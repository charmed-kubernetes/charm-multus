import logging
import unittest.mock as mock
from unittest.mock import call

import pytest
import yaml
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Pod
from ops.manifests.manipulations import HashableResource

from net_attach_definitions import NetworkAttachDefinitions, ValidationError

VALID_YAML = """apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  name: sriov
  namespace: default
  annotations:
    k8s.v1.cni.cncf.io/resourceName: intel.com/sriov
spec:
  config: |
    {
      "type": "sriov",
      "ipam": {
        "type": "host-local",
        "ranges": [[{
            "subnet": "10.123.123.0/24"
        }]]
      }
    }
"""

INVALID_YAML = """apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  annotations:
    k8s.v1.cni.cncf.io/resourceName: intel.com/sriov
spec:
  other: |
    {
      "type": "sriov",
      "ipam": {
        "type": "host-local",
        "ranges": [[{
            "subnet": "10.123.123.0/24"
        }]]
      }
    }
"""


@pytest.mark.parametrize(
    "context_raised,manifest",
    [
        pytest.param(
            pytest.raises(ValidationError),
            INVALID_YAML,
            id="Invalid Manifest",
        ),
        pytest.param(
            pytest.raises(yaml.YAMLError), "{NOT,A,\tYAML}", id="Invalid YAML"
        ),
    ],
)
def test_validate_manifests(context_raised, manifest):
    with context_raised:
        NetworkAttachDefinitions()._validate_manifests(manifest)


@pytest.mark.parametrize(
    "context_raised,manifest",
    [
        pytest.param(
            pytest.raises(ValidationError),
            INVALID_YAML,
            id="Invalid Manifest",
        ),
    ],
)
def test_validate_and_load(context_raised, manifest):
    with context_raised as err:
        resources = NetworkAttachDefinitions()._validate_and_load(manifest)
    if not err:
        assert resources


@pytest.mark.parametrize(
    "installed,resources,log_message",
    [
        pytest.param(
            [
                Pod(
                    kind="Pod",
                    metadata=ObjectMeta(name=f"pod-{n}", namespace="mock-ns"),
                )
                for n in range(5)
            ],
            [
                HashableResource(
                    Pod(
                        kind="Pod",
                        metadata=ObjectMeta(name=f"pod-{n}", namespace="mock-ns"),
                    )
                )
                for n in range(0, 3)
            ],
            "Removed 2 NetworkAttachmentDefinitions",
            id="Remnants",
        ),
        pytest.param(
            [
                Pod(
                    kind="Pod",
                    metadata=ObjectMeta(name=f"pod-{n}", namespace="mock-ns"),
                )
                for n in range(5)
            ],
            [
                HashableResource(
                    Pod(
                        kind="Pod",
                        metadata=ObjectMeta(name=f"pod-{n}", namespace="mock-ns"),
                    )
                )
                for n in range(5)
            ],
            "Removed 0 NetworkAttachmentDefinitions",
            id="Non Remnants",
        ),
    ],
)
def test_scrub_resources(lk_nad_client, installed, resources, log_message, caplog):
    mock_list = lk_nad_client.list
    mock_list.return_value = installed
    nad = NetworkAttachDefinitions()
    nad.resources = resources
    with caplog.at_level(logging.INFO):
        nad.scrub_resources()
        assert log_message in caplog.text


def test_remove_resources(lk_nad_client):
    mock_list = lk_nad_client.list
    mock_delete: mock.MagicMock = lk_nad_client.delete
    resources = [
        Pod(
            kind="Pod",
            metadata=ObjectMeta(name=f"pod-{n}", namespace="mock-ns"),
        )
        for n in range(5)
    ]
    mock_list.return_value = resources
    NetworkAttachDefinitions().remove_resources()
    calls = [
        call(type(rsc), rsc.metadata.name, namespace=rsc.metadata.namespace)
        for rsc in resources
    ]
    mock_delete.assert_has_calls(calls, any_order=True)


@pytest.mark.parametrize(
    "manifest,log_message",
    [
        pytest.param(
            VALID_YAML,
            "Applied 1 NetworkAttachmentDefinitions",
            id="Valid YAML",
        ),
    ],
)
def test_apply_manifests(manifest, log_message, caplog):
    with caplog.at_level(logging.INFO):
        NetworkAttachDefinitions().apply_manifests(manifest)
        assert log_message in caplog.text


@pytest.mark.parametrize(
    "context_raised,manifest",
    [
        pytest.param(
            pytest.raises(ValidationError),
            INVALID_YAML,
            id="Invalid Manifest",
        ),
        pytest.param(
            pytest.raises(yaml.YAMLError),
            "{NOT,A,\tYAML}",
            id="Invalid YAML",
        ),
    ],
)
def test_apply_manifests_raises(context_raised, manifest):
    with context_raised:
        NetworkAttachDefinitions().apply_manifests(manifest)


def test_remove_resources_api_error(api_error_class, lk_nad_client, caplog):
    lk_nad_client.list.side_effect = api_error_class()
    with pytest.raises(api_error_class):
        NetworkAttachDefinitions().remove_resources()
        assert "Failed to get Network Attachment Definitions" in caplog.text


def test_scrub_resources_api_error(api_error_class, lk_nad_client, caplog):
    lk_nad_client.list.side_effect = api_error_class()
    with pytest.raises(api_error_class):
        NetworkAttachDefinitions().scrub_resources()
        assert "Failed to get Network Attachment Definitions" in caplog.text


def test_delete_resources_api_error(api_error_class, lk_nad_client, caplog):
    lk_nad_client.delete.side_effect = api_error_class()
    with pytest.raises(api_error_class):
        resources = [
            HashableResource(
                Pod(
                    kind="Pod",
                    metadata=ObjectMeta(name=f"pod-{n}", namespace="mock-ns"),
                )
            )
            for n in range(5)
        ]
        NetworkAttachDefinitions()._delete_resources(resources)
        assert "Retrying..." in caplog.text


def test_apply_manifests_api_error(api_error_class, lk_nad_client, caplog):
    lk_nad_client.apply.side_effect = api_error_class()
    with pytest.raises(api_error_class):
        NetworkAttachDefinitions().apply_manifests(VALID_YAML)
        assert "Failed applying" in caplog.text


@mock.patch("yaml.safe_load")
def test_schema_not_found(mock_safe, caplog):
    mock_safe.side_effect = yaml.YAMLError("Error")
    with caplog.at_level(logging.INFO):
        with pytest.raises(yaml.YAMLError):
            NetworkAttachDefinitions().schema
            assert "Failed reading validation schema" in caplog.text
