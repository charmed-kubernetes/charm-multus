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

Clone this repo:
```
git clone https://github.com/charmed-kubernetes/charm-multus.git
cd charm-multus
git submodule init
git submodule update
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

Deploying a local copy of Multus:
```
juju deploy . --resource multus-image=nfvpe/multus:v3.4
```
