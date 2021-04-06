# This Dockerfile is used to build the image available on DockerHub
FROM ubuntu:20.04 as build

# Avoid asking for TZ info
ENV DEBIAN_FRONTEND "noninteractive"
RUN ln -fs /usr/share/zoneinfo/UTC /etc/localtime

ENV INSTALL_PKGS "git golang-1.13 python3 python3-yaml"

RUN apt update && \
    apt install -y $INSTALL_PKGS && \
    ln -s /usr/lib/go-1.13/bin/go /usr/bin/go && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    git clone https://github.com/k8snetworkplumbingwg/multus-cni /usr/src/multus-cni && \
    cd /usr/src/multus-cni && \
    ./hack/build-go.sh

# Building with go modules
ENV GO111MODULE "on"
RUN git clone https://github.com/go-delve/delve && \
    cd delve && \
    go build ./cmd/dlv && \
    mv dlv /usr/bin

# Actual container
FROM ubuntu:20.04

ENV INSTALL_PKGS "python3 python3-yaml"

RUN apt update && \
    apt install -y $INSTALL_PKGS && \
    ln -s /usr/bin/python3 /usr/bin/python

COPY --from=build /usr/src/multus-cni /usr/src/multus-cni
COPY --from=build /usr/bin/dlv /usr/bin/dlv
WORKDIR /

RUN cp /usr/src/multus-cni/images/entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
