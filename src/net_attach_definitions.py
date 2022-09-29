# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Module for managing Network Attachment Definitions"""
import logging
from functools import cached_property
from typing import List, Set

import yaml
from cerberus import Validator
from lightkube import Client
from lightkube.codecs import load_all_yaml
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import create_namespaced_resource
from ops.manifests.manipulations import HashableResource

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

    @cached_property
    def schema(self) -> dict:
        """Load the NetworkAttachmentDefinition validation schema"""
        try:
            with open("schemas/NetworkAttachDefinition.yaml", "r") as f:
                return yaml.safe_load(f)
        except yaml.YAMLError:
            log.error("Failed reading validation schema")

    def apply_manifests(self, manifests: str) -> None:
        try:
            resources = self._validate_and_load(manifests)
        except (self.ValidationError, yaml.YAMLError) as e:
            log.error(e)
            return

        applied: Set[HashableResource] = set()
        for rsc in resources:
            log.info(f"Applying {rsc}")
            try:
                self.client.apply(rsc.resource, force=True)
                applied.add(rsc)
            except ApiError:
                log.exception(f"Failed applying {rsc}")
        log.info(f"Applied {len(resources)} NetworkAttachmentDefinitions")
        self.resources = applied
        self.scrub_resources()

    def remove_resources(self) -> None:
        try:
            resources = list(self.client.list(self.nad_resource, namespace="*"))
        except ApiError:
            log.error(
                "Failed to get Network Attachment Definitions in cluster. "
                "There may be NADs that couldn't be removed."
            )
            return
        for rsc in resources:
            self.client.delete(
                type(rsc), rsc.metadata.name, namespace=rsc.metadata.namespace
            )
        log.info(f"Removed {len(resources)} NetworkAttachmentDefinitions")

    def scrub_resources(self) -> None:
        try:
            installed = set(
                HashableResource(_)
                for _ in self.client.list(self.nad_resource, namespace="*")
            )
        except ApiError:
            log.error(
                "Failed to get Network Attachment Definitions in cluster. "
                "There may be old NADs that couldn't be removed. "
                "Try again later running the scrub_nads action."
            )
            return
        remnants = installed.difference(self.resources)
        for r in remnants:
            self.client.delete(type(r.resource), r.name, namespace=r.namespace)
        log.info(f"Removed {len(remnants)} NetworkAttachmentDefinitions")

    def _load_and_wrap(self, manifests: str) -> List[HashableResource]:
        return [HashableResource(rsc) for rsc in load_all_yaml(manifests)]

    def _validate_and_load(self, manifests: str) -> List[HashableResource]:
        try:
            self._validate_manifests(manifests)
        except (self.ValidationError, yaml.YAMLError):
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
                raise self.ValidationError(errors)
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
