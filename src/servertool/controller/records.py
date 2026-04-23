from __future__ import annotations

from pathlib import Path, PurePosixPath
import json
from typing import Any, Mapping

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
    audit: Mapping[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "version": "1",
        "run_id": run_id,
        "member_id": config.member_id,
        "workspace_name": config.workspace_name,
        "project": remote_spec.project,
        "assets": remote_spec.assets.to_dict(),
        "fetch_include": list(remote_spec.fetch.include),
        "spec_path": str(spec_path),
        "remote_host": config.remote_host,
        "remote_user": config.remote_user,
        "remote_root": config.remote_member_root,
        "remote_run_root": remote_run_root.as_posix(),
        "remote_member_root": config.remote_member_root,
        "remote_trainhub_root": config.remote_root,
        "submitted_at": utc_now_text(),
    }
    if audit:
        payload.update(dict(audit))
    write_json(
        run_record_path(config, run_id),
        payload,
    )


def update_run_record(config: Config, run_id: str, updates: Mapping[str, Any]) -> None:
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
        if not _record_matches_current_member(config, payload):
            continue
        payload.setdefault("record_path", str(path))
        records.append(payload)
    records.sort(key=lambda item: str(item.get("submitted_at", "")), reverse=True)
    return records


def iter_all_run_records(config: Config) -> list[dict[str, object]]:
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


def _record_matches_current_member(config: Config, record: Mapping[str, Any]) -> bool:
    member_id = str(record.get("member_id", "")).strip()
    if member_id:
        return member_id == config.member_id

    remote_member_root = str(record.get("remote_member_root", "")).strip()
    if remote_member_root:
        return remote_member_root == config.remote_member_root

    return True
