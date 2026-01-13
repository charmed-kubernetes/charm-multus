import logging
import random
import shlex
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Union

import pytest
import pytest_asyncio
from kubernetes import config as k8s_config
from kubernetes.client import Configuration
from lightkube import Client, KubeConfig, codecs
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Namespace, Pod
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption(
        "--k8s-cloud",
        action="store",
        help="Juju kubernetes cloud to reuse; if not provided, will generate a new cloud",
    )


@dataclass
class CharmedKubernetes:
    kubeconfig: Path
    model: str


@pytest_asyncio.fixture(scope="module")
async def charmed_kubernetes(ops_test):
    with ops_test.model_context("main") as model:
        deploy, control_plane_app = True, "kubernetes-control-plane"
        current_model = ops_test.request.config.option.model
        if current_model:
            control_plane_apps = [
                app_name
                for app_name, app in model.applications.items()
                if "kubernetes-control-plane" in app.charm_url
            ]
            if not control_plane_apps:
                pytest.fail(
                    f"Model {current_model} doesn't contain {control_plane_app} charm"
                )
            deploy, control_plane_app = False, control_plane_apps[0]

        if deploy:
            overlays = [
                ops_test.Bundle("kubernetes-core", channel="edge"),
                Path("tests/data/kube-ovn-overlay.yaml"),
                Path("tests/data/vsphere-overlay.yaml"),
            ]

            log.info("Rendering overlays...")
            bundle, *overlays = await ops_test.async_render_bundles(*overlays)

            log.info("Deploying k8s-core...")
            overlays = " ".join(f"--overlay={f}" for f in overlays)
            juju_cmd = (
                f"deploy -m {ops_test.model_full_name} {bundle} --trust {overlays}"
            )
            await ops_test.juju(*shlex.split(juju_cmd), fail_msg="Bundle deploy failed")

        await model.wait_for_idle(status="active", timeout=60 * 60)
        kubeconfig_path = ops_test.tmp_path / "kubeconfig"
        retcode, stdout, stderr = await ops_test.run(
            "juju",
            "scp",
            f"{control_plane_app}/leader:/home/ubuntu/config",
            kubeconfig_path,
        )
        if retcode != 0:
            log.error(f"retcode: {retcode}")
            log.error(f"stdout:\n{stdout.strip()}")
            log.error(f"stderr:\n{stderr.strip()}")
            pytest.fail("Failed to copy kubeconfig from kubernetes-control-plane")
        assert Path(kubeconfig_path).stat().st_size, "kubeconfig file is 0 bytes"
    yield CharmedKubernetes(kubeconfig_path, model)


@pytest.fixture(scope="module")
def module_name(request):
    return request.module.__name__.replace("_", "-")


@pytest_asyncio.fixture(scope="module")
async def k8s_client(charmed_kubernetes, module_name):
    rand_str = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    namespace = f"{module_name}-{rand_str}"
    config = KubeConfig.from_file(charmed_kubernetes.kubeconfig)
    client = Client(
        config=config.get(context_name="juju-context"),
        namespace=namespace,
        trust_env=False,
    )
    load_in_cluster_generic_resources(client)
    namespace_obj = Namespace(metadata=ObjectMeta(name=namespace))
    log.info(f"Creating namespace {namespace} for use with lightkube client")
    client.create(namespace_obj)
    yield client, namespace
    log.info(f"Deleting namespace {namespace} for use with lightkube client")
    client.delete(Namespace, namespace)


@pytest.fixture(scope="module")
def kubectl(ops_test, charmed_kubernetes):
    """Supports running kubectl exec commands."""

    KubeCtl = Union[str, Tuple[int, str, str]]

    async def f(*args, **kwargs) -> KubeCtl:
        """Actual callable returned by the fixture.
        :returns: if kwargs[check] is True or undefined, stdout is returned
                  if kwargs[check] is False, Tuple[rc, stdout, stderr] is returned
        """
        cmd = ["kubectl", "--kubeconfig", str(charmed_kubernetes.kubeconfig)] + list(
            args
        )
        check = kwargs["check"] = kwargs.get("check", True)
        rc, stdout, stderr = await ops_test.run(*cmd, **kwargs)
        if not check:
            return rc, stdout, stderr
        return stdout

    return f


@pytest.fixture(scope="module")
def kubectl_exec(kubectl):
    async def f(name: str, namespace: str, cmd: str, **kwds):
        shcmd = f'exec {name} -n {namespace} -- sh -c "{cmd}"'
        return await kubectl(*shlex.split(shcmd), **kwds)

    return f


@pytest_asyncio.fixture(scope="module")
async def k8s_model(ops_test: OpsTest, charmed_kubernetes):
    model_alias = "k8s-model"
    log.info("Creating k8s model ...")
    try:
        config = type.__call__(Configuration)
        k8s_config.load_config(
            client_configuration=config, config_file=str(charmed_kubernetes.kubeconfig)
        )
        cloud_name = ops_test.request.config.getoption("--k8s-cloud")
        k8s_cloud = await ops_test.add_k8s(
            cloud_name, kubeconfig=config, skip_storage=False
        )
        k8s_model = await ops_test.track_model(
            model_alias, cloud_name=k8s_cloud, keep=ops_test.ModelKeep.NEVER
        )
        yield k8s_model, model_alias
    finally:
        await ops_test.forget_model(model_alias, timeout=10 * 60, allow_failure=True)


@pytest.fixture()
def kube_ovn_subnet(k8s_client):
    client, _ = k8s_client
    log.info("Creating Kube-OVN subnet")
    path = Path("tests/data/test_subnet.yaml")
    resources = []
    for rsc in codecs.load_all_yaml(path.read_text()):
        resources.append(client.create(rsc))
    try:
        yield
    finally:
        log.info("Deleting Kube-OVN subnet")
        for rsc in reversed(resources):
            client.delete(
                type(rsc), rsc.metadata.name, namespace=rsc.metadata.namespace
            )
        log.info("Removed Kube-OVN subnet")


@pytest.fixture()
async def kube_ovn_nad(ops_test, kube_ovn_subnet, k8s_model):
    log.info("Configuring Multus Charm with Kube-OVN NAD")
    _, k8s_alias = k8s_model
    with ops_test.model_context(k8s_alias) as model:
        multus_app = model.applications["multus"]
        path = Path.cwd() / "tests/data/kube_ovn_nad.yaml"
        with open(path) as f:
            await multus_app.set_config({"network-attachment-definitions": f.read()})
            yield
            log.info("Deleting Kube-OVN NAD")
            await multus_app.set_config({"network-attachment-definitions": ""})
    log.info("Removed Kube-OVN NAD")


@pytest.fixture()
def multinic_pod(k8s_client, kube_ovn_nad):
    log.info("Creating Test Pod")
    client, _ = k8s_client
    path = Path.cwd() / "tests/data/multinic_pod.yaml"
    resources = []
    for rsc in codecs.load_all_yaml(path.read_text()):
        resources.append(client.create(rsc))
    pod = list(client.list(Pod, namespace="default"))[0]

    client.wait(Pod, "multinicpod", for_conditions=["Ready"], namespace="default")
    try:
        yield pod
    finally:
        log.info("Deleting Test Pod")
        for rsc in reversed(resources):
            client.delete(
                type(rsc), rsc.metadata.name, namespace=rsc.metadata.namespace
            )
        log.info("Removed Test Pod")
