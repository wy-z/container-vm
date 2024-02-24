import abc
import enum
import ipaddress
import os
import pathlib

import dynaconf
import pydantic

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = "/storage" if os.path.exists("/storage") else ".storage"


#
# Qemu Config
#

TQemuVal = str | int | float  # note: int(True) == 1
TQemuKValOpt = dict[str, TQemuVal]
TQemuKDictOpt = dict[str, dict[str, TQemuVal]]
TQemuConfig = list[dict[str, None | TQemuVal | TQemuKValOpt | TQemuKDictOpt]]


class QemuOpt(abc.ABC):
    type_adapter: pydantic.TypeAdapter

    @abc.abstractmethod
    def to_opts(self) -> list[str]:
        pass

    @classmethod
    def validate(cls, inst) -> bool:
        try:
            cls.type_adapter.validate_python(inst)
            return True
        except pydantic.ValidationError:
            return False


class QemuOptKVal(QemuOpt, TQemuKValOpt):
    type_adapter = pydantic.TypeAdapter(TQemuKValOpt)

    def to_opts(self) -> list[str]:
        return [", ".join(f"{key}={val}" for key, val in self.items())]


class QemuOptKDict(QemuOpt, TQemuKDictOpt):
    type_adapter = pydantic.TypeAdapter(TQemuKDictOpt)

    def to_opts(self) -> list[str]:
        args = []
        for key, d in self.items():
            opts = ",".join(f"{k}={v}" for k, v in d.items())
            args.append(f"{key},{opts}")
        return args


class QemuConfig(TQemuConfig):
    ext_args: list[str] = []

    def to_args(self) -> str:
        args = []
        for opt in self:
            for key, value in opt.items():
                if value is None or (isinstance(value, bool) and value):
                    args.append(f"-{key}")
                elif QemuOptKVal.validate(value):
                    args.extend(f"-{key} {v}" for v in QemuOptKVal(value).to_opts())  # noqa
                elif QemuOptKDict.validate(value):
                    args.extend(f"-{key} {v}" for v in QemuOptKDict(value).to_opts())  # noqa
                else:
                    args.append(f"-{key} {value}")
        return " ".join(args + self.ext_args)


#
# Dynaconf
#


settings = dynaconf.Dynaconf(
    envvar_prefix="",
    settings_files=["settings.yaml"],
    merge_enabled=True,
    environments=False,
    load_dotenv=True,
)

#
# ContainerVm Config
#


class WinOpts(pydantic.BaseModel):
    virtio_iso: pathlib.Path
    enable_tmp: bool = True


class BootMode(enum.StrEnum):
    UEFI = "uefi"
    SECURE = "secure"
    WINDOWS = "windows"
    LEGACY = "legacy"


class Config(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    qemu: QemuConfig = pydantic.Field(default_factory=QemuConfig)

    arch: str = "x86_64"
    cpu_num: int | None = None
    mem_size: int | None = None
    iso: pathlib.Path | None = None
    enable_accel: bool = True
    enable_macvlan: bool = True
    enable_dhcp: bool = True
    enable_vnc_web: bool = True
    enable_console: bool = True
    machine: str | None = None
    boot_mode: BootMode = BootMode.LEGACY
    boot: str | None = None
    ifaces: list[str] = []
    networks: list[ipaddress.IPv4Network] = []
    extra_args: str = ""
    win_opts: WinOpts | None = None
    port_forwards: list[str] = []

    def __init__(self, *args, **kwargs):
        if (qemu_opts := kwargs.get("qemu")) and not isinstance(qemu_opts, QemuConfig):
            kwargs["qemu"] = QemuConfig(qemu_opts)
        super().__init__(*args, **kwargs)

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if not hasattr(self, k):
                continue
            setattr(self, k, v)

    @property
    def is_win(self):
        return self.win_opts is not None


config: Config


def load_config(path: str | None = None):
    if path:
        settings.load_file(path=path)

    global config
    d = settings.as_dict()
    for k in list(d.keys()):
        if k.isupper():  # copy upper case to lower case
            d[k.lower()] = d[k]
    config = Config.model_validate(d)


load_config()


#
# Enums
#


class NetworkMode(enum.StrEnum):
    TAP_BRIDGE = "tapbr"
    MACVLAN = "macvlan"


class VmPort(enum.IntEnum):
    TELNET = 10000
    QMP = 10001
    VNC_WS = 5800
