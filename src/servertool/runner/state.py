from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json

from ..shared.layout import RunLayout
from ..shared.spec import RunSpec


STATE_VERSION = "1"


def utc_now_text(now: datetime | None = None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    return timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def layout_paths(layout: RunLayout) -> dict[str, str]:
    return {
        "project_root": layout.project_root.as_posix(),
        "run_root": layout.run_root.as_posix(),
        "spec": layout.spec_path.as_posix(),
        "meta": layout.meta_path.as_posix(),
        "status": layout.status_path.as_posix(),
        "launch": layout.launch_path.as_posix(),
        "job": layout.job_path.as_posix(),
        "stdout": layout.stdout_log.as_posix(),
        "stderr": layout.stderr_log.as_posix(),
        "outputs": layout.outputs_dir.as_posix(),
        "ckpts": layout.ckpts_dir.as_posix(),
    }


def build_meta(spec: RunSpec, run_id: str, layout: RunLayout, created_at: str | None = None) -> dict[str, Any]:
    timestamp = created_at or utc_now_text()
    return {
        "version": STATE_VERSION,
        "run_id": run_id,
        "project": spec.project,
        "project_slug": layout.project_slug,
        "run_name": spec.run_name,
        "scheduler": spec.launch.scheduler,
        "created_at": timestamp,
        "paths": layout_paths(layout),
    }


def build_status(
    run_id: str,
    layout: RunLayout,
    state: str,
    message: str,
    created_at: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    job_id: str | None = None,
    pid: int | None = None,
    exit_code: int | None = None,
    notify_error: str = "",
) -> dict[str, Any]:
    timestamp = created_at or utc_now_text()
    return {
        "version": STATE_VERSION,
        "run_id": run_id,
        "state": state,
        "job_id": job_id,
        "pid": pid,
        "exit_code": exit_code,
        "created_at": timestamp,
        "started_at": started_at,
        "ended_at": ended_at,
        "updated_at": utc_now_text(),
        "message": message,
        "paths": layout_paths(layout),
        "notify_error": notify_error,
    }


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2) + "\n")
