from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import socket
import time
from typing import Callable

from ..shared.config import Config
from ..shared.layout import RunLayout, build_run_id, build_run_layout, slugify
from ..shared.spec import RunSpec, load_spec, write_spec
from ..shared.system import run_command
from . import transport as remote_ops
from .records import read_run_record
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
    audit: "SubmissionAudit"
    commands: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class UploadPlan:
    label: str
    source: Path
    destination: PurePosixPath
    contents_only: bool


@dataclass(frozen=True)
class FetchPlan:
    run_id: str
    remote_run_root: PurePosixPath
    destination_base: Path
    local_run_root: Path
    fetch_include: tuple[str, ...]
    command: tuple[str, ...]


@dataclass(frozen=True)
class SubmissionAudit:
    submitted_by: str
    controller_user: str
    controller_host: str
    controller_platform: str
    controller_version: str
    git_rev: str
    git_dirty: bool
    spec_sha256: str

    def to_runner_env(self) -> dict[str, str]:
        return {
            "SERVERTOOL_SUBMITTED_BY": self.submitted_by,
            "SERVERTOOL_CONTROLLER_USER": self.controller_user,
            "SERVERTOOL_CONTROLLER_HOST": self.controller_host,
            "SERVERTOOL_CONTROLLER_PLATFORM": self.controller_platform,
            "SERVERTOOL_CONTROLLER_VERSION": self.controller_version,
            "SERVERTOOL_SOURCE_GIT_REV": self.git_rev,
            "SERVERTOOL_SOURCE_GIT_DIRTY": "1" if self.git_dirty else "0",
            "SERVERTOOL_SPEC_SHA256": self.spec_sha256,
        }

    def to_record(self) -> dict[str, object]:
        return {
            "submitted_by": self.submitted_by,
            "controller_user": self.controller_user,
            "controller_host": self.controller_host,
            "controller_platform": self.controller_platform,
            "controller_version": self.controller_version,
            "git_rev": self.git_rev,
            "git_dirty": self.git_dirty,
            "spec_sha256": self.spec_sha256,
        }


def ensure_remote_host(config: Config) -> None:
    remote_ops.ensure_remote_host(config)


def _resolve_local_asset_path(spec_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (spec_path.parent / candidate).resolve()


def _remote_code_path(layout: RunLayout, run_id: str) -> PurePosixPath:
    return layout.code_root / run_id


def _build_upload_plan(label: str, source: Path, destination_root: PurePosixPath, run_id: str) -> UploadPlan:
    if source.is_dir():
        return UploadPlan(
            label=label,
            source=source,
            destination=destination_root / run_id,
            contents_only=True,
        )
    return UploadPlan(
        label=label,
        source=source,
        destination=destination_root / run_id / source.name,
        contents_only=False,
    )


def _shared_env_path(config: Config, env_name: str) -> PurePosixPath:
    return config.shared_env_root_posix / slugify(env_name)


def _shared_model_path(config: Config, provider: str, model_id: str, revision: str) -> PurePosixPath:
    model_parts = [slugify(part) for part in model_id.split("/") if part.strip()]
    return config.shared_model_root_posix.joinpath(provider, *model_parts, slugify(revision or "main"))


def _remote_workdir(code_root: PurePosixPath, workdir: str) -> str:
    if not workdir or workdir == ".":
        return code_root.as_posix()
    candidate = PurePosixPath(workdir)
    if candidate.is_absolute():
        return candidate.as_posix()
    return (code_root / candidate).as_posix()


def _build_remote_spec(spec_path: Path, spec: RunSpec, layout: RunLayout, config: Config) -> tuple[RunSpec, list[UploadPlan]]:
    code_destination = _remote_code_path(layout, layout.run_id)
    code_source = _resolve_local_asset_path(spec_path, spec.assets.code.path)
    if not code_source.exists():
        raise FileNotFoundError(f"Code asset path does not exist: {code_source}")

    upload_plans = [_build_upload_plan("Sync code asset", code_source, layout.code_root, layout.run_id)]

    remote_dataset = spec.assets.dataset
    if spec.assets.dataset.source == "sync":
        dataset_source = _resolve_local_asset_path(spec_path, spec.assets.dataset.path)
        if not dataset_source.exists():
            raise FileNotFoundError(f"Dataset asset path does not exist: {dataset_source}")
        dataset_upload = _build_upload_plan("Sync dataset asset", dataset_source, layout.datasets_root, layout.run_id)
        upload_plans.append(dataset_upload)
        remote_dataset = replace(spec.assets.dataset, path=dataset_upload.destination.as_posix())

    remote_env = spec.assets.env
    if spec.assets.env.source == "build":
        build_file = _resolve_local_asset_path(spec_path, spec.assets.env.file)
        if not build_file.exists():
            raise FileNotFoundError(f"Environment build file does not exist: {build_file}")
        env_upload = _build_upload_plan("Upload environment build file", build_file, layout.envs_root, layout.run_id)
        upload_plans.append(env_upload)
        remote_env = replace(
            spec.assets.env,
            file=env_upload.destination.as_posix(),
            path=_shared_env_path(config, spec.assets.env.name).as_posix(),
        )
    elif spec.assets.env.source == "upload":
        env_source = _resolve_local_asset_path(spec_path, spec.assets.env.path)
        if not env_source.exists():
            raise FileNotFoundError(f"Uploaded environment path does not exist: {env_source}")
        env_upload = _build_upload_plan("Upload environment asset", env_source, layout.envs_root, layout.run_id)
        upload_plans.append(env_upload)
        remote_env = replace(spec.assets.env, path=env_upload.destination.as_posix())

    remote_model = spec.assets.model
    if spec.assets.model.source == "hub":
        remote_model = replace(
            spec.assets.model,
            path=_shared_model_path(
                config,
                spec.assets.model.provider,
                spec.assets.model.model_id,
                spec.assets.model.revision or "main",
            ).as_posix(),
            revision=spec.assets.model.revision or "main",
        )
    elif spec.assets.model.source == "upload":
        model_source = _resolve_local_asset_path(spec_path, spec.assets.model.path)
        if not model_source.exists():
            raise FileNotFoundError(f"Uploaded model path does not exist: {model_source}")
        model_upload = _build_upload_plan("Upload model asset", model_source, layout.models_root, layout.run_id)
        upload_plans.append(model_upload)
        remote_model = replace(spec.assets.model, path=model_upload.destination.as_posix())

    remote_assets = replace(
        spec.assets,
        code=replace(spec.assets.code, path=code_destination.as_posix()),
        dataset=remote_dataset,
        env=remote_env,
        model=remote_model,
    )
    remote_launch = replace(spec.launch, workdir=_remote_workdir(code_destination, spec.launch.workdir))
    remote_spec = replace(spec, assets=remote_assets, launch=remote_launch)
    return remote_spec, upload_plans


def build_submission_audit(config: Config, remote_spec: RunSpec, *, submitted_by: str | None = None) -> SubmissionAudit:
    controller_user = _controller_user_text()
    effective_submitter = (submitted_by or config.member_id).strip() or config.member_id
    git_rev, git_dirty = _git_source_state(config.root)
    spec_text = json.dumps(remote_spec.to_dict(), sort_keys=True, separators=(",", ":"))
    return SubmissionAudit(
        submitted_by=effective_submitter,
        controller_user=controller_user,
        controller_host=_controller_host_text(),
        controller_platform=platform.platform(),
        controller_version=config.version,
        git_rev=git_rev,
        git_dirty=git_dirty,
        spec_sha256=hashlib.sha256(spec_text.encode("utf-8")).hexdigest(),
    )


def _controller_user_text() -> str:
    try:
        import getpass

        value = getpass.getuser().strip()
    except (ImportError, OSError, KeyError):
        value = ""
    return value or "user"


def _controller_host_text() -> str:
    try:
        value = socket.gethostname().strip()
    except OSError:
        value = ""
    return value or "unknown-host"


def _git_source_state(root: Path) -> tuple[str, bool]:
    try:
        revision = run_command(["git", "-C", str(root), "rev-parse", "HEAD"])
        if revision.returncode != 0:
            return "", False
        status = run_command(["git", "-C", str(root), "status", "--short"])
    except OSError:
        return "", False
    return revision.stdout.strip(), bool(status.stdout.strip())


def prepare_submit(
    config: Config,
    spec_path: Path,
    explicit_run_id: str | None,
    staging_dir: Path,
) -> SubmitPlan:
    spec = load_spec(spec_path)
    submitted_by = config.member_id
    run_id = explicit_run_id or build_run_id(spec.run_name, submitted_by=submitted_by)
    layout = build_run_layout(config.remote_member_root_posix, spec.project, run_id)
    remote_spec, upload_plans = _build_remote_spec(spec_path, spec, layout, config)
    audit = build_submission_audit(config, remote_spec, submitted_by=submitted_by)

    incoming_dir = config.remote_member_root_posix / ".incoming" / run_id
    incoming_spec = incoming_dir / "spec.json"
    commands: list[tuple[str, tuple[str, ...]]] = []

    mkdir_targets = {incoming_dir.as_posix()}
    for upload_plan in upload_plans:
        if upload_plan.contents_only:
            mkdir_targets.add(upload_plan.destination.as_posix())
        else:
            mkdir_targets.add(str(upload_plan.destination.parent))
    mkdir_args = ["mkdir", "-p", *sorted(mkdir_targets)]
    commands.append(("Prepare remote directories", tuple(build_ssh_command(config, mkdir_args))))
    for upload_plan in upload_plans:
        commands.append(
            (
                upload_plan.label,
                tuple(
                    build_rsync_push_command(
                        config,
                        upload_plan.source,
                        upload_plan.destination,
                        contents_only=upload_plan.contents_only,
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
                        env=remote_servertool_env(config, audit.to_runner_env()),
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
                        env=remote_servertool_env(config),
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
        audit=audit,
        commands=tuple(commands),
    )


def _remote_run_root_from_status(status: dict[str, object]) -> PurePosixPath:
    paths = status.get("paths")
    if not isinstance(paths, dict) or not isinstance(paths.get("run_root"), str):
        raise ValueError("Remote status is missing paths.run_root")
    return PurePosixPath(paths["run_root"])


def _path_is_relative_to(candidate: PurePosixPath, root: PurePosixPath) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _record_matches_current_member(
    config: Config,
    record: dict[str, object] | None,
    remote_run_root: PurePosixPath,
) -> bool:
    if not isinstance(record, dict):
        return False

    record_member_id = str(record.get("member_id", "")).strip()
    if record_member_id and record_member_id != config.member_id:
        return False

    record_remote_member_root = str(record.get("remote_member_root", "")).strip()
    if record_remote_member_root and record_remote_member_root != config.remote_member_root:
        return False

    record_remote_run_root = str(record.get("remote_run_root", "")).strip()
    return record_remote_run_root == remote_run_root.as_posix()


def _validate_remote_status_access(config: Config, target: str, status: dict[str, object]) -> None:
    run_id = str(status.get("run_id", target))
    remote_run_root = _remote_run_root_from_status(status)
    remote_member_id = str(status.get("member_id", "")).strip()
    if remote_member_id and remote_member_id != config.member_id:
        raise ValueError(
            f"Run '{run_id}' belongs to member '{remote_member_id}', not current member '{config.member_id}'"
        )

    if _path_is_relative_to(remote_run_root, config.remote_member_root_posix):
        return

    if _path_is_relative_to(remote_run_root, config.remote_root_posix):
        if remote_member_id == config.member_id:
            return
        record = read_run_record(config, run_id)
        if _record_matches_current_member(config, record, remote_run_root):
            return
        raise ValueError(
            "Refusing to access a legacy shared-root run without a matching local run record for the current member: "
            + run_id
        )

    raise ValueError(
        "Refusing to access run outside the current member root or legacy shared root: " + remote_run_root.as_posix()
    )


def load_remote_status(config: Config, run_id: str) -> dict[str, object]:
    result = remote_ops.run_ssh_command(
        config,
        servertool_remote_argv(
            config,
            ["runner", "status", run_id],
            env=remote_servertool_env(config),
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "remote status failed")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Remote status did not return a JSON object")
    _validate_remote_status_access(config, run_id, payload)
    return payload


def load_remote_log_text(config: Config, target: str, lines: int, use_stderr: bool) -> str:
    load_remote_status(config, target)
    remote_args = ["runner", "tail", target, "--lines", str(max(lines, 1))]
    if use_stderr:
        remote_args.append("--stderr")
    result = remote_ops.run_ssh_command(
        config,
        servertool_remote_argv(
            config,
            remote_args,
            env=remote_servertool_env(config),
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


def _fetch_include_from_payload(payload: dict[str, object] | None) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()

    fetch = payload.get("fetch")
    if isinstance(fetch, dict):
        include = fetch.get("include")
        if isinstance(include, list) and all(isinstance(item, str) and item.strip() for item in include):
            return tuple(item.strip() for item in include)

    include = payload.get("fetch_include")
    if isinstance(include, list) and all(isinstance(item, str) and item.strip() for item in include):
        return tuple(item.strip() for item in include)
    return ()


def _normalize_fetch_pattern(pattern: str) -> str:
    value = pattern.strip().lstrip("/")
    while value.startswith("./"):
        value = value[2:]
    return value


def _build_fetch_rsync_args(fetch_include: tuple[str, ...]) -> tuple[str, ...]:
    if not fetch_include:
        return ()

    args = ["--prune-empty-dirs", "--include=*/"]
    for pattern in fetch_include:
        normalized = _normalize_fetch_pattern(pattern)
        if normalized:
            args.append(f"--include={normalized}")
    args.append("--exclude=*")
    return tuple(args)


def build_fetch_plan(config: Config, target: str, destination_base: Path | None = None) -> FetchPlan:
    status = load_remote_status(config, target)
    run_id = str(status.get("run_id", target))
    remote_run_root = _remote_run_root_from_status(status)
    resolved_base = destination_base or (config.local_run_cache / "fetched")
    local_run_root = resolved_base / remote_run_root.name
    record = read_run_record(config, run_id)
    fetch_include = _fetch_include_from_payload(status) or _fetch_include_from_payload(record)
    return FetchPlan(
        run_id=run_id,
        remote_run_root=remote_run_root,
        destination_base=resolved_base,
        local_run_root=local_run_root,
        fetch_include=fetch_include,
        command=tuple(
            build_rsync_pull_command(
                config,
                remote_run_root,
                resolved_base,
                extra_args=_build_fetch_rsync_args(fetch_include),
            )
        ),
    )
