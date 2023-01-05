import asyncio
import logging
import re
import shlex
import time
from pathlib import Path

import pytest

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_deploy_charm(ops_test, k8s_model):
    log.info("Build charm...")
    charm = await ops_test.build_charm(".")

    _, k8s_alias, model_name = k8s_model
    with ops_test.model_context(k8s_alias) as model:
        juju_cmd = f"deploy {charm.resolve()} -m {model_name} --trust"
        await ops_test.juju(*shlex.split(juju_cmd), fail_msg="Deploy charm failed")

        await model.block_until(lambda: "multus" in model.applications, timeout=60 * 3)
        await model.wait_for_idle(status="active", timeout=60 * 5)

    # wait until all kubernetes-worker units have multus CNI config installed
    deadline = time.time() + 600
    for unit in ops_test.model.applications["kubernetes-worker"].units:
        log.info("waiting for Multus config on unit %s" % unit.name)
        while time.time() < deadline:
            rc, _, _ = await ops_test.juju(
                "ssh",
                "-m",
                ops_test.model_full_name,
                unit.name,
                "--",
                "sudo",
                "ls",
                "/etc/cni/net.d",
                "|",
                "grep",
                "multus",
            )
            if rc == 0:
                break
            await asyncio.sleep(1)
        else:
            pytest.fail("timed out waiting for Multus config on unit %s" % unit.name)


async def test_pod_interfaces(multinic_pod, kubectl_exec):
    pod = "multinicpod"
    output = await kubectl_exec(pod, "default", "ip a")
    matches = re.findall(r"inet\s10.166.0.\d+\/16", output)
    assert len(matches) == 2
