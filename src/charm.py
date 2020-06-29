#!/usr/bin/env python3

import json
import logging
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus
from oci_image import OCIImageResource, OCIImageResourceError
import traceback
import yaml

log = logging.getLogger()


class MultusCharm(CharmBase):
    def __init__(self, framework, key):
        super().__init__(framework, key)
        self.multus_image = OCIImageResource(self, 'multus-image')
        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)
        self.framework.observe(self.on.config_changed, self.set_pod_spec)

    def set_pod_spec(self, event):
        if not self.model.unit.is_leader():
            log.info('Not a leader, skipping set_pod_spec')
            self.model.unit.status = ActiveStatus()
            return

        try:
            image_details = self.multus_image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            return

        net_attach_defs_str = self.model.config.get(
            'network-attachment-definitions', '[]'
        )
        try:
            net_attach_defs = yaml.safe_load(net_attach_defs_str)
        except yaml.YAMLError:
            log.error(traceback.format_exc())
            msg = 'network-attachment-definitions config is invalid' + \
                ', see debug-log'
            self.model.unit.status = BlockedStatus(msg)
            return

        pod_spec = {
            'version': 3,
            'containers': [{
                'name': 'kube-multus',
                'imageDetails': image_details,
                'command': ['/entrypoint.sh'],
                'args': [
                    '--multus-conf-file=auto',
                    '--cni-version=0.3.1'
                ],
                'volumeConfig': [
                    {
                        'name': 'cni',
                        'mountPath': '/host/etc/cni/net.d',
                        'hostPath': {
                            'path': '/etc/cni/net.d'
                        }
                    },
                    {
                        'name': 'cnibin',
                        'mountPath': '/host/opt/cni/bin',
                        'hostPath': {
                            'path': '/opt/cni/bin'
                        }
                    }
                ],
                'kubernetes': {
                    'securityContext': {
                        'privileged': True
                    }
                }
            }],
            'serviceAccount': {
                'roles': [{
                    'global': True,
                    'rules': [
                        {
                            'apiGroups': ['k8s.cni.cncf.io'],
                            'resources': ['*'],
                            'verbs': ['*']
                        },
                        {
                            'apiGroups': [''],
                            'resources': [
                                'pods',
                                'pods/status'
                            ],
                            'verbs': [
                                'get',
                                'update'
                            ]
                        }
                    ]
                }]
            },
            'kubernetesResources': {
                'pod': {
                    'hostNetwork': True
                },
                'customResourceDefinitions': [{
                    'name': 'network-attachment-definitions.k8s.cni.cncf.io',
                    'spec': {
                        'group': 'k8s.cni.cncf.io',
                        'scope': 'Namespaced',
                        'names': {
                            'plural': 'network-attachment-definitions',
                            'singular': 'network-attachment-definition',
                            'kind': 'NetworkAttachmentDefinition',
                            'shortNames': ['net-attach-def']
                        },
                        'versions': [{
                            'name': 'v1',
                            'served': True,
                            'storage': True
                        }],
                        'validation': {
                            'openAPIV3Schema': {
                                'type': 'object',
                                'properties': {
                                    'spec': {
                                        'type': 'object',
                                        'properties': {
                                            'config': {
                                                'type': 'string'
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }]
            }
        }

        custom_resources = []
        for net_attach_def in net_attach_defs:
            metadata = {
                'name': net_attach_def['name']
            }
            if 'namespace' in net_attach_def:
                metadata['namespace'] = net_attach_def['namespace']
            if 'resource-name' in net_attach_def:
                metadata['annotations'] = {
                    'k8s.v1.cni.cncf.io/resourceName': net_attach_def['resource-name']
                }
            custom_resource = {
                'apiVersion': 'k8s.cni.cncf.io/v1',
                'kind': 'NetworkAttachmentDefinition',
                'metadata': metadata,
                'spec': {
                    'config': json.dumps(net_attach_def['config'], indent=2)
                }
            }
            custom_resources.append(custom_resource)

        if custom_resources:
            pod_spec['kubernetesResources']['customResources'] = {
                'network-attachment-definitions.k8s.cni.cncf.io': custom_resources
            }

        self.model.unit.status = MaintenanceStatus('Setting pod spec')
        self.model.pod.set_spec(pod_spec)
        self.model.unit.status = ActiveStatus()


if __name__ == '__main__':
    main(MultusCharm)
