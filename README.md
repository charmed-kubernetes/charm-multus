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

## How to test

Clone this repo:
```
git clone https://github.com/charmed-kubernetes/charm-multus.git
cd charm-multus
git submodule init
git submodule update
```

Deploy Charmed Kubernetes with Ceph:

```
juju deploy cs:charmed-kubernetes
juju deploy -n 3 ceph-mon
juju deploy -n 3 ceph-osd --storage osd-devices=32G,2 --storage osd-journals=8G,1
juju add-relation ceph-osd ceph-mon
juju add-relation ceph-mon:admin kubernetes-master
juju add-relation ceph-mon:client kubernetes-master
```

Add k8s to juju controller:
```
juju scp kubernetes-master/0:config ~/.kube/config
juju add-k8s k8s --controller <controller-name>
```

Create k8s model:
```
juju add-model k8s k8s
```

Deploy multus:
```
juju deploy . --resource multus-image=nfvpe/multus:v3.4
```
