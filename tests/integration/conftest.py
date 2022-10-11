import logging
import os
import shlex
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
async def kubeconfig(ops_test):
    kubeconfig_path = ops_test.tmp_path / "kubeconfig"
    rc, stdout, stderr = await ops_test.run(
        "juju",
        "scp",
        "kubernetes-control-plane/leader:/home/ubuntu/config",
        kubeconfig_path,
    )
    if rc != 0:
        log.error(f"retcode: {rc}")
        log.error(f"stdout:\n{stdout.strip()}")
        log.error(f"stderr:\n{stderr.strip()}")
        pytest.fail("Failed to copy kubeconfig from kubernetes-control-plane")
    assert Path(kubeconfig_path).stat().st_size, "kubeconfig file is 0 bytes"
    yield kubeconfig_path


@pytest.fixture(scope="module")
async def client(kubeconfig):
    config = KubeConfig.from_file(kubeconfig)
    client = Client(
        config=config.get(context_name="juju-context"),
        trust_env=False,
    )
    load_in_cluster_generic_resources(client)
    yield client


@pytest.fixture(scope="module")
def kubectl(ops_test, kubeconfig):
    """Supports running kubectl exec commands."""

    KubeCtl = Union[str, Tuple[int, str, str]]

    async def f(*args, **kwargs) -> KubeCtl:
        """Actual callable returned by the fixture.
        :returns: if kwargs[check] is True or undefined, stdout is returned
                  if kwargs[check] is False, Tuple[rc, stdout, stderr] is returned
        """
        cmd = ["kubectl", "--kubeconfig", str(kubeconfig)] + list(args)
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
async def k8s_storage(kubectl):
    await kubectl("apply", "-f", "tests/data/vsphere-storageclass.yaml")


@pytest.fixture(scope="module")
def module_name(request):
    return request.module.__name__.replace("_", "-")


@pytest.fixture(scope="module")
async def k8s_cloud(k8s_storage, kubeconfig, module_name, ops_test, request):
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
        os.environ["KUBECONFIG"] = str(kubeconfig)
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
    path = Path.cwd() / "tests/data/test_subnet.yaml"
    with open(path) as f:
        for rsc in codecs.load_all_yaml(f):
            client.create(rsc)

    yield

    log.info("Deleting Kube-OVN subnet")
    with open(path) as f:
        for rsc in codecs.load_all_yaml(f):
            client.delete(
                type(rsc), rsc.metadata.name, namespace=rsc.metadata.namespace
            )

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
