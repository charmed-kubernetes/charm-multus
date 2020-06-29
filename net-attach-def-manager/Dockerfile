FROM ubuntu:20.04
RUN ["apt", "update"]
RUN ["apt", "install", "-y", "python3-minimal", "python3-yaml"]
COPY build.tmp/kubectl /usr/bin/kubectl
COPY net-attach-def-manager.py /net-attach-def-manager.py
ENTRYPOINT ["/net-attach-def-manager.py"]
