# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import re
from pathlib import Path
from unittest import mock

import pytest
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import MultusCharm


BUNDLES = sorted(path.name for path in Path("upstream/multus/manifests").iterdir())


@pytest.fixture
def harness():
    harness = Harness(MultusCharm)
    harness.disable_hooks()
    harness.set_leader()
    harness.begin()
    yield harness
    harness.cleanup()


@pytest.mark.parametrize("release", [None, "", *BUNDLES])
def test_loadable_thin_bundles(harness, release):
    """All selectors and the default retain primary-CNI/NAD and image wiring."""
    if release is not None:
        harness.update_config({"release": release})
    manifests = harness.charm.manifests
    resources = {resource.kind: resource.resource for resource in manifests.resources}
    assert len(resources) == 6
    assert resources["CustomResourceDefinition"].metadata.name == (
        "network-attachment-definitions.k8s.cni.cncf.io"
    )
    daemonset = resources["DaemonSet"]
    assert daemonset.metadata.name == "kube-multus-ds"
    assert daemonset.metadata.namespace == "kube-system"
    assert daemonset.spec.selector.matchLabels == {"name": "multus"}
    assert daemonset.spec.updateStrategy.type == "RollingUpdate"
    spec = daemonset.spec.template.spec
    assert spec.hostNetwork
    assert spec.serviceAccountName == "multus"
    assert {volume.hostPath.path for volume in spec.volumes if volume.hostPath} == {
        "/etc/cni/net.d",
        "/opt/cni/bin",
    }
    assert "--multus-conf-file=auto" in spec.containers[0].args
    assert spec.containers[0].command in [["/entrypoint.sh"], ["/thin_entrypoint"]]
    containers = spec.containers + spec.initContainers
    assert len(containers) == 2
    assert len({container.image for container in containers}) == 1
    for container in containers:
        assert re.fullmatch(
            r"ghcr.io/canonical/cdk/k8snetworkplumbingwg/multus-cni:v\d+\.\d+\.\d+",
            container.image,
        )


@pytest.mark.parametrize("deployed", [True, False])
@pytest.mark.parametrize(
    "handler",
    ["_install_or_upgrade", "_on_config_changed", "_update_status"],
)
def test_unknown_legacy_image_blocks_reconciliation(harness, deployed, handler):
    """Never infer a version from the historical mutable selector or replace it."""
    harness.update_config({"release": "v4.0"})
    charm = harness.charm
    charm.stored.deployed = deployed
    with mock.patch.object(charm.manifests, "apply_manifests") as apply, mock.patch.object(
        charm.nad_manager, "apply_manifests"
    ) as apply_nads:
        getattr(charm, handler)(mock.MagicMock())
    apply.assert_not_called()
    apply_nads.assert_not_called()
    assert isinstance(charm.unit.status, BlockedStatus)
    assert "Inspect running image digests" in charm.unit.status.message
    assert "explicit patch" in charm.unit.status.message


@pytest.mark.parametrize(
    "handler,collector_method",
    [("_sync_resources", "apply_missing_resources"), ("_scrub_resources", "scrub_resources")],
)
def test_legacy_actions_cannot_bypass_guard(harness, handler, collector_method):
    harness.update_config({"release": "v4.0"})
    event = mock.MagicMock()
    with mock.patch.object(harness.charm.collector, collector_method) as collect:
        getattr(harness.charm, handler)(event)
    collect.assert_not_called()
    event.fail.assert_called_once_with(harness.charm.unit.status.message)


def test_explicit_patch_choice_unblocks_upgrade(harness):
    harness.update_config({"release": "v4.0"})
    charm = harness.charm
    charm.stored.deployed = True
    charm._install_or_upgrade(mock.MagicMock())
    assert isinstance(charm.unit.status, BlockedStatus)
    with mock.patch.object(charm.manifests, "apply_manifests") as apply, mock.patch(
        "charm.Collector.unready", new_callable=mock.PropertyMock, return_value=[]
    ):
        harness.update_config({"release": charm.manifests.default_release})
        charm._install_or_upgrade(mock.MagicMock())
        apply.assert_called_once()
    assert isinstance(charm.unit.status, ActiveStatus)
