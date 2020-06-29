# Multus charm

This is an early proof-of-concept charm for running Multus CNI on Charmed
Kubernetes.

## Limitations

This charm requires functionality from Juju 2.8+ which is currently under
active development. In order to run Multus, you will need to install Juju from
edge:

```
sudo snap install juju --channel edge --classic
```

Or if Juju is already installed, refresh it:

```
sudo snap refresh juju --channel edge
```

## Development

Build the charm:

```
charmcraft build
```

Deploy Charmed Kubernetes with Ceph:
```
wget https://raw.githubusercontent.com/charmed-kubernetes/bundle/master/overlays/ceph-rbd.yaml
juju deploy cs:charmed-kubernetes --overlay ceph-rbd.yaml
```

Add k8s to Juju controller:
```
juju scp kubernetes-master/0:config ~/.kube/config
juju add-k8s my-k8s-cloud --controller $(juju switch | cut -d: -f1)
```

Create k8s model:
```
juju add-model my-k8s-model my-k8s-cloud
```

Deploy Multus:
```
juju deploy ./multus.charm --resource multus-image=nfvpe/multus:v3.4
```

Manually apply RBAC rules so the Multus charm can create
NetworkAttachmentDefinitions:
```
$ cat rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: multus-network-attachment-definitions
rules:
- apiGroups: ["k8s.cni.cncf.io"]
  resources: ["network-attachment-definitions"]
  verbs: ["*"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: multus-network-attachment-definitions
subjects:
- kind: ServiceAccount
  namespace: my-k8s-model  # <-- YOUR JUJU MODEL NAME HERE
  name: multus-operator
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: multus-network-attachment-definitions

$ kubectl apply -f rbac.yaml
```
