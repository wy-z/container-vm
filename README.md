# container-vm

[![Pulls]][hub_url]
[![image](https://raw.githubusercontent.com/wy-z/container-vm/main/tests/coverage.svg)](https://github.com/wy-z/container-vm)

Run qemu/kvm VM inside a docker container

## Quick Start

### Linux

```sh
mkdir tmp && cp tmp
wget https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-virt-3.19.1-x86_64.iso
docker run --name container-vm --rm -v $PWD:/storage --cap-add=NET_ADMIN \
    --device=/dev/kvm -p 8080:8080 weiyang/container-vm run --iso /storage/alpine-virt-3.19.1-x86_64.iso
```

### MacOS

```sh
mkdir tmp && cp tmp
wget https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-virt-3.19.1-x86_64.iso
docker run --name container-vm --rm -v $PWD:/storage --cap-add=NET_ADMIN --device-cgroup-rule='c *:* rwm' \
    -p 8080:8080 weiyang/container-vm run --macvlan --iso /storage/alpine-virt-3.19.1-x86_64.iso
```

Then you can:

- Open `http://localhost:8080` to visit VM graphic
- `docker exec -it container-vm telnet 127.0.0.1 10000` to visit VM console
  - `Ctrl-A-C` -> Qemu monitor console
  - `Ctrl-]` + `quit` to exit telnet

## Features

- Simplicity: Utilizes a clean, straightforward QEMU setup for hassle-free virtualization, focusing on ease of use.
- Flexibility: Offers full compatibility and extensibility with customizable configurations, catering to diverse needs and ensuring easy adaptability for future expansions.
- Native Performance: Delivers exceptional efficiency and optimal performance through the use of advanced technologies such as Tap, MacVlan, and KVM acceleration.

## Windows VM

1.  Download windows iso (`Win11_23H2_x64v2.iso` or [tiny11](https://archive.org/details/tiny11-2311))
2.  Download VirtIO from `https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio` (`virtio-win.iso`)

        If the hard drive is not detected, remember to install the drivers from the VirtIO ISO

3.  Start container

    Linux

    ```sh
    docker run --rm -v $PWD:/storage --cap-add=NET_ADMIN --device /dev/kvm \
        -p 8080:8080 weiyang/container-vm run -c 4 -m 8192 \
        --iso /storage/Win11_23H2_x64v2.iso windows --virtio-iso /storage/virtio-win.iso \
        apply-disk -s 64G -n hda ext-args -- -cpu host
    ```

    MacOS

    ```sh
    docker run --rm -v $PWD:/storage --cap-add=NET_ADMIN --device-cgroup-rule='c *:* rwm' \
        -p 8080:8080 weiyang/container-vm run --macvlan -c 4 -m 8192 \
        --iso /storage/Win11_23H2_x64v2.iso windows --virtio-iso /storage/virtio-win.iso \
        apply-disk -s 64G -n hda
    ```

         On MacOS, rm `--device=/dev/kvm` and `ext-args -- -cpu host`

    1. `--cap-add=NET_ADMIN` is necessary for network configuration
    2. `--device-cgroup-rule='c *:* rwm'` is necessary for macvlan, or disable by `--no-macvlan`
    3. `-c 4 -m 8192` 4 cpu cores, 8G memory
    4. `--iso /storage/Win11_23H2_x64v2.iso` add boot cdrom
    5. `windows --virtio-iso /storage/virtio-win.iso` add virtio iso
    6. `apply-disk -s 64G -n hda` create a 64G disk if not exists
    7. `ext-args -- -cpu host` host-passthrough cpu mode, all flags after `ext-args --` will be passed to qemu
    8. VirtIO iso is recommended for best performance

#### OpenGL Support

Install Mesa3D driver https://github.com/pal1000/mesa-dist-win/releases

#### Better Graphical Performance

1.  Run docker with `--device=/dev/dri`

        If `/dev/dri` not exists, try create by:
        ```
        mkdir -m 755 /dev/dri
        mknod -m 666 /dev/dri/card0 c 226 0
        mknod -m 666 /dev/dri/renderD128 c 226 128
        ```

2.  `weiyang/container run *** --vga no ext-args -- -display egl-headless -device virtio-vga-gl`

## Container capability limits

1. Minimum capability requirement is `--cap-add=NET_ADMIN`, run with `--no-accel`
2. `--device-cgroup-rule='c *:* rwm'`/`--macvlan` will enable macvlan, otherwise use tap bridge
3. `--device=/dev/kvm`/`--no-accel` will disable IO acceleration, not recommended

## Podman Support

         The testing for Podman is not yet complete; you may submit an Issue if needed.

    - May need to add more capabilities, such as `--cap-add NET_RAW`
    - May need to add more devices, such as `--device=/dev/net/tun`

## CLI Commands

### Run

    Commands are chainable, e.g. `run xxx windows xxx apply-disk xxx port-forward xxx ext-args -- xxx xxx`

```
❯ python main.py run --help

 Usage: main.py run [OPTIONS] COMMAND1 [ARGS]... [COMMAND2 [ARGS]...]...

╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --cpu        -c                  INTEGER                                                                    CPU cores [default: None]                                                   │
│ --mem        -m                  INTEGER RANGE [x>=1]                                                       Memory size in MB [default: None]                                           │
│ --arch                           [alpha|sparc|nios2|sh4|xtensa|avr|sparc64|riscv32|m68k|tricore|microblaze  VM arch [default: x86_64]                                                   │
│                                  |cris|mipsel|sh4eb|aarch64|loongarch64|ppc|hppa|mips64el|or1k|i386|mips64                                                                              │
│                                  |rx|microblazeel|riscv64|xtensaeb|mips|x86_64|s390x|arm|ppc64]                                                                                         │
│ --iso                            TEXT                                                                       ISO file path or drive url [default: None]                                  │
│ --accel          --no-accel                                                                                 Enable acceleration [default: accel]                                        │
│ --macvlan        --no-macvlan                                                                               Enable macvlan network, otherwise use bridge network [default: no-macvlan]  │
│ --netdev         --no-netdev                                                                                Setup netdev or not [default: netdev]                                       │
│ --dhcp           --no-dhcp                                                                                  Enable DHCP [default: dhcp]                                                 │
│ --vnc-web        --no-vnc-web                                                                               Enable VNC web client (noVNC) [default: vnc-web]                            │
│ --console        --no-console                                                                               Enable Qemu monitor (mon+telnet+qmp) [default: console]                     │
│ --machine                        TEXT                                                                       Machine type [default: None]                                                │
│ --boot                           STR_OR_NONE                                                                Boot options (no|false|none|nil|null == disable) [default: once=dc]         │
│ --vga                            STR_OR_NONE                                                                Setup VGA (virtio) [default: virtio]                                        │
│ --boot-mode                      [uefi|secure|windows|legacy]                                               Boot mode [default: legacy]                                                 │
│ --iface                          TEXT                                                                       (multiple) Special VM network interface (e.g. eth1)                         │
│ --network                        TEXT                                                                       (multiple) Special VM network CIDR (IPv4) (e.g. 192.168.1.0/24)             │
│ --dry            --no-dry                                                                                   Dry run [default: no-dry]                                                   │
│ --help                                                                                                      Show this message and exit.                                                 │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ apply-disk                                   Apply VM disk                                                                                                                              │
│ exec-sh                                      Exec shell script files before start Qemu                                                                                                  │
│ ext-args                                     External Qemu args                                                                                                                         │
│ port-forward                                 Forward VM ports                                                                                                                           │
│ windows                                      Windows specific options                                                                                                                   │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### Apply Disk

    `run xxx apply-disk -s 64G -n hda apply-disk -s 32G -n hdb`

```
❯ python main.py run apply-disk --help

 Usage: main.py run apply-disk [OPTIONS]

 Apply VM disk

╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --name       -n      TEXT  Disk name (e.g. disk1) [default: None] [required]                                                                                                         │
│    --size       -s      TEXT  Disk size (e.g. 32G) [default: 16G]                                                                                                                       │
│    --file-type          TEXT  Drive file type (e.g. qcow2,raw) [default: qcow2]                                                                                                         │
│    --if-type            TEXT  Drive interface type (e.g. virtio,ide) [default: None]                                                                                                    │
│    --opts               TEXT  External drive options (e.g. index=i,format=f) [default: None]                                                                                            │
│    --help                     Show this message and exit.                                                                                                                               │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### Windows

    `run xxx windows --virtio-iso /storage/virtio-iso.iso`

```
❯ python main.py run windows --help

 Usage: main.py run windows [OPTIONS]

 Windows specific options

╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --virtio-iso                PATH  Window virtio driver iso, download from https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio [default: None]                │
│ --tpm           --no-tpm          Enable TPM [default: tpm]                                                                                                                             │
│ --help                            Show this message and exit.                                                                                                                           │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### Port Forwarding

    `run xxx port-forward -p 22:22 -p 3389:3389`
    Ports 22 and 3389 are set to forward automatically by default

```
❯ python main.py run port-forward --help

 Usage: main.py run port-forward [OPTIONS]

 Forward VM ports

╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --port  -p      TEXT  (multiple) Port forward spec (e.g. 80:8088) [default: None]                                                                                                       │
│ --help                Show this message and exit.                                                                                                                                       │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### External Arguments

    `run xxx ext-args -- -cpu host -netdev xxx`

```
❯ python main.py run ext-args --help

 Usage: main.py run ext-args [OPTIONS] ARGS...

 External Qemu args

╭─ Arguments ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    args      ARGS...  External Qemu args [default: None] [required]                                                                                                                   │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                                                                                             │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### Execute shell script

    `run xxx exec-sh -f xxx.sh`

```
❯ python main.py run exec-sh --help

 Usage: main.py run exec-sh [OPTIONS]

 Exec shell script files before start Qemu

╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --file  -f      PATH  (multiple) shell script file [default: None]                                                                                                                      │
│ --help                Show this message and exit.                                                                                                                                       │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## Similar Projects

- https://github.com/BBVA/kvm
- https://github.com/qemus/qemu-docker

## License

MIT

[hub_url]: https://hub.docker.com/r/weiyang/container-vm/
[Pulls]: https://img.shields.io/docker/pulls/weiyang/container-vm.svg?style=flat&label=pulls&logo=docker
