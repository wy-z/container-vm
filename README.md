# docker-vm

Run qemu/kvm vm's inside a docker container

## QuickStart

```sh
docker pull weiyang/container-vm
wget https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-virt-3.19.1-x86_64.iso
docker run --rm -it -v $PWD:$PWD -w $PWD --cap-add=NET_ADMIN --device-cgroup-rule='c *:* rwm' --device /dev/kvm -p 8080:8080 weiyang/container-vm run --iso src/alpine-virt-3.19.0-x86_64.iso
# open http://localhost:8080
```
