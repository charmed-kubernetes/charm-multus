import logging
import os
import shlex
from collections import namedtuple
from pathlib import Path
from random import choices
from string import ascii_lowercase, digits
from typing import Tuple, Union

import juju.utils
import pytest
import yaml
from lightkube import Client, KubeConfig, codecs
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption(
        "--k8s-cloud",
        action="store",
        help="Juju kubernetes cloud to reuse; if not provided, will generate a new cloud",
    )


@pytest.fixture(scope="module")
async def charmed_kubernetes(ops_test):
    CharmedKubernetes = namedtuple("CharmedKubernetes", "kubeconfig,model")
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
async def client(charmed_kubernetes):
    config = KubeConfig.from_file(charmed_kubernetes.kubeconfig)
    client = Client(
        config=config.get(context_name="juju-context"),
        trust_env=False,
    )
    load_in_cluster_generic_resources(client)
    yield client


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


@pytest.fixture(scope="module")
def module_name(request):
    return request.module.__name__.replace("_", "-")


@pytest.fixture(scope="module")
async def k8s_cloud(charmed_kubernetes, module_name, ops_test, request):
    """Use an existing k8s-cloud or create a k8s-cloud
    for deploying a new k8s model into"""
    cloud_name = request.config.option.k8s_cloud or f"{module_name}-k8s-cloud"
    controller = await ops_test.model.get_controller()
    try:
        current_clouds = await controller.clouds()
        if f"cloud-{cloud_name}" in current_clouds.clouds:
            yield cloud_name
            return
    finally:
        await controller.disconnect()

    with ops_test.model_context("main"):
        log.info(f"Adding cloud '{cloud_name}'...")
        os.environ["KUBECONFIG"] = str(charmed_kubernetes.kubeconfig)
        await ops_test.juju(
            "add-k8s",
            cloud_name,
            f"--controller={ops_test.controller_name}",
            "--client",
            check=True,
            fail_msg=f"Failed to add-k8s {cloud_name}",
        )
    yield cloud_name

    with ops_test.model_context("main"):
        log.info(f"Removing cloud '{cloud_name}'...")
        await ops_test.juju(
            "remove-cloud",
            cloud_name,
            "--controller",
            ops_test.controller_name,
            "--client",
            check=True,
        )


@pytest.fixture(scope="module")
async def k8s_model(k8s_cloud, ops_test: OpsTest):
    model_alias = "k8s-model"
    log.info("Creating k8s model ...")
    # Create model with Juju CLI to work around a python-libjuju bug
    # https://github.com/juju/python-libjuju/issues/603
    model_name = "test-multus-" + "".join(choices(ascii_lowercase + digits, k=4))
    await ops_test.juju(
        "add-model",
        f"--controller={ops_test.controller_name}",
        model_name,
        k8s_cloud,
        "--no-switch",
    )
    model = await ops_test.track_model(
        model_alias,
        model_name=model_name,
        cloud_name=k8s_cloud,
        credential_name=k8s_cloud,
        keep=False,
    )
    model_uuid = model.info.uuid
    yield model, model_alias, model_name
    timeout = 10 * 60

    if multus_app := model.applications.get("multus"):
        await multus_app.destroy(force=True)

    await ops_test.forget_model(model_alias, timeout=timeout, allow_failure=False)

    async def model_removed():
        _, stdout, stderr = await ops_test.juju("models", "--format", "yaml")
        if _ != 0:
            return False
        model_list = yaml.safe_load(stdout)["models"]
        which = [m for m in model_list if m["model-uuid"] == model_uuid]
        return len(which) == 0

    log.info("Removing k8s model")
    await juju.utils.block_until_with_coroutine(model_removed, timeout=timeout)
    # Update client's model cache
    await ops_test.juju("models")
    log.info("k8s model removed")


@pytest.fixture()
def kube_ovn_subnet(client):
    log.info("Creating Kube-OVN subnet")
    path = Path("tests/data/test_subnet.yaml")
    resources = codecs.load_all_yaml(path.read_text())
    for rsc in resources:
        client.create(rsc)

    yield

    log.info("Deleting Kube-OVN subnet")
    for rsc in resources:
        client.delete(type(rsc), rsc.metadata.name, namespace=rsc.metadata.namespace)
    log.info("Removed Kube-OVN subnet")


@pytest.fixture()
async def kube_ovn_nad(ops_test, kube_ovn_subnet, k8s_model):
    log.info("Configuring Multus Charm with Kube-OVN NAD")
    _, k8s_alias, _ = k8s_model
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
def multinic_pod(client: Client, kube_ovn_nad):
    log.info("Creating Test Pod")
    path = Path.cwd() / "tests/data/multinic_pod.yaml"
    with open(path) as f:
        for rsc in codecs.load_all_yaml(f):
            client.create(rsc)
    pod = list(client.list(Pod, namespace="default"))[0]

    client.wait(Pod, "multinicpod", for_conditions=["Ready"], namespace="default")

    yield pod

    log.info("Deleting Test Pod")
    with open(path) as f:
        for rsc in codecs.load_all_yaml(f):
            client.delete(
                type(rsc), rsc.metadata.name, namespace=rsc.metadata.namespace
            )

    log.info("Removed Test Pod")
