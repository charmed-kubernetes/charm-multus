FROM ubuntu:20.04
ARG TARGETARCH
ENV KUBE_VERSION=v1.18.5
RUN ["apt", "update"]
RUN ["apt", "install", "-y", "python3-minimal", "python3-yaml"]
ADD https://storage.googleapis.com/kubernetes-release/release/${KUBE_VERSION}/bin/linux/${TARGETARCH}/kubectl /usr/bin/kubectl
RUN ["chmod", "+x", "/usr/bin/kubectl"]
COPY net-attach-def-manager.py /net-attach-def-manager.py
ENTRYPOINT ["/net-attach-def-manager.py"]
