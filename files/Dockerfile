ARG CVM_DIR=/container-vm

FROM container-vm-dev as build

ARG CVM_DIR

ADD . ${CVM_DIR}
RUN cd ${CVM_DIR} \
    && just build


FROM container-vm-base

ARG CVM_DIR

COPY --from=build ${CVM_DIR}/dist/container-vm /app

VOLUME /storage
EXPOSE 8080 22 3389

ENTRYPOINT ["/app/container-vm"]
