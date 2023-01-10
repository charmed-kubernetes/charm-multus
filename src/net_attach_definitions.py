# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Module for managing Network Attachment Definitions"""
import logging
import traceback
from typing import List, Set

import yaml
from cerberus import Validator
from lightkube import Client, codecs
from lightkube.generic_resource import create_namespaced_resource
from ops.manifests import ManifestClientError
from ops.manifests.manipulations import HashableResource
from tenacity import retry
from tenacity.retry import retry_if_exception_type
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_exponential

log = logging.getLogger(__file__)


class NetworkAttachDefinitions:
    """Class used for managing the lifecycle of the Network Attachment Definitions
    for the Multus charm.
    """

    def __init__(self, client: Client = None):
        """Create a NetworkAttachDefinitions object

        @param client: lightkube client
        """
        self.client = client if client else Client()
        self.resources: Set[HashableResource] = set()
        self.validator = Validator()
        self.nad_resource = create_namespaced_resource(
            "k8s.cni.cncf.io",
            "v1",
            "NetworkAttachmentDefinition",
            "network-attachment-definitions",
        )

    @property
    def schema(self) -> dict:
        """Load the NetworkAttachmentDefinition validation schema"""
        try:
            with open("schemas/NetworkAttachDefinition.yaml", "r") as f:
                return yaml.safe_load(f)
        except yaml.YAMLError:
            log.error(f"Failed reading validation schema: {traceback.format_exc()}")
            raise

    @retry(
        reraise=True,
        retry=retry_if_exception_type(ManifestClientError),
        wait=wait_exponential(max=10),
        stop=stop_after_attempt(3),
    )
    def apply_manifests(self, manifests: str) -> None:
        try:
            resources = self._validate_and_load(manifests)
        except (ValidationError, yaml.YAMLError) as e:
            log.error(e)
            raise

        applied: Set[HashableResource] = set()
        for rsc in resources:
            log.info(f"Applying {rsc}")
            try:
                self.client.apply(rsc.resource, force=True)
                applied.add(rsc)
            except ManifestClientError as e:
                log.exception(f"Failed applying {rsc}: {e}. Retrying...")
                raise

        log.info(f"Applied {len(applied)} NetworkAttachmentDefinitions")
        self.resources = applied
        self.scrub_resources()

    def remove_resources(self) -> None:
        try:
            resources = self._list_resources()
            self._delete_resources(resources)
        except ManifestClientError:
            raise

        log.info(f"Removed {len(resources)} NetworkAttachmentDefinitions")

    def scrub_resources(self) -> None:
        try:
            installed = self._list_resources()
            remnants = installed.difference(self.resources)
            self._delete_resources(remnants)
        except ManifestClientError:
            raise

        log.info(f"Removed {len(remnants)} NetworkAttachmentDefinitions")

    @retry(
        reraise=True,
        retry=retry_if_exception_type(ManifestClientError),
        wait=wait_exponential(max=10),
        stop=stop_after_attempt(3),
    )
    def _delete_resources(self, resources: Set[HashableResource]):
        for rsc in resources:
            try:
                self.client.delete(
                    type(rsc.resource), rsc.name, namespace=rsc.namespace
                )
            except ManifestClientError as e:
                log.error(f"Failed to remove {rsc}: {e}. Retrying...")
                raise

    def _load_and_wrap(self, manifests: str) -> List[HashableResource]:
        resources = list(yaml.safe_load_all(manifests))
        for rsc in resources:
            labels = rsc["metadata"].setdefault("labels", {})
            labels["app.kubernetes.io/managed-by"] = "charm-multus"
        return [HashableResource(codecs.from_dict(rsc)) for rsc in resources]

    @retry(
        reraise=True,
        retry=retry_if_exception_type(ManifestClientError),
        wait=wait_exponential(max=10),
        stop=stop_after_attempt(3),
    )
    def _list_resources(self):
        try:
            resources = set(
                HashableResource(_)
                for _ in self.client.list(
                    self.nad_resource,
                    labels={"app.kubernetes.io/managed-by": "charm-multus"},
                    namespace="*",
                )
            )
            return resources
        except ManifestClientError:
            log.error(
                "Failed to get Network Attachment Definitions in cluster. Retrying..."
            )
            raise

    def _validate_and_load(self, manifests: str) -> List[HashableResource]:
        try:
            self._validate_manifests(manifests)
        except (ValidationError, yaml.YAMLError):
            raise
        return self._load_and_wrap(manifests)

    def _validate_manifests(self, manifests: str) -> None:
        try:
            errors = ""
            nads = list(yaml.safe_load_all(manifests))
            for nad in nads:
                if not self.validator.validate(nad, self.schema):
                    errors += yaml.safe_dump(self.validator.errors)

            if errors:
                raise ValidationError(errors)
        except yaml.YAMLError:
            log.error("Failed to parse NetworkAttachmentDefinitions")
            raise


class ValidationError(Exception):
    """Exception to raise for errors in the Validation process
    for Network Attachment Definitions
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"Error validating NetworkAttachmentDefinitions: {self.message}"
