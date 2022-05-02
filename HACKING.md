# Development

Build the charm:

```
make charm
```

Deploy Charmed Kubernetes with Ceph:
```
wget https://raw.githubusercontent.com/charmed-kubernetes/bundle/main/overlays/ceph-rbd.yaml
juju deploy charmed-kubernetes --overlay ceph-rbd.yaml
```

Add k8s to Juju controller:
```
juju scp kubernetes-control-plane/0:config ~/.kube/config
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
