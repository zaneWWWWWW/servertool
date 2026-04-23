from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence
import os

from ..shared.config import Config
from ..shared.system import run_command, shlex_join


def remote_host_configured(config: Config) -> bool:
    return bool(config.remote_host.strip())


def ensure_remote_host(config: Config) -> None:
    if not remote_host_configured(config):
        raise ValueError("SERVERTOOL_REMOTE_HOST is not configured")


def servertool_remote_argv(
    config: Config,
    arguments: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> list[str]:
    command: list[str] = ["env"]
    for key, value in sorted((env or {}).items()):
        command.append(f"{key}={value}")
    command.extend([config.remote_python, "-m", "servertool", *arguments])
    return command


def remote_runner_module_root(config: Config) -> PurePosixPath:
    return config.remote_runner_module_root


def remote_servertool_env(config: Config, extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
    return remote_servertool_env_for_module(config, config.remote_runner_module_root, extra_env=extra_env)


def remote_servertool_env_for_module(
    config: Config,
    module_root: PurePosixPath,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = {
        # Prefer the versioned current release while keeping the legacy direct install as a fallback.
        "PYTHONPATH": ":".join(
            [
                module_root.as_posix(),
                config.remote_runner_install_root.as_posix(),
            ]
        ),
        "SERVERTOOL_LAB_CONFIG_FILE": config.remote_lab_config_file.as_posix(),
        "SERVERTOOL_USER_CONFIG_FILE": config.remote_member_config_file.as_posix(),
        "SERVERTOOL_RUNNER_ROOT": config.remote_member_root,
    }
    if extra_env:
        env.update(extra_env)
    return env


def build_ssh_command(config: Config, remote_argv: Sequence[str]) -> list[str]:
    ensure_remote_host(config)
    return [
        config.ssh_bin,
        "-p",
        config.remote_port,
        config.remote_address,
        shlex_join(remote_argv),
    ]


def run_ssh_command(config: Config, remote_argv: Sequence[str]):
    return run_command(build_ssh_command(config, remote_argv))


def build_rsync_push_command(
    config: Config,
    source: Path,
    destination: PurePosixPath,
    *,
    contents_only: bool = False,
    extra_args: Sequence[str] = (),
) -> list[str]:
    ensure_remote_host(config)
    source_arg = _local_rsync_path(source, config.rsync_backend, contents_only)
    target = f"{config.remote_address}:{destination.as_posix()}"
    return [
        *_rsync_prefix(config),
        "-az",
        *extra_args,
        "-e",
        _rsync_ssh_shell(config),
        source_arg,
        target,
    ]


def build_rsync_pull_command(
    config: Config,
    source: PurePosixPath,
    destination: Path,
    *,
    extra_args: Sequence[str] = (),
) -> list[str]:
    ensure_remote_host(config)
    source_arg = f"{config.remote_address}:{source.as_posix()}"
    destination_arg = _local_rsync_path(destination, config.rsync_backend, contents_only=False)
    return [
        *_rsync_prefix(config),
        "-az",
        *extra_args,
        "-e",
        _rsync_ssh_shell(config),
        source_arg,
        destination_arg,
    ]


def run_rsync_push(
    config: Config,
    source: Path,
    destination: PurePosixPath,
    *,
    contents_only: bool = False,
):
    return run_command(build_rsync_push_command(config, source, destination, contents_only=contents_only))


def run_rsync_pull(config: Config, source: PurePosixPath, destination: Path):
    return run_command(build_rsync_pull_command(config, source, destination))


def build_rsync_version_command(config: Config) -> list[str]:
    return [*_rsync_prefix(config), "--version"]


def _rsync_prefix(config: Config) -> list[str]:
    if config.rsync_backend == "wsl":
        return ["wsl", "-e", config.rsync_bin]
    return [config.rsync_bin]


def _rsync_ssh_shell(config: Config) -> str:
    return f"{config.ssh_bin} -p {config.remote_port}"


def _local_rsync_path(path: Path, backend: str, contents_only: bool) -> str:
    value = _to_wsl_path(path) if backend == "wsl" else str(path)
    if contents_only and path.is_dir() and not value.endswith(("/", "\\")):
        return value + "/"
    return value


def _to_wsl_path(path: Path) -> str:
    raw = str(path.resolve())
    if os.name == "nt" and len(raw) >= 3 and raw[1:3] == ":\\":
        drive = raw[0].lower()
        rest = raw[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return raw.replace("\\", "/")
