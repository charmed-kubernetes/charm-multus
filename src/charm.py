#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

import logging

from lightkube.core.exceptions import ApiError
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.manifests import Collector
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from yaml import YAMLError

from manifests import MultusManifests
from net_attach_definitions import NetworkAttachDefinitions, ValidationError

log = logging.getLogger(__name__)


class MultusCharm(CharmBase):
    """A Juju charm for Multus CNI"""

    stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.manifests = MultusManifests(self, self.config)
        self.collector = Collector(self.manifests)
        self.nad_manager = NetworkAttachDefinitions(self.manifests.client)
        self.stored.set_default(
            nad_manifest="",  # Store previous NAD manifest
            blocked=False,  # Store Blocked Status
            deployed=False,
        )

        self.framework.observe(self.on.install, self._install_or_upgrade)
        self.framework.observe(self.on.upgrade_charm, self._install_or_upgrade)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.remove, self._on_remove)

        self.framework.observe(self.on.list_versions_action, self._list_versions)
        self.framework.observe(self.on.list_resources_action, self._list_resources)
        self.framework.observe(self.on.scrub_resources_action, self._scrub_resources)
        self.framework.observe(
            self.on.scrub_net_attach_defs_action, self._scrub_net_attach_defs
        )
        self.framework.observe(self.on.update_status, self._update_status)

    def _scrub_net_attach_defs(self, event):
        try:
            self.nad_manager.scrub_resources()
            msg = "Successfully scrubbed resources from the cluster."
            event.set_results({"result": msg})
        except ApiError as e:
            event.fail(f"Failed to scrub net-attach-defs from the cluster: {e}")

    def _on_config_changed(self, event):
        current_nads = self.stored.nad_manifest
        na_definitions = self.config.get("network-attachment-definitions")

        if current_nads != na_definitions:
            self.unit.status = WaitingStatus("Applying Network Attachment Definitions.")
            try:
                self.nad_manager.apply_manifests(na_definitions)
                self.stored.nad_manifest = na_definitions
                self.unit.status = ActiveStatus("Ready")
                self.stored.blocked = False
            except (YAMLError, ValidationError):
                self.stored.blocked = True
            except ApiError as e:
                log.error(f"Failed to net-attach-def manifests: {e}")

        self._install_or_upgrade(event)

    def _list_versions(self, event):
        self.collector.list_versions(event)

    def _list_resources(self, event):
        resources = event.params.get("resources", "")
        return self.collector.list_resources(event, resources=resources)

    def _scrub_resources(self, event):
        resources = event.params.get("resources", "")
        return self.collector.scrub_resources(event, resources=resources)

    def _update_status(self, _):
        if not self.stored.deployed:
            return

        unready = self.collector.unready
        blocked = self.stored.blocked

        if blocked:
            self.unit.status = BlockedStatus(
                "Invalid NAD manifests. Check the logs for more information."
            )
        elif unready:
            self.unit.status = WaitingStatus(", ".join(unready))
        else:
            self.unit.set_workload_version(self.collector.short_version)
            self.unit.status = ActiveStatus("Ready")
            self.app.status = ActiveStatus(self.collector.long_version)

    def _install_or_upgrade(self, event):
        if not self.unit.is_leader():
            self.unit.status = ActiveStatus("Ready")
            return
        log.info("Applying Multus manifests")
        self.manifests.apply_manifests()
        self.stored.deployed = True
        self._update_status(event)

    def _on_remove(self, _):
        log.info("Removing Network Attachment Definitions")
        try:
            self.nad_manager.remove_resources()
        except ApiError as e:
            log.error(f"Failed to remove net-attach-defs from the cluster: {e}")
        log.info("Removing Multus manifests")
        self.manifests.delete_manifests(ignore_unauthorized=True, ignore_not_found=True)


if __name__ == "__main__":
    main(MultusCharm)  # pragma: no cover
