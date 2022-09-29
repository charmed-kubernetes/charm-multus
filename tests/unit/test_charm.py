# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest.mock as mock

import ops.testing
import pytest
from conftest import MockActionEvent
from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import MultusCharm

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


@mock.patch("net_attach_definitions.NetworkAttachDefinitions.scrub_resources")
def test_scrub_net_attach_defs(mock_scrub, harness):
    harness.begin_with_initial_hooks()
    harness.charm._scrub_net_attach_defs("mock_event")
    mock_scrub.assert_called_once()


@pytest.mark.parametrize(
    "config_value",
    [pytest.param(TEST_NAD, id="Config set"), pytest.param("", id="No config")],
)
@mock.patch("net_attach_definitions.NetworkAttachDefinitions.apply_manifests")
def test_on_config_changed(mock_apply, harness, config_value):
    harness.begin_with_initial_hooks()
    harness.update_config({"network-attachment-definitions": config_value})
    if config_value:
        mock_apply.assert_called_once_with(config_value)
    else:
        mock_apply.assert_not_called()


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
    mock_list.assert_called_once_with(mock_event, resources="")


@mock.patch("charm.Collector.scrub_resources")
def test_scrub_resources(mock_list, harness):
    harness.begin_with_initial_hooks()
    mock_event = MockActionEvent({})
    harness.charm._scrub_resources(mock_event)
    mock_list.assert_called_once_with(mock_event, resources="")
