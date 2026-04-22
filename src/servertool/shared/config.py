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


def _default_cache_file() -> Path:
    return _default_cache_root() / "disk-cache.json"


def _default_local_run_cache() -> Path:
    return _default_cache_root() / "runs"


def _default_rsync_backend() -> str:
    return "wsl" if os.name == "nt" else "native"


def _default_config_file() -> Path:
    return _default_config_root() / "config.env"


def _default_smtp_secrets_file() -> Path:
    return _default_config_root() / "smtp.env"


def _default_remote_root(shared_home: Path) -> str:
    return str(PurePosixPath(shared_home.as_posix()) / "trainhub")


def local_config_path() -> Path:
    return Path(os.getenv("SERVERTOOL_CONFIG_FILE", str(_default_config_file()))).expanduser()


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


def load_local_config() -> dict[str, str]:
    return load_env_file(local_config_path(), lambda key: key.startswith("SERVERTOOL_"))


def _config_value(local_values: dict[str, str], key: str, default: str) -> str:
    if key in os.environ:
        return os.environ[key]
    for alias in LEGACY_ENV_ALIASES.get(key, ()):
        alias_value = os.getenv(alias)
        if alias_value is not None:
            return alias_value
    return local_values.get(key, default)


def _config_int(local_values: dict[str, str], key: str, default: int) -> int:
    raw_value = _config_value(local_values, key, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError:
        return default


def _config_bool(local_values: dict[str, str], key: str, default: bool) -> bool:
    raw_value = _config_value(local_values, key, "1" if default else "0").strip().lower()
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
    shared_account: str
    shared_home: Path
    workspace_name: str
    auth_url: str
    network_probe_url: str
    a40_partition: str
    a6000_partition: str
    default_compute_host: str
    a40_max_time: str
    a6000_max_time: str
    quota_limit: str
    cache_file: Path
    test_output_dir: Path
    install_path: str
    remote_root: str
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

    @classmethod
    def from_root(cls, root: Path) -> "Config":
        local_values = load_local_config()
        shared_account = _config_value(local_values, "SERVERTOOL_SHARED_ACCOUNT", "clusteruser")
        shared_home = Path(
            _config_value(local_values, "SERVERTOOL_SHARED_HOME", f"/cluster/home/{shared_account}")
        ).expanduser()
        remote_root = _config_value(local_values, "SERVERTOOL_REMOTE_ROOT", _default_remote_root(shared_home))
        return cls(
            name=_config_value(local_values, "SERVERTOOL_NAME", "servertool"),
            version=_config_value(local_values, "SERVERTOOL_VERSION", __version__),
            author=_config_value(local_values, "SERVERTOOL_AUTHOR", "zanewang"),
            root=root,
            shared_account=shared_account,
            shared_home=shared_home,
            workspace_name=_config_value(local_values, "SERVERTOOL_WORKSPACE_NAME", "YOUR_NAME"),
            auth_url=_config_value(local_values, "SERVERTOOL_AUTH_URL", "https://auth.example.com"),
            network_probe_url=_config_value(local_values, "SERVERTOOL_NETWORK_PROBE_URL", "https://example.com"),
            a40_partition=_config_value(local_values, "SERVERTOOL_A40_PARTITION", "A40"),
            a6000_partition=_config_value(local_values, "SERVERTOOL_A6000_PARTITION", "A6000"),
            default_compute_host=_config_value(local_values, "SERVERTOOL_DEFAULT_COMPUTE_HOST", "compute01"),
            a40_max_time=_config_value(local_values, "SERVERTOOL_A40_MAX_TIME", "15 days"),
            a6000_max_time=_config_value(local_values, "SERVERTOOL_A6000_MAX_TIME", "25 days"),
            quota_limit=_config_value(local_values, "SERVERTOOL_QUOTA_LIMIT", "300G"),
            cache_file=Path(_config_value(local_values, "SERVERTOOL_CACHE_FILE", str(_default_cache_file()))).expanduser(),
            test_output_dir=Path(
                _config_value(local_values, "SERVERTOOL_TEST_OUTPUT_DIR", "/tmp/servertool")
            ).expanduser(),
            install_path=_config_value(local_values, "SERVERTOOL_INSTALL_PATH", "/usr/local/bin/servertool"),
            remote_root=remote_root,
            runner_root=Path(_config_value(local_values, "SERVERTOOL_RUNNER_ROOT", remote_root)).expanduser(),
            local_run_cache=Path(
                _config_value(local_values, "SERVERTOOL_LOCAL_RUN_CACHE", str(_default_local_run_cache()))
            ).expanduser(),
            notify_email_to=_config_value(local_values, "SERVERTOOL_NOTIFY_EMAIL_TO", ""),
            remote_host=_config_value(local_values, "SERVERTOOL_REMOTE_HOST", ""),
            remote_user=_config_value(local_values, "SERVERTOOL_REMOTE_USER", shared_account),
            remote_port=_config_value(local_values, "SERVERTOOL_REMOTE_PORT", "22"),
            remote_python=_config_value(local_values, "SERVERTOOL_REMOTE_PYTHON", "python3"),
            remote_password=_config_value(local_values, "SERVERTOOL_REMOTE_PASSWORD", ""),
            ssh_bin=_config_value(local_values, "SERVERTOOL_SSH_BIN", "ssh"),
            rsync_bin=_config_value(local_values, "SERVERTOOL_RSYNC_BIN", "rsync"),
            rsync_backend=_config_value(local_values, "SERVERTOOL_RSYNC_BACKEND", _default_rsync_backend()),
            notify_email_from=_config_value(local_values, "SERVERTOOL_NOTIFY_EMAIL_FROM", ""),
            smtp_host=_config_value(local_values, "SERVERTOOL_SMTP_HOST", "smtp.qq.com"),
            smtp_port=_config_int(local_values, "SERVERTOOL_SMTP_PORT", 465),
            smtp_use_ssl=_config_bool(local_values, "SERVERTOOL_SMTP_USE_SSL", True),
            smtp_secrets_file=Path(
                _config_value(local_values, "SERVERTOOL_SMTP_SECRETS_FILE", str(_default_smtp_secrets_file()))
            ).expanduser(),
        )

    @property
    def workspace_path(self) -> Path:
        return self.shared_home / self.workspace_name

    @property
    def remote_root_posix(self) -> PurePosixPath:
        return PurePosixPath(self.remote_root)

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

    def recommended_request(self) -> list[str]:
        return [
            "srun",
            "-p",
            self.a40_partition,
            "-N",
            "1",
            "-n",
            "8",
            "--mem=32G",
            "--gres=gpu:1",
            "--pty",
            "bash",
            "-i",
        ]
