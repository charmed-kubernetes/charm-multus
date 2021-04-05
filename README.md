# Multus charm

This is a charm for running Multus CNI on Charmed Kubernetes.

This charm is maintained along with the components of Charmed Kubernetes. For
full information, please visit the
[official Charmed Kubernetes docs](https://ubuntu.com/kubernetes/docs/cni-multus).

## Build

Docker is needed to build the images and push it to the charmstore. Suggested:

$ sudo snap install docker --classic

Follow steps on docker documenation to enable it for your current user.

Install dependencies to start running this deployment:

$ make bootstrap

You can build the charm with:

$ make charm

That will build the multus.charm file and all container images will be on docker. 
Push the charm with the images to the charmstore.

$ export NAMESPACE=<namespace-to-be-used-on-charmstore>
$ make upload
