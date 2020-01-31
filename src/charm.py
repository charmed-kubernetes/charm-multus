#!/usr/bin/env python3

import sys
sys.path.append('lib')

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus
from oci_image import OCIImageResource


class MultusCharm(CharmBase):
    state = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self.init_state)
        self.multus_image = OCIImageResource(self, 'multus-image')
        self.framework.observe(self.multus_image.on.image_available, self.image_available)

    def init_state(self, event):
        self.state.registry_path = None
        self.state.registry_user = None
        self.state.registry_pass = None

    def image_available(self, event):
        self.state.registry_path = event.registry_path
        self.state.registry_user = event.username
        self.state.registry_pass = event.password
        self.set_pod_spec()

    def set_pod_spec(self):
        self.model.unit.status = MaintenanceStatus('Setting pod spec')
        self.model.pod.set_spec({
            'version': 2,
            'containers': [{
                'name': 'kube-multus',
                'imageDetails': {
                    'imagePath': self.state.registry_path,
                    'username': self.state.registry_user,
                    'password': self.state.registry_pass
                },
                'command': ['/entrypoint.sh'],
                'args': [
                    '--multus-conf-file=auto',
                    '--cni-version=0.3.1'
                ],
                'kubernetes': {
                    'securityContext': {
                        'privileged': True
                    }
                }
            }],
            'serviceAccount': {
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
            },
            'kubernetesResources': {
                'customResourceDefinitions': {
                    'network-attachment-definitions.k8s.cni.cncf.io': {
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
                }
            }
        })


if __name__ == '__main__':
    main(MultusCharm)
