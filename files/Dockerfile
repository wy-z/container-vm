FROM container-vm-base

ENV NOVNC_DIR /opt/noVNC
ENV NOVNC_VERSION 1.4.0

RUN apt update \
    && apt --no-install-recommends -y install python3 \
    && apt clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY ./Caddyfile /etc/caddy/Caddyfile

VOLUME /storage
EXPOSE 22 23 8080

ENTRYPOINT ["/run/entry.sh"]
