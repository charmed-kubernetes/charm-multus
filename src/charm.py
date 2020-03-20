#!/usr/bin/env python3

import sys
sys.path.append('lib')

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus
from oci_image import OCIImageResource, ResourceError


class MultusCharm(CharmBase):
    def __init__(self, framework, key):
        super().__init__(framework, key)
        self.multus_image = OCIImageResource(self, 'multus-image')
        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)

    def set_pod_spec(self, event):
        if not self.model.unit.is_leader():
            print('Not a leader, skipping set_pod_spec')
            self.model.unit.status = ActiveStatus()
            return

        try:
            image_details = self.multus_image.fetch()
        except ResourceError as e:
            self.model.unit.status = e.status
            return

        self.model.unit.status = MaintenanceStatus('Setting pod spec')
        self.model.pod.set_spec({
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
        })

        self.model.unit.status = ActiveStatus()


if __name__ == '__main__':
    main(MultusCharm)
