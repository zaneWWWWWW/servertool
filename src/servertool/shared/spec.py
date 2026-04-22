from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping
import json

if TYPE_CHECKING:
    from .config import Config


SPEC_VERSION = "1"


class SpecValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        joined = "\n".join(f"- {error}" for error in errors)
        super().__init__(f"Invalid run spec:\n{joined}")


@dataclass(frozen=True)
class AssetSpec:
    code: str
    env: str
    dataset: str
    model: str


@dataclass(frozen=True)
class LaunchSpec:
    scheduler: str
    partition: str
    gpus: int
    cpus: int
    mem: str
    time: str
    workdir: str
    command: str


@dataclass(frozen=True)
class FetchSpec:
    include: tuple[str, ...]


@dataclass(frozen=True)
class NotifyEmailSpec:
    enabled: bool
    to: tuple[str, ...]


@dataclass(frozen=True)
class NotifySpec:
    email: NotifyEmailSpec


@dataclass(frozen=True)
class RunSpec:
    version: str
    project: str
    run_name: str
    assets: AssetSpec
    launch: LaunchSpec
    fetch: FetchSpec
    notify: NotifySpec

    @classmethod
    def defaults(
        cls,
        config: Config,
        project: str,
        run_name: str = "baseline",
    ) -> "RunSpec":
        notify_to = (config.notify_email_to,) if config.notify_email_to else ()
        return cls(
            version=SPEC_VERSION,
            project=project,
            run_name=run_name,
            assets=AssetSpec(code=".", env="", dataset="", model=""),
            launch=LaunchSpec(
                scheduler="slurm",
                partition=config.a40_partition,
                gpus=1,
                cpus=8,
                mem="32G",
                time="04:00:00",
                workdir=".",
                command="python train.py",
            ),
            fetch=FetchSpec(include=("outputs/**", "ckpts/**")),
            notify=NotifySpec(email=NotifyEmailSpec(enabled=bool(notify_to), to=notify_to)),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunSpec":
        errors: list[str] = []
        version = _require_string(payload, "version", errors)
        project = _require_string(payload, "project", errors)
        run_name = _require_string(payload, "run_name", errors)
        assets_payload = _require_mapping(payload, "assets", errors)
        launch_payload = _require_mapping(payload, "launch", errors)
        fetch_payload = _require_mapping(payload, "fetch", errors)
        notify_payload = _require_mapping(payload, "notify", errors)
        email_payload = _require_mapping(notify_payload, "email", errors)

        if errors:
            raise SpecValidationError(errors)

        spec = cls(
            version=version,
            project=project,
            run_name=run_name,
            assets=AssetSpec(
                code=_require_string(assets_payload, "code", errors),
                env=_require_string_value(assets_payload, "env", errors),
                dataset=_require_string_value(assets_payload, "dataset", errors),
                model=_require_string_value(assets_payload, "model", errors),
            ),
            launch=LaunchSpec(
                scheduler=_require_string(launch_payload, "scheduler", errors),
                partition=_require_string(launch_payload, "partition", errors),
                gpus=_require_positive_int(launch_payload, "gpus", errors),
                cpus=_require_positive_int(launch_payload, "cpus", errors),
                mem=_require_string(launch_payload, "mem", errors),
                time=_require_string(launch_payload, "time", errors),
                workdir=_require_string(launch_payload, "workdir", errors),
                command=_require_string(launch_payload, "command", errors),
            ),
            fetch=FetchSpec(include=tuple(_require_string_list(fetch_payload, "include", errors))),
            notify=NotifySpec(
                email=NotifyEmailSpec(
                    enabled=_require_bool(email_payload, "enabled", errors),
                    to=tuple(_require_string_list(email_payload, "to", errors)),
                )
            ),
        )
        spec.validate(errors)
        return spec

    def validate(self, errors: list[str] | None = None) -> None:
        issues = [] if errors is None else errors
        if self.version != SPEC_VERSION:
            issues.append(f"version must be '{SPEC_VERSION}'")
        if self.launch.scheduler != "slurm":
            issues.append("launch.scheduler must be 'slurm' in v1")
        if self.notify.email.enabled and not self.notify.email.to:
            issues.append("notify.email.to must contain at least one recipient when email is enabled")
        if not self.fetch.include:
            issues.append("fetch.include must contain at least one pattern")
        if issues:
            raise SpecValidationError(issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project": self.project,
            "run_name": self.run_name,
            "assets": {
                "code": self.assets.code,
                "env": self.assets.env,
                "dataset": self.assets.dataset,
                "model": self.assets.model,
            },
            "launch": {
                "scheduler": self.launch.scheduler,
                "partition": self.launch.partition,
                "gpus": self.launch.gpus,
                "cpus": self.launch.cpus,
                "mem": self.launch.mem,
                "time": self.launch.time,
                "workdir": self.launch.workdir,
                "command": self.launch.command,
            },
            "fetch": {
                "include": list(self.fetch.include),
            },
            "notify": {
                "email": {
                    "enabled": self.notify.email.enabled,
                    "to": list(self.notify.email.to),
                }
            },
        }


def load_spec(path: Path) -> RunSpec:
    payload = json.loads(path.read_text())
    return RunSpec.from_dict(payload)


def write_spec(path: Path, spec: RunSpec) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec.to_dict(), indent=2) + "\n")


def _require_mapping(payload: Mapping[str, Any], key: str, errors: list[str]) -> Mapping[str, Any]:
    value = payload.get(key)
    if isinstance(value, dict):
        return value
    errors.append(f"{key} must be an object")
    return {}


def _require_string(payload: Mapping[str, Any], key: str, errors: list[str]) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    errors.append(f"{key} must be a non-empty string")
    return ""


def _require_string_value(payload: Mapping[str, Any], key: str, errors: list[str]) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    errors.append(f"{key} must be a string")
    return ""


def _require_positive_int(payload: Mapping[str, Any], key: str, errors: list[str]) -> int:
    value = payload.get(key)
    if isinstance(value, int) and value > 0:
        return value
    errors.append(f"{key} must be a positive integer")
    return 0


def _require_string_list(payload: Mapping[str, Any], key: str, errors: list[str]) -> list[str]:
    value = payload.get(key)
    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        return value
    errors.append(f"{key} must be a list of non-empty strings")
    return []


def _require_bool(payload: Mapping[str, Any], key: str, errors: list[str]) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    errors.append(f"{key} must be a boolean")
    return False
