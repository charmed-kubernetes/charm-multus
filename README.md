# Multus charm

This is a charm for running Multus CNI on Charmed Kubernetes.

This charm is maintained along with the components of Charmed Kubernetes. For
full information, please visit the
[official Charmed Kubernetes docs](https://ubuntu.com/kubernetes/docs/cni-multus).

## Bundled releases

The default release is Multus v4.3.2. The charm retains the **thin plugin**
deployment: Multus discovers the existing primary CNI configuration and adds
secondary interfaces from `NetworkAttachmentDefinition` resources. It does not
switch an existing installation to the thick daemon/shim architecture.

Upstream [supports Kubernetes versions maintained by the Kubernetes community](https://github.com/k8snetworkplumbingwg/multus-cni/blob/v4.3.2/docs/development.md#which-kubernetes-version-is-supported-in-multus),
which [includes Kubernetes 1.36](https://kubernetes.io/releases/). Bundling older
Multus releases does not imply they have been validated with Kubernetes 1.36.

The historical `release=v4.0` bundle predates the upstream v4.0.0 release: it is
the 3.9-generation thin manifest (`/entrypoint.sh` plus a `cp` init container),
which v4.0.0 and later distroless images cannot run. Its images previously
followed the mutable `stable` tag, which in the Charmed Kubernetes registries
(`ghcr.io/canonical/cdk`, `rocks.canonical.com:443/cdk`) resolves to the same
digest as v3.9.1; both images are now pinned to v3.9.1. Because a custom
`image-registry` may have resolved `stable` to a different image, the charm
**blocks reconciliation while `release=v4.0` is selected**, including resource
sync/scrub actions, rather than replacing whatever is running. Inspect the
running container/init-container image digests, then explicitly configure a
patch release (for example, `juju config multus release=v4.3.2`) appropriate for
the installed version and cluster. Existing workloads and NADs are left untouched
until that choice. New installations should also choose a patch release. The
v3.9.1 bundle is unchanged.

To import a selected release, preserving its upstream thin-plugin manifest and
pinning both container images to the release tag:

```bash
python3 upstream/update.py v3.9.3 v4.0.2 v4.1.4 v4.2.4 v4.3.2
python3 upstream/update.py --check v3.9.3 v4.0.2 v4.1.4 v4.2.4 v4.3.2
```

Update both `charmcraft.yaml` and `upstream/multus/version` when selecting a new
default. Before rolling out a charm upgrade, ensure its images exist in the
configured `image-registry` and validate primary-network connectivity, existing
attachments, and creation/deletion of secondary-network pods during the rolling
DaemonSet update. Never remove the primary CNI configuration or the existing
NetworkAttachmentDefinitions as part of the upgrade.

### Known upgrade issue: stale `00-multus.conf`

The 3.x entrypoint always writes `/etc/cni/net.d/00-multus.conf`. The v4.x thin
entrypoint writes `00-multus.conflist` instead when the primary CNI configuration
uses CNI version 1.0.0 or later (for example Calico v3.32), and it does not remove
an existing `00-multus.conf`. Container runtimes load the alphabetically first
configuration, so the stale `00-multus.conf` stays in use with its old CNI
version and its old copy of the primary configuration. The same applies when the
primary CNI moves to 1.0.0 or later after Multus v4.x is installed and the Multus
pods restart. Upstream provides no startup migration for this (the
`--cleanup-config-on-exit` flag only acts when the new process exits), and the
v4.x images have no shell, so the charm does not clean up node files.

After the DaemonSet has rolled out, check `/etc/cni/net.d` on every node. If both
`00-multus.conf` and `00-multus.conflist` exist, the `.conf` file is the stale
Multus-generated configuration: remove only that file and verify new pods. Never
remove the primary CNI's own configuration files.
