# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import logging
import unittest.mock as mock

import ops.testing
import pytest
from conftest import MockActionEvent
from ops.manifests import ManifestClientError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness
from yaml import YAMLError

from charm import MultusCharm
from net_attach_definitions import ValidationError

ops.testing.SIMULATE_CAN_CONNECT = True

TEST_NAD = """apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
name: flannel
namespace: default
spec:
config: |
    {
        "cniVersion": "0.3.1",
        "plugins": [
        {
            "type": "flannel",
            "delegate": {
            "hairpinMode": true,
            "isDefaultGateway": true
            }
        },
        {
            "type": "portmap",
            "capabilities": {"portMappings": true},
            "snat": true
        }
        ]
    }
"""


@pytest.fixture
def harness():
    harness = Harness(MultusCharm)
    try:
        yield harness
    finally:
        harness.cleanup()


@pytest.fixture
def charm(harness):
    harness.begin_with_initial_hooks()
    yield harness.charm


@mock.patch("net_attach_definitions.NetworkAttachDefinitions.scrub_resources")
def test_scrub_net_attach_defs(mock_scrub, charm):
    event = mock.MagicMock()
    charm._scrub_net_attach_defs(event)
    mock_scrub.assert_called_once()


@pytest.mark.parametrize(
    "config_value,stored_value",
    [
        pytest.param(TEST_NAD, "", id="Create new NADs"),
        pytest.param("", TEST_NAD, id="Remove NADs"),
        pytest.param("", "", id="No change"),
    ],
)
@mock.patch("net_attach_definitions.NetworkAttachDefinitions.apply_manifests")
def test_on_config_changed(mock_apply, harness, charm, config_value, stored_value):
    charm.stored.nad_manifest = stored_value
    harness.update_config({"network-attachment-definitions": config_value})
    if config_value or stored_value:
        mock_apply.assert_called_once_with(config_value)
        assert isinstance(charm.unit.status, ActiveStatus)
    else:
        mock_apply.assert_not_called()


@pytest.mark.parametrize(
    "side_effect",
    [
        pytest.param(YAMLError("Error"), id="Invalid YAML"),
        pytest.param(ValidationError("Error"), id="Invalid Manifest"),
    ],
)
@mock.patch("net_attach_definitions.NetworkAttachDefinitions.apply_manifests")
def test_on_config_changed_raises(mock_apply, harness, charm, side_effect):
    mock_apply.side_effect = side_effect
    harness.set_leader()
    harness.update_config({"network-attachment-definitions": "\tNOT A YAML!"})
    assert isinstance(charm.unit.status, BlockedStatus)


@mock.patch("net_attach_definitions.NetworkAttachDefinitions.apply_manifests")
def test_on_config_changed_api_error(mock_apply, harness, charm, caplog):
    mock_apply.side_effect = ManifestClientError("foo")
    harness.set_leader()
    with caplog.at_level(logging.INFO):
        charm.stored.nad_manifest = TEST_NAD
        charm._on_config_changed("mock-event")
        assert "Failed to apply net-attach-def manifests:" in caplog.text


@mock.patch("net_attach_definitions.NetworkAttachDefinitions.scrub_resources")
def test_scrub_net_attach_defs_api_error(mock_scrub, harness, charm, caplog):
    mock_scrub.side_effect = ManifestClientError("foo")
    harness.set_leader()
    with caplog.at_level(logging.INFO):
        event = mock.MagicMock()
        charm._scrub_net_attach_defs(event)
        assert "Failed to scrub net-attach-defs from the cluster" in caplog.text


@mock.patch("net_attach_definitions.NetworkAttachDefinitions.remove_resources")
def test_on_remove_api_error(mock_remove, harness, charm, caplog):
    mock_remove.side_effect = ManifestClientError("foo")
    harness.set_leader()
    with caplog.at_level(logging.INFO):
        mock_event = mock.MagicMock()
        charm._on_remove(mock_event)
        mock_event.defer.assert_called_once()
        assert "Failed to remove net-attach-defs from the cluster" in caplog.text


@pytest.mark.parametrize("deployed", [True, False])
@pytest.mark.parametrize("unready", ["Waiting", ""])
def test_update_status(harness, deployed, unready):
    with mock.patch(
        "charm.Collector.unready", new_callable=mock.PropertyMock, return_value=unready
    ):
        harness.set_leader()
        harness.begin_with_initial_hooks()
        charm = harness.charm
        charm.stored.deployed = deployed
        charm._update_status("mock-event")
        if deployed:
            if unready:
                assert isinstance(charm.unit.status, WaitingStatus)
            else:
                assert isinstance(charm.unit.status, ActiveStatus)


@mock.patch("charm.MultusManifests.apply_manifests")
def test_install_or_upgrade(mock_apply, harness):
    harness.set_leader()
    harness.disable_hooks()
    harness.begin()
    harness.charm._install_or_upgrade("mock_event")
    mock_apply.assert_called_once()
    assert harness.charm.stored.deployed


@mock.patch("net_attach_definitions.NetworkAttachDefinitions.remove_resources")
@mock.patch("charm.MultusManifests.delete_manifests")
def test_on_remove(mock_remove, mock_delete, harness):
    harness.begin_with_initial_hooks()
    harness.charm._on_remove("mock-event")
    mock_remove.assert_called_once()
    mock_delete.assert_called_once()


@mock.patch("charm.Collector.list_versions")
def test_list_versions(mock_list, harness):
    harness.begin_with_initial_hooks()
    harness.charm._list_versions("mock_event")
    mock_list.assert_called_once_with("mock_event")


@mock.patch("charm.Collector.list_resources")
def test_list_resources(mock_list, harness):
    harness.begin_with_initial_hooks()
    mock_event = MockActionEvent({})
    harness.charm._list_resources(mock_event)
    mock_list.assert_called_once_with(mock_event, manifests="multus", resources="")


@mock.patch("charm.Collector.apply_missing_resources")
def test_sync_resources(mock_sync, harness):
    harness.begin_with_initial_hooks()
    mock_event = MockActionEvent({})
    harness.charm._sync_resources(mock_event)
    mock_sync.assert_called_once_with(mock_event, manifests="multus", resources="")


@mock.patch("charm.Collector.apply_missing_resources")
def test_sync_resources_failure(mock_sync, harness):
    harness.begin_with_initial_hooks()
    mock_sync.side_effect = ManifestClientError("boo", "foo")
    output = harness.run_action("sync-resources", {})
    mock_sync.assert_called_once()
    first_call, *_ = mock_sync.call_args_list
    mock_sync.assert_called_once_with(
        first_call.args[0], manifests="multus", resources=""
    )
    assert "Failed to sync missing resources:" in output.results["result"]
