# Multus charm

This is an early proof-of-concept charm for running Multus CNI on Charmed
Kubernetes.

## Limitations

In Juju 2.7.1, it's not possible for k8s charms to create DaemonSets or to
create hostPath Volumes. As a result, this PoC has the following limitations:

* Only works with 1 kubernetes-worker
* Requires manual creation of PersistentVolume storage

## How to test

Deploy kubernetes-core with Ceph:

```
juju deploy cs:kubernetes-core
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

Create k8s PeristentVolume:
```
cat > storage.yaml << EOF
kind: PersistentVolume
apiVersion: v1
metadata:
  name: cni-conf-0
spec:
  capacity:
    storage: 100Mi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: k8s-multus-cni-conf
  hostPath:
    path: "/etc/cni/net.d"
---
kind: PersistentVolume
apiVersion: v1
metadata:
  name: cni-bin-0
spec:
  capacity:
    storage: 100Mi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: k8s-multus-cni-bin
  hostPath:
    path: "/opt/cni/bin"
EOF
kubectl apply -f storage.yaml
```

Create storage pool:
```
for suffix in conf bin; do
  juju create-storage-pool multus-cni-$suffix kubernetes \
    storage-class=multus-cni-$suffix \
    storage-provisioner=kubernetes.io/no-provisioner
done
```

Deploy multus:
```
juju deploy . --resource multus-image=nfvpe/multus:v3.4 \
  --storage cni-conf=multus-cni-conf,10M \
  --storage cni-bin=multus-cni-bin,10M
```
