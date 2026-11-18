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

The historical `release=v4.0` bundle is retained with both images pinned to
v4.0.0 instead of following the mutable `stable` tag. The charm **blocks
reconciliation while `release=v4.0` is selected**, including resource sync/scrub
actions: an existing deployment may already run a newer image resolved from
`stable`, so applying the historical bundle could silently downgrade it. Inspect
the running container/init-container image digests, then explicitly configure a
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
