#!/usr/bin/env python3

import logging
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus
import traceback
import yaml

log = logging.getLogger()


class MultusCharm(CharmBase):
    def __init__(self, framework, key):
        super().__init__(framework, key)
        self.multus_image = OCIImageResource(self, "multus-image")
        self.nadm_image = OCIImageResource(self, "net-attach-def-manager-image")
        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)
        self.framework.observe(self.on.config_changed, self.set_pod_spec)

    def set_pod_spec(self, event):
        if not self.model.unit.is_leader():
            log.info("Not a leader, skipping set_pod_spec")
            self.model.unit.status = ActiveStatus()
            return

        try:
            multus_image_details = self.multus_image.fetch()
            nadm_image_details = self.nadm_image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            return

        net_attach_defs_str = self.model.config.get("network-attachment-definitions", "")
        invalid_net_attach_def_status = BlockedStatus(
            "network-attachment-definitions config is invalid, see debug-log"
        )
        try:
            net_attach_defs = list(yaml.safe_load_all(net_attach_defs_str))
        except yaml.YAMLError:
            log.error(traceback.format_exc())
            self.model.unit.status = invalid_net_attach_def_status
            return

        for net_attach_def in net_attach_defs:
            if net_attach_def.get("apiVersion") != "k8s.cni.cncf.io/v1":
                log.error(
                    "network-attachment-definitions config is invalid:"
                    + " apiVersion must be k8s.cni.cncf.io/v1"
                )
                self.model.unit.status = invalid_net_attach_def_status
                return
            if net_attach_def.get("kind") != "NetworkAttachmentDefinition":
                log.error(
                    "network-attachment-definitions config is invalid:"
                    + " kind must be NetworkAttachmentDefinition"
                )
                self.model.unit.status = invalid_net_attach_def_status
                return
            if not net_attach_def.get("metadata", {}).get("name"):
                log.error(
                    "network-attachment-definitions config is invalid:"
                    + " metadata.name is required"
                )
                self.model.unit.status = invalid_net_attach_def_status
                return
            if not net_attach_def.get("spec", {}).get("config"):
                log.error(
                    "network-attachment-definitions config is invalid:"
                    + " spec.config is required"
                )
                self.model.unit.status = invalid_net_attach_def_status
                return

        for net_attach_def in net_attach_defs:
            net_attach_def["metadata"].setdefault("namespace", self.model.name)

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        pod_spec = {
            "version": 3,
            "containers": [
                {
                    "name": "kube-multus",
                    "imageDetails": multus_image_details,
                    "command": ["/entrypoint.sh"],
                    "args": ["--multus-conf-file=auto", "--cni-version=0.3.1"],
                    "volumeConfig": [
                        {
                            "name": "cni",
                            "mountPath": "/host/etc/cni/net.d",
                            "hostPath": {"path": "/etc/cni/net.d"},
                        },
                        {
                            "name": "cnibin",
                            "mountPath": "/host/opt/cni/bin",
                            "hostPath": {"path": "/opt/cni/bin"},
                        },
                    ],
                    "kubernetes": {"securityContext": {"privileged": True}},
                },
                {
                    "name": "net-attach-def-manager",
                    "imageDetails": nadm_image_details,
                    "volumeConfig": [
                        {
                            "name": "config",
                            "mountPath": "/config",
                            "files": [
                                {
                                    "path": "manifest.yaml",
                                    "content": yaml.safe_dump_all(net_attach_defs) or "# empty",
                                }
                            ],
                        }
                    ],
                },
            ],
            "serviceAccount": {
                "roles": [
                    {
                        "global": True,
                        "rules": [
                            {"apiGroups": ["k8s.cni.cncf.io"], "resources": ["*"], "verbs": ["*"]},
                            {
                                "apiGroups": [""],
                                "resources": ["pods", "pods/status"],
                                "verbs": ["get", "update"],
                            },
                        ],
                    }
                ]
            },
            "kubernetesResources": {
                "pod": {"hostNetwork": True},
                "customResourceDefinitions": [
                    {
                        "name": "network-attachment-definitions.k8s.cni.cncf.io",
                        "spec": {
                            "group": "k8s.cni.cncf.io",
                            "scope": "Namespaced",
                            "names": {
                                "plural": "network-attachment-definitions",
                                "singular": "network-attachment-definition",
                                "kind": "NetworkAttachmentDefinition",
                                "shortNames": ["net-attach-def"],
                            },
                            "versions": [
                                {
                                    "name": "v1",
                                    "served": True,
                                    "storage": True,
                                    "schema": {
                                        "openAPIV3Schema": {
                                            "type": "object",
                                            "properties": {
                                                "apiVersion": {"type": "string"},
                                                "kind": {"type": "string"},
                                                "metadata": {"type": "object"},
                                                "spec": {
                                                    "type": "object",
                                                    "properties": {"config": {"type": "string"}},
                                                },
                                            },
                                        }
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        }
        self.model.pod.set_spec(pod_spec)
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(MultusCharm)
