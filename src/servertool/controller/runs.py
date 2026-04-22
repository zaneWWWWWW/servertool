from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
import json
import time
from typing import Callable

from ..shared.config import Config
from ..shared.layout import RunLayout, build_run_id, build_run_layout, slugify
from ..shared.spec import RunSpec, load_spec, write_spec
from . import transport as remote_ops
from .transport import (
    build_rsync_pull_command,
    build_rsync_push_command,
    build_ssh_command,
    remote_servertool_env,
    servertool_remote_argv,
)


FOLLOW_POLL_SECONDS = 2.0
TERMINAL_RUN_STATES = {"succeeded", "failed", "stopped"}


@dataclass(frozen=True)
class SubmitPlan:
    run_id: str
    spec_path: Path
    layout: RunLayout
    remote_spec: RunSpec
    commands: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class FetchPlan:
    run_id: str
    remote_run_root: PurePosixPath
    destination_base: Path
    local_run_root: Path
    command: tuple[str, ...]


def ensure_remote_host(config: Config) -> None:
    remote_ops.ensure_remote_host(config)


def _resolve_local_asset_path(spec_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (spec_path.parent / candidate).resolve()


def _remote_code_path(layout: RunLayout, run_id: str) -> PurePosixPath:
    return layout.code_root / run_id


def _dataset_remote_path(layout: RunLayout, dataset_source: Path | None) -> str:
    if dataset_source is None:
        return ""
    name = dataset_source.stem if dataset_source.is_file() else dataset_source.name
    return (layout.datasets_root / slugify(name)).as_posix()


def _remote_workdir(code_root: PurePosixPath, workdir: str) -> str:
    if not workdir or workdir == ".":
        return code_root.as_posix()
    candidate = PurePosixPath(workdir)
    if candidate.is_absolute():
        return candidate.as_posix()
    return (code_root / candidate).as_posix()


def _build_remote_spec(spec_path: Path, spec: RunSpec, layout: RunLayout) -> tuple[RunSpec, Path, Path | None]:
    code_destination = _remote_code_path(layout, layout.run_id)
    code_source = _resolve_local_asset_path(spec_path, spec.assets.code)
    if not code_source.exists():
        raise FileNotFoundError(f"Code asset path does not exist: {code_source}")

    dataset_source = None
    if spec.assets.dataset:
        candidate = _resolve_local_asset_path(spec_path, spec.assets.dataset)
        if candidate.exists():
            dataset_source = candidate

    remote_assets = replace(
        spec.assets,
        code=code_destination.as_posix(),
        dataset=_dataset_remote_path(layout, dataset_source) or spec.assets.dataset,
    )
    remote_launch = replace(spec.launch, workdir=_remote_workdir(code_destination, spec.launch.workdir))
    remote_spec = replace(spec, assets=remote_assets, launch=remote_launch)
    return remote_spec, code_source, dataset_source


def prepare_submit(
    config: Config,
    spec_path: Path,
    explicit_run_id: str | None,
    staging_dir: Path,
) -> SubmitPlan:
    spec = load_spec(spec_path)
    run_id = explicit_run_id or build_run_id(spec.run_name)
    layout = build_run_layout(config.remote_root_posix, spec.project, run_id)
    remote_spec, code_source, dataset_source = _build_remote_spec(spec_path, spec, layout)

    incoming_dir = config.remote_root_posix / ".incoming" / run_id
    incoming_spec = incoming_dir / "spec.json"
    code_destination = PurePosixPath(remote_spec.assets.code)
    commands: list[tuple[str, tuple[str, ...]]] = []

    mkdir_args = ["mkdir", "-p", incoming_dir.as_posix(), code_destination.as_posix()]
    if dataset_source is not None:
        mkdir_args.append(PurePosixPath(remote_spec.assets.dataset).as_posix())
    commands.append(("Prepare remote directories", tuple(build_ssh_command(config, mkdir_args))))
    commands.append(
        (
            "Sync code asset",
            tuple(
                build_rsync_push_command(
                    config,
                    code_source,
                    code_destination,
                    contents_only=code_source.is_dir(),
                )
            ),
        )
    )
    if dataset_source is not None:
        commands.append(
            (
                "Sync dataset asset",
                tuple(
                    build_rsync_push_command(
                        config,
                        dataset_source,
                        PurePosixPath(remote_spec.assets.dataset),
                        contents_only=dataset_source.is_dir(),
                    )
                ),
            )
        )

    temp_spec_path = staging_dir / "spec.json"
    write_spec(temp_spec_path, remote_spec)
    commands.append(
        (
            "Upload remote spec",
            tuple(build_rsync_push_command(config, temp_spec_path, incoming_spec, contents_only=False)),
        )
    )
    commands.append(
        (
            "Prepare remote run",
            tuple(
                build_ssh_command(
                    config,
                    servertool_remote_argv(
                        config,
                        ["runner", "prepare", incoming_spec.as_posix(), "--run-id", run_id],
                        env=remote_servertool_env(
                            config,
                            {"SERVERTOOL_RUNNER_ROOT": config.remote_root},
                        ),
                    ),
                )
            ),
        )
    )
    commands.append(
        (
            "Start remote job",
            tuple(
                build_ssh_command(
                    config,
                    servertool_remote_argv(
                        config,
                        ["runner", "start", run_id],
                        env=remote_servertool_env(
                            config,
                            {"SERVERTOOL_RUNNER_ROOT": config.remote_root},
                        ),
                    ),
                )
            ),
        )
    )
    return SubmitPlan(
        run_id=run_id,
        spec_path=spec_path,
        layout=layout,
        remote_spec=remote_spec,
        commands=tuple(commands),
    )


def load_remote_status(config: Config, run_id: str) -> dict[str, object]:
    result = remote_ops.run_ssh_command(
        config,
        servertool_remote_argv(
            config,
            ["runner", "status", run_id],
            env=remote_servertool_env(
                config,
                {"SERVERTOOL_RUNNER_ROOT": config.remote_root},
            ),
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "remote status failed")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Remote status did not return a JSON object")
    return payload


def load_remote_log_text(config: Config, target: str, lines: int, use_stderr: bool) -> str:
    remote_args = ["runner", "tail", target, "--lines", str(max(lines, 1))]
    if use_stderr:
        remote_args.append("--stderr")
    result = remote_ops.run_ssh_command(
        config,
        servertool_remote_argv(
            config,
            remote_args,
            env=remote_servertool_env(
                config,
                {"SERVERTOOL_RUNNER_ROOT": config.remote_root},
            ),
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "remote log read failed")
    return result.stdout.rstrip()


def follow_remote_logs(
    config: Config,
    target: str,
    lines: int,
    use_stderr: bool,
    emit: Callable[[str], None],
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    previous_lines: list[str] = []
    first_pass = True
    try:
        while True:
            try:
                output = load_remote_log_text(config, target, lines, use_stderr)
            except RuntimeError as error:
                if "Log file not found:" in str(error):
                    sleeper(FOLLOW_POLL_SECONDS)
                    continue
                raise

            current_lines = output.splitlines()
            new_lines = current_lines if first_pass else _new_tail_lines(previous_lines, current_lines)
            if new_lines:
                emit("\n".join(new_lines))
            previous_lines = current_lines
            first_pass = False

            try:
                status = load_remote_status(config, target)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
                status = {}
            if str(status.get("state", "")) in TERMINAL_RUN_STATES:
                return 0

            sleeper(FOLLOW_POLL_SECONDS)
    except KeyboardInterrupt:
        return 0


def _new_tail_lines(previous_lines: list[str], current_lines: list[str]) -> list[str]:
    if not previous_lines:
        return current_lines
    max_overlap = min(len(previous_lines), len(current_lines))
    for overlap in range(max_overlap, 0, -1):
        if previous_lines[-overlap:] == current_lines[:overlap]:
            return current_lines[overlap:]
    return current_lines


def build_fetch_plan(config: Config, target: str, destination_base: Path | None = None) -> FetchPlan:
    status = load_remote_status(config, target)
    paths = status.get("paths")
    if not isinstance(paths, dict) or not isinstance(paths.get("run_root"), str):
        raise ValueError("Remote status is missing paths.run_root")

    run_id = str(status.get("run_id", target))
    remote_run_root = PurePosixPath(paths["run_root"])
    resolved_base = destination_base or (config.local_run_cache / "fetched")
    local_run_root = resolved_base / remote_run_root.name
    return FetchPlan(
        run_id=run_id,
        remote_run_root=remote_run_root,
        destination_base=resolved_base,
        local_run_root=local_run_root,
        command=tuple(build_rsync_pull_command(config, remote_run_root, resolved_base)),
    )
