FROM debian:stable-slim

ENV NOVNC_DIR /opt/noVNC
ENV NOVNC_VERSION 1.4.0

RUN apt update \
    && apt --no-install-recommends -y install \
    tini \
    qemu-system \
    wget \
    swtpm \
    iptables \
    iproute2 \
    dnsmasq \
    net-tools \
    bridge-utils \
    netcat-openbsd \
    inetutils-ping \
    caddy \
    telnet \
    && apt clean \
    && mkdir -p $NOVNC_DIR \
    && wget https://github.com/novnc/noVNC/archive/refs/tags/v"$NOVNC_VERSION".tar.gz -O /tmp/novnc.tar.gz -q \
    && tar -xf /tmp/novnc.tar.gz -C /tmp/ \
    && cd /tmp/noVNC-"$NOVNC_VERSION" \
    && mv app core vendor package.json *.html $NOVNC_DIR \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY ./Caddyfile /etc/caddy/Caddyfile

VOLUME /storage
EXPOSE 22 23 8080

ENTRYPOINT ["/run/entry.sh"]
