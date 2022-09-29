#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

import logging

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.manifests import Collector
from ops.model import ActiveStatus, WaitingStatus

from manifests import MultusManifests
from net_attach_definitions import NetworkAttachDefinitions

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

    def _scrub_net_attach_defs(self, _):
        self.nad_manager.scrub_resources()

    def _on_config_changed(self, _):
        na_definitions = self.config.get("network-attachment-definitions")
        if na_definitions:
            self.nad_manager.apply_manifests(na_definitions)

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
        if unready:
            self.unit.status = WaitingStatus(", ".join(unready))
        else:
            self.unit.status = ActiveStatus("Ready")
            self.unit.set_workload_version(self.collector.short_version)
            self.app.status = ActiveStatus(self.collector.long_version)

    def _install_or_upgrade(self, event):
        if not self.unit.is_leader():
            return
        log.info("Applying Multus manifests")
        self.manifests.apply_manifests()
        self.stored.deployed = True
        self._update_status(event)

    def _on_remove(self, _):
        log.info("Removing Network Attachment Definitions")
        self.nad_manager.remove_resources()
        log.info("Removing Multus manifests")
        self.manifests.delete_manifests(ignore_unauthorized=True, ignore_not_found=True)


if __name__ == "__main__":
    main(MultusCharm)  # pragma: no cover
