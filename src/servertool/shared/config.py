from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import os
import shlex
from typing import Callable, Sequence

from .. import __version__


LEGACY_ENV_ALIASES = {
    "SERVERTOOL_REMOTE_HOST": ("SERVERIP",),
    "SERVERTOOL_REMOTE_USER": ("SERVERUSERNAME",),
    "SERVERTOOL_REMOTE_PASSWORD": ("SERVERPSD",),
}

USER_CONFIG_KEYS = frozenset(
    {
        "SERVERTOOL_WORKSPACE_NAME",
        "SERVERTOOL_MEMBER_ID",
        "SERVERTOOL_NOTIFY_EMAIL_TO",
        "SERVERTOOL_LOCAL_RUN_CACHE",
    }
)

LAB_CONFIG_KEYS = frozenset(
    {
        "SERVERTOOL_NAME",
        "SERVERTOOL_VERSION",
        "SERVERTOOL_AUTHOR",
        "SERVERTOOL_SHARED_ACCOUNT",
        "SERVERTOOL_SHARED_HOME",
        "SERVERTOOL_A40_PARTITION",
        "SERVERTOOL_A6000_PARTITION",
        "SERVERTOOL_A40_MAX_TIME",
        "SERVERTOOL_A6000_MAX_TIME",
        "SERVERTOOL_INSTALL_PATH",
        "SERVERTOOL_REMOTE_ROOT",
        "SERVERTOOL_REMOTE_HOST",
        "SERVERTOOL_REMOTE_USER",
        "SERVERTOOL_REMOTE_PORT",
        "SERVERTOOL_REMOTE_PYTHON",
        "SERVERTOOL_REMOTE_PASSWORD",
        "SERVERTOOL_SSH_BIN",
        "SERVERTOOL_RSYNC_BIN",
        "SERVERTOOL_RSYNC_BACKEND",
        "SERVERTOOL_NOTIFY_EMAIL_FROM",
        "SERVERTOOL_SMTP_HOST",
        "SERVERTOOL_SMTP_PORT",
        "SERVERTOOL_SMTP_USE_SSL",
        "SERVERTOOL_SMTP_SECRETS_FILE",
        "SERVERTOOL_PIP_INDEX_URL",
        "SERVERTOOL_PIP_EXTRA_INDEX_URL",
        "SERVERTOOL_CONDA_CHANNELS",
        "SERVERTOOL_HF_ENDPOINT",
        "SERVERTOOL_MODELSCOPE_ENDPOINT",
        "SERVERTOOL_SHARED_ENV_ROOT",
        "SERVERTOOL_SHARED_MODEL_ROOT",
        "SERVERTOOL_SHARED_CACHE_ROOT",
    }
)


def _default_config_root() -> Path:
    if os.name == "nt":
        config_root = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
        if config_root:
            return Path(config_root).expanduser() / "servertool"
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))).expanduser() / "servertool"


def _default_cache_root() -> Path:
    if os.name == "nt":
        cache_root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if cache_root:
            return Path(cache_root).expanduser() / "servertool"
    return Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser() / "servertool"


def _default_local_run_cache() -> Path:
    return _default_cache_root() / "runs"


def _default_rsync_backend() -> str:
    return "wsl" if os.name == "nt" else "native"


def _default_user_config_file() -> Path:
    return _default_config_root() / "user.env"


def _default_lab_config_file() -> Path:
    return _default_config_root() / "lab.env"


def _default_smtp_secrets_file() -> Path:
    return _default_config_root() / "smtp.env"


def _default_shared_env_root(remote_root: str) -> str:
    return str(PurePosixPath(remote_root) / "envs")


def _default_shared_model_root(remote_root: str) -> str:
    return str(PurePosixPath(remote_root) / "models")


def _default_shared_cache_root(remote_root: str) -> str:
    return str(PurePosixPath(remote_root) / "cache")


def _default_remote_root(shared_home: Path) -> str:
    return str(PurePosixPath(shared_home.as_posix()) / "trainhub")


def _default_remote_member_root(shared_home: Path, workspace_name: str) -> str:
    return str(PurePosixPath(shared_home.as_posix()) / workspace_name / ".servertool")


def user_config_path() -> Path:
    override = os.getenv("SERVERTOOL_USER_CONFIG_FILE") or os.getenv("SERVERTOOL_CONFIG_FILE")
    return Path(override or str(_default_user_config_file())).expanduser()


def local_config_path() -> Path:
    return user_config_path()


def lab_config_path() -> Path:
    return Path(os.getenv("SERVERTOOL_LAB_CONFIG_FILE", str(_default_lab_config_file()))).expanduser()


def _parse_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        try:
            return str(ast.literal_eval(value))
        except (SyntaxError, ValueError):
            return value[1:-1]
    return value


def load_env_file(path: Path, key_filter: Callable[[str], bool] | None = None) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key_filter is not None and not key_filter(key):
            continue
        values[key] = _parse_env_value(raw_value)
    return values


def load_user_config() -> dict[str, str]:
    return load_env_file(user_config_path(), lambda key: key in USER_CONFIG_KEYS)


def load_local_config() -> dict[str, str]:
    return load_user_config()


def load_lab_config() -> dict[str, str]:
    return load_env_file(lab_config_path(), lambda key: key in LAB_CONFIG_KEYS)


def _config_value(user_values: dict[str, str], lab_values: dict[str, str], key: str, default: str) -> str:
    if key in os.environ:
        return os.environ[key]
    for alias in LEGACY_ENV_ALIASES.get(key, ()):
        alias_value = os.getenv(alias)
        if alias_value is not None:
            return alias_value
    if key in user_values:
        return user_values[key]
    return lab_values.get(key, default)


def _has_config_value(user_values: dict[str, str], lab_values: dict[str, str], key: str) -> bool:
    if key in os.environ:
        return True
    if key in user_values or key in lab_values:
        return True
    return any(alias in os.environ for alias in LEGACY_ENV_ALIASES.get(key, ()))


def _config_int(user_values: dict[str, str], lab_values: dict[str, str], key: str, default: int) -> int:
    raw_value = _config_value(user_values, lab_values, key, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError:
        return default


def _config_bool(user_values: dict[str, str], lab_values: dict[str, str], key: str, default: bool) -> bool:
    raw_value = _config_value(user_values, lab_values, key, "1" if default else "0").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def render_env_file(values: Sequence[tuple[str, str]], comments: Sequence[str] = ()) -> str:
    lines = list(comments)
    if lines:
        lines.append("")
    for key, value in values:
        lines.append(f"export {key}={shlex.quote(value)}")
    return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class Config:
    name: str
    version: str
    author: str
    root: Path
    user_config_file: Path
    lab_config_file: Path
    shared_account: str
    shared_home: Path
    workspace_name: str
    member_id: str
    a40_partition: str
    a6000_partition: str
    a40_max_time: str
    a6000_max_time: str
    install_path: str
    remote_root: str
    remote_member_root: str
    runner_root: Path
    local_run_cache: Path
    notify_email_to: str
    remote_host: str
    remote_user: str
    remote_port: str
    remote_python: str
    remote_password: str
    ssh_bin: str
    rsync_bin: str
    rsync_backend: str
    notify_email_from: str
    smtp_host: str
    smtp_port: int
    smtp_use_ssl: bool
    smtp_secrets_file: Path
    pip_index_url: str
    pip_extra_index_url: str
    conda_channels: str
    hf_endpoint: str
    modelscope_endpoint: str
    shared_env_root: str
    shared_model_root: str
    shared_cache_root: str

    @classmethod
    def from_root(cls, root: Path) -> "Config":
        user_config_file = user_config_path()
        lab_config_file = lab_config_path()
        user_values = load_user_config()
        lab_values = load_lab_config()
        shared_account = _config_value(user_values, lab_values, "SERVERTOOL_SHARED_ACCOUNT", "clusteruser")
        shared_home_default = Path(f"/cluster/home/{shared_account}")
        shared_home_configured = _has_config_value(user_values, lab_values, "SERVERTOOL_SHARED_HOME")
        remote_root_override = _config_value(user_values, lab_values, "SERVERTOOL_REMOTE_ROOT", "")
        inferred_shared_home = shared_home_default
        if not shared_home_configured and remote_root_override.strip():
            inferred_shared_home = Path(PurePosixPath(remote_root_override).parent.as_posix()).expanduser()
        shared_home = Path(
            _config_value(user_values, lab_values, "SERVERTOOL_SHARED_HOME", str(inferred_shared_home))
        ).expanduser()
        workspace_name = _config_value(user_values, lab_values, "SERVERTOOL_WORKSPACE_NAME", "YOUR_NAME")
        member_id = _config_value(user_values, lab_values, "SERVERTOOL_MEMBER_ID", workspace_name)
        remote_root = _config_value(user_values, lab_values, "SERVERTOOL_REMOTE_ROOT", _default_remote_root(shared_home))
        remote_member_root = _config_value(
            user_values,
            lab_values,
            "SERVERTOOL_REMOTE_MEMBER_ROOT",
            _default_remote_member_root(shared_home, workspace_name),
        )
        shared_env_root = _config_value(
            user_values,
            lab_values,
            "SERVERTOOL_SHARED_ENV_ROOT",
            _default_shared_env_root(remote_root),
        )
        shared_model_root = _config_value(
            user_values,
            lab_values,
            "SERVERTOOL_SHARED_MODEL_ROOT",
            _default_shared_model_root(remote_root),
        )
        shared_cache_root = _config_value(
            user_values,
            lab_values,
            "SERVERTOOL_SHARED_CACHE_ROOT",
            _default_shared_cache_root(remote_root),
        )
        return cls(
            name=_config_value(user_values, lab_values, "SERVERTOOL_NAME", "servertool"),
            version=_config_value(user_values, lab_values, "SERVERTOOL_VERSION", __version__),
            author=_config_value(user_values, lab_values, "SERVERTOOL_AUTHOR", "zanewang"),
            root=root,
            user_config_file=user_config_file,
            lab_config_file=lab_config_file,
            shared_account=shared_account,
            shared_home=shared_home,
            workspace_name=workspace_name,
            member_id=member_id,
            a40_partition=_config_value(user_values, lab_values, "SERVERTOOL_A40_PARTITION", "A40"),
            a6000_partition=_config_value(user_values, lab_values, "SERVERTOOL_A6000_PARTITION", "A6000"),
            a40_max_time=_config_value(user_values, lab_values, "SERVERTOOL_A40_MAX_TIME", "15 days"),
            a6000_max_time=_config_value(user_values, lab_values, "SERVERTOOL_A6000_MAX_TIME", "25 days"),
            install_path=_config_value(user_values, lab_values, "SERVERTOOL_INSTALL_PATH", "/usr/local/bin/servertool"),
            remote_root=remote_root,
            remote_member_root=remote_member_root,
            runner_root=Path(
                _config_value(user_values, lab_values, "SERVERTOOL_RUNNER_ROOT", remote_member_root)
            ).expanduser(),
            local_run_cache=Path(
                _config_value(user_values, lab_values, "SERVERTOOL_LOCAL_RUN_CACHE", str(_default_local_run_cache()))
            ).expanduser(),
            notify_email_to=_config_value(user_values, lab_values, "SERVERTOOL_NOTIFY_EMAIL_TO", ""),
            remote_host=_config_value(user_values, lab_values, "SERVERTOOL_REMOTE_HOST", ""),
            remote_user=_config_value(user_values, lab_values, "SERVERTOOL_REMOTE_USER", shared_account),
            remote_port=_config_value(user_values, lab_values, "SERVERTOOL_REMOTE_PORT", "22"),
            remote_python=_config_value(user_values, lab_values, "SERVERTOOL_REMOTE_PYTHON", "python3"),
            remote_password=_config_value(user_values, lab_values, "SERVERTOOL_REMOTE_PASSWORD", ""),
            ssh_bin=_config_value(user_values, lab_values, "SERVERTOOL_SSH_BIN", "ssh"),
            rsync_bin=_config_value(user_values, lab_values, "SERVERTOOL_RSYNC_BIN", "rsync"),
            rsync_backend=_config_value(user_values, lab_values, "SERVERTOOL_RSYNC_BACKEND", _default_rsync_backend()),
            notify_email_from=_config_value(user_values, lab_values, "SERVERTOOL_NOTIFY_EMAIL_FROM", ""),
            smtp_host=_config_value(user_values, lab_values, "SERVERTOOL_SMTP_HOST", "smtp.qq.com"),
            smtp_port=_config_int(user_values, lab_values, "SERVERTOOL_SMTP_PORT", 465),
            smtp_use_ssl=_config_bool(user_values, lab_values, "SERVERTOOL_SMTP_USE_SSL", True),
            smtp_secrets_file=Path(
                _config_value(user_values, lab_values, "SERVERTOOL_SMTP_SECRETS_FILE", str(_default_smtp_secrets_file()))
            ).expanduser(),
            pip_index_url=_config_value(user_values, lab_values, "SERVERTOOL_PIP_INDEX_URL", ""),
            pip_extra_index_url=_config_value(user_values, lab_values, "SERVERTOOL_PIP_EXTRA_INDEX_URL", ""),
            conda_channels=_config_value(user_values, lab_values, "SERVERTOOL_CONDA_CHANNELS", ""),
            hf_endpoint=_config_value(user_values, lab_values, "SERVERTOOL_HF_ENDPOINT", ""),
            modelscope_endpoint=_config_value(user_values, lab_values, "SERVERTOOL_MODELSCOPE_ENDPOINT", ""),
            shared_env_root=shared_env_root,
            shared_model_root=shared_model_root,
            shared_cache_root=shared_cache_root,
        )

    @property
    def user_config_exists(self) -> bool:
        return self.user_config_file.exists()

    @property
    def lab_config_exists(self) -> bool:
        return self.lab_config_file.exists()

    @property
    def workspace_path(self) -> Path:
        return self.shared_home / self.workspace_name

    @property
    def remote_workspace_posix(self) -> PurePosixPath:
        return PurePosixPath(self.shared_home.as_posix()) / self.workspace_name

    @property
    def remote_root_posix(self) -> PurePosixPath:
        return PurePosixPath(self.remote_root)

    @property
    def remote_member_root_posix(self) -> PurePosixPath:
        return PurePosixPath(self.remote_member_root)

    @property
    def remote_runner_install_root(self) -> PurePosixPath:
        return self.remote_root_posix / ".runner"

    @property
    def remote_runner_releases_root(self) -> PurePosixPath:
        return self.remote_runner_install_root / "releases"

    @property
    def remote_runner_current_root(self) -> PurePosixPath:
        return self.remote_runner_install_root / "current"

    def remote_runner_release_root(self, version: str | None = None) -> PurePosixPath:
        release = (version or self.version).strip() or self.version
        return self.remote_runner_releases_root / release

    @property
    def remote_runner_module_root(self) -> PurePosixPath:
        return self.remote_runner_current_root

    @property
    def remote_lab_config_dir(self) -> PurePosixPath:
        return self.remote_root_posix / "lab"

    @property
    def remote_lab_config_file(self) -> PurePosixPath:
        return self.remote_lab_config_dir / "lab.env"

    @property
    def remote_lab_smtp_secrets_file(self) -> PurePosixPath:
        return self.remote_lab_config_dir / "smtp.env"

    @property
    def remote_member_config_file(self) -> PurePosixPath:
        return self.remote_member_root_posix / "config.env"

    @property
    def shared_env_root_posix(self) -> PurePosixPath:
        return PurePosixPath(self.shared_env_root)

    @property
    def shared_model_root_posix(self) -> PurePosixPath:
        return PurePosixPath(self.shared_model_root)

    @property
    def shared_cache_root_posix(self) -> PurePosixPath:
        return PurePosixPath(self.shared_cache_root)

    @property
    def shared_pip_cache_root(self) -> PurePosixPath:
        return self.shared_cache_root_posix / "pip"

    @property
    def shared_conda_cache_root(self) -> PurePosixPath:
        return self.shared_cache_root_posix / "conda"

    @property
    def shared_huggingface_cache_root(self) -> PurePosixPath:
        return self.shared_cache_root_posix / "huggingface"

    @property
    def shared_modelscope_cache_root(self) -> PurePosixPath:
        return self.shared_cache_root_posix / "modelscope"

    @property
    def remote_address(self) -> str:
        if self.remote_user:
            return f"{self.remote_user}@{self.remote_host}"
        return self.remote_host

    @property
    def gpu_partitions(self) -> tuple[str, str]:
        return (self.a40_partition, self.a6000_partition)

    def partition_max_time(self, partition: str) -> str:
        if partition == self.a6000_partition:
            return self.a6000_max_time
        return self.a40_max_time
