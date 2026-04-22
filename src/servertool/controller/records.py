from __future__ import annotations

from pathlib import Path, PurePosixPath
import json

from ..runner.state import read_json, utc_now_text, write_json
from ..shared.config import Config
from ..shared.spec import RunSpec


def run_record_path(config: Config, run_id: str) -> Path:
    return config.local_run_cache / f"{run_id}.json"


def default_fetch_base(config: Config) -> Path:
    return config.local_run_cache / "fetched"


def write_run_record(
    config: Config,
    run_id: str,
    spec_path: Path,
    remote_spec: RunSpec,
    remote_run_root: PurePosixPath,
) -> None:
    write_json(
        run_record_path(config, run_id),
        {
            "version": "1",
            "run_id": run_id,
            "project": remote_spec.project,
            "spec_path": str(spec_path),
            "remote_host": config.remote_host,
            "remote_root": remote_run_root.as_posix(),
            "remote_run_root": remote_run_root.as_posix(),
            "remote_trainhub_root": config.remote_root,
            "submitted_at": utc_now_text(),
        },
    )


def update_run_record(config: Config, run_id: str, updates: dict[str, str]) -> None:
    path = run_record_path(config, run_id)
    payload = read_json(path) if path.exists() else {"version": "1", "run_id": run_id}
    payload.update(updates)
    write_json(path, payload)


def read_run_record(config: Config, run_id: str) -> dict[str, object] | None:
    path = run_record_path(config, run_id)
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    payload.setdefault("record_path", str(path))
    return payload


def iter_run_records(config: Config) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if not config.local_run_cache.exists():
        return records
    for path in sorted(config.local_run_cache.glob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        payload.setdefault("record_path", str(path))
        records.append(payload)
    records.sort(key=lambda item: str(item.get("submitted_at", "")), reverse=True)
    return records
