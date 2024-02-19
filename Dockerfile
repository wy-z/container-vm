FROM debian:stable-slim

ENV NOVNC_DIR /opt/noVNC
ENV NOVNC_VERSION 1.4.0

RUN apt update \
    && apt --no-install-recommends -y install \
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
    # vga
    xserver-xorg-video-intel \
    qemu-system-modules-opengl \
    && apt clean \
    && mkdir -p $NOVNC_DIR \
    && wget https://github.com/novnc/noVNC/archive/refs/tags/v"$NOVNC_VERSION".tar.gz -O /tmp/novnc.tar.gz -q \
    && tar -xf /tmp/novnc.tar.gz -C /tmp/ \
    && cd /tmp/noVNC-"$NOVNC_VERSION" \
    && mv app core vendor package.json *.html $NOVNC_DIR \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY ./src /run/
COPY ./web /var/www/

RUN chmod +x /run/*.sh

VOLUME /storage
EXPOSE 22 23 80

ENV CPU_CORES "1"
ENV RAM_SIZE "1G"
ENV DISK_SIZE "16G"
ENV BOOT "http://example.com/image.iso"

ARG VERSION_ARG "0.0"
RUN echo "$VERSION_ARG" > /run/version

ENTRYPOINT ["/run/entry.sh"]
