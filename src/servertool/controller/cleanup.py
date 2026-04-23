from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import shutil

from ..shared.config import Config
from .records import default_fetch_base, read_run_record, run_record_path
from .runs import TERMINAL_RUN_STATES, load_remote_status
from .transport import build_ssh_command


@dataclass(frozen=True)
class CleanupAction:
    label: str
    kind: str
    command: tuple[str, ...] = ()
    path: Path | None = None


@dataclass(frozen=True)
class CleanupPlan:
    run_id: str
    remote_state: str
    remote_state_confirmed: bool
    remote_run_root: PurePosixPath | None
    actions: tuple[CleanupAction, ...]
    notes: tuple[str, ...]


def build_remote_cleanup_plan(config: Config, run_id: str, *, force: bool = False) -> CleanupPlan:
    record = read_run_record(config, run_id)
    _validate_record_member_access(config, run_id, record)
    remote_state = ""
    remote_state_confirmed = False

    try:
        status = load_remote_status(config, run_id)
        remote_run_root = _remote_run_root_from_status(status)
        remote_state = str(status.get("state", ""))
        remote_state_confirmed = True
    except (OSError, RuntimeError, ValueError):
        remote_run_root = _remote_run_root_from_record(record)
        if remote_run_root is None:
            raise ValueError(f"Unable to resolve remote run path for {run_id}")
        if not force:
            raise ValueError(
                f"Remote status is unavailable for run '{run_id}'. Rerun with --force to delete by local record."
            )

    _validate_remote_run_root(config, run_id, remote_run_root)
    if remote_state_confirmed and remote_state not in TERMINAL_RUN_STATES and not force:
        raise ValueError(
            f"Refusing to delete run '{run_id}' while remote state is '{remote_state or '(unknown)'}'. Use --force to override."
        )

    notes: list[str] = []
    if not remote_state_confirmed:
        notes.append("Remote status could not be confirmed; cleanup will use the local run record path.")

    return CleanupPlan(
        run_id=run_id,
        remote_state=remote_state,
        remote_state_confirmed=remote_state_confirmed,
        remote_run_root=remote_run_root,
        actions=(
            CleanupAction(
                label="Remove remote run directory",
                kind="command",
                command=tuple(build_ssh_command(config, ["rm", "-rf", remote_run_root.as_posix()])),
            ),
        ),
        notes=tuple(notes),
    )


def build_run_cleanup_plan(
    config: Config,
    run_id: str,
    *,
    force: bool = False,
    local_only: bool = False,
    remote_only: bool = False,
) -> CleanupPlan:
    if local_only and remote_only:
        raise ValueError("Cannot combine --local-only and --remote-only")

    record = read_run_record(config, run_id)
    _validate_record_member_access(config, run_id, record)
    actions: list[CleanupAction] = []
    notes: list[str] = []
    remote_state = ""
    remote_state_confirmed = False
    remote_run_root: PurePosixPath | None = None

    if not local_only:
        remote_plan = build_remote_cleanup_plan(config, run_id, force=force)
        remote_state = remote_plan.remote_state
        remote_state_confirmed = remote_plan.remote_state_confirmed
        remote_run_root = remote_plan.remote_run_root
        actions.extend(remote_plan.actions)
        notes.extend(remote_plan.notes)

    if not remote_only:
        record_path = run_record_path(config, run_id)
        if record_path.exists():
            actions.append(
                CleanupAction(
                    label="Remove local run record",
                    kind="delete_path",
                    path=record_path,
                )
            )
        else:
            notes.append(f"Local run record not found: {record_path}")

        fetch_path, fetch_note = _planned_fetched_path(config, record, run_id, force=force)
        if fetch_path is not None:
            actions.append(
                CleanupAction(
                    label="Remove local fetched directory",
                    kind="delete_path",
                    path=fetch_path,
                )
            )
        elif fetch_note:
            notes.append(fetch_note)

    if not actions:
        raise ValueError(f"Nothing to clean up for run '{run_id}'")

    return CleanupPlan(
        run_id=run_id,
        remote_state=remote_state,
        remote_state_confirmed=remote_state_confirmed,
        remote_run_root=remote_run_root,
        actions=tuple(actions),
        notes=tuple(notes),
    )


def delete_local_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return
    path.unlink()


def _remote_run_root_from_status(status: dict[str, object]) -> PurePosixPath:
    paths = status.get("paths")
    if not isinstance(paths, dict) or not isinstance(paths.get("run_root"), str):
        raise ValueError("Remote status is missing paths.run_root")
    return PurePosixPath(paths["run_root"])


def _remote_run_root_from_record(record: dict[str, object] | None) -> PurePosixPath | None:
    if not isinstance(record, dict):
        return None
    value = record.get("remote_run_root")
    if isinstance(value, str) and value.strip():
        return PurePosixPath(value)
    return None


def _validate_remote_run_root(config: Config, run_id: str, remote_run_root: PurePosixPath) -> None:
    candidate_roots = [config.remote_member_root_posix]
    if config.remote_root_posix != config.remote_member_root_posix:
        candidate_roots.append(config.remote_root_posix)

    for root in candidate_roots:
        try:
            relative = remote_run_root.relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        if len(parts) != 4 or parts[0] != "projects" or parts[2] != "runs":
            raise ValueError(
                f"Refusing to delete remote path outside projects/*/runs/*: {remote_run_root.as_posix()}"
            )
        if parts[3] != run_id:
            raise ValueError(
                f"Refusing to delete remote path '{remote_run_root.as_posix()}' because it does not match run id '{run_id}'"
            )
        return

    raise ValueError(
        "Refusing to delete remote path outside the current member root or legacy shared root: "
        + remote_run_root.as_posix()
    )


def _planned_fetched_path(
    config: Config,
    record: dict[str, object] | None,
    run_id: str,
    *,
    force: bool,
) -> tuple[Path | None, str]:
    if not isinstance(record, dict):
        return None, "Local fetched directory is unknown because no run record is available"
    raw_path = record.get("local_fetch_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, "Local fetched directory has not been recorded yet"

    fetch_path = Path(raw_path).expanduser()
    if not fetch_path.exists():
        return None, f"Local fetched directory not found: {fetch_path}"
    if fetch_path.name != run_id:
        return None, f"Refusing to delete local fetched path with unexpected name: {fetch_path}"
    if _is_relative_to(fetch_path, default_fetch_base(config)):
        return fetch_path, ""
    if force:
        return fetch_path, ""
    return (
        None,
        f"Local fetched directory is outside the default fetched cache and was kept: {fetch_path}. Use --force to remove it.",
    )


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _validate_record_member_access(config: Config, run_id: str, record: dict[str, object] | None) -> None:
    if not isinstance(record, dict):
        return
    record_member_id = str(record.get("member_id", "")).strip()
    if record_member_id and record_member_id != config.member_id:
        raise ValueError(
            f"Run '{run_id}' belongs to member '{record_member_id}', not current member '{config.member_id}'"
        )
