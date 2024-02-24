FROM python:3-slim-bookworm

RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources \
    && apt update \
    && apt --no-install-recommends -y install \
    tini \
    qemu-system \
    wget \
    swtpm \
    iptables \
    iproute2 \
    apt-utils \
    dnsmasq \
    net-tools \
    netcat-openbsd \
    bridge-utils \
    caddy \
    tcpdump \
    inetutils-ping \
    && apt clean \
    && pip install 'typer[all]' pydantic dynaconf ring tenacity -i https://pypi.tuna.tsinghua.edu.cn/simple

