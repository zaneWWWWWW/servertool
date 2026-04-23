from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Mapping
import json

if TYPE_CHECKING:
    from .config import Config


SPEC_VERSION = "2"

DATASET_SOURCES = {"none", "sync", "shared_path"}
ENV_SOURCES = {"none", "shared_path", "build", "upload"}
ENV_BUILD_TYPES = {"pip", "conda"}
MODEL_SOURCES = {"none", "hub", "shared_path", "upload"}
MODEL_PROVIDERS = {"huggingface", "modelscope"}


class SpecValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        joined = "\n".join(f"- {error}" for error in errors)
        super().__init__(f"Invalid run spec:\n{joined}")


@dataclass(frozen=True)
class CodeAssetSpec:
    source: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "path": self.path,
        }


@dataclass(frozen=True)
class DatasetAssetSpec:
    source: str
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"source": self.source}
        if self.path:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class EnvAssetSpec:
    source: str
    path: str = ""
    build_type: str = ""
    file: str = ""
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"source": self.source}
        if self.path:
            payload["path"] = self.path
        if self.build_type:
            payload["type"] = self.build_type
        if self.file:
            payload["file"] = self.file
        if self.name:
            payload["name"] = self.name
        return payload


@dataclass(frozen=True)
class ModelAssetSpec:
    source: str
    path: str = ""
    provider: str = ""
    model_id: str = ""
    revision: str = ""
    subpath: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"source": self.source}
        if self.path:
            payload["path"] = self.path
        if self.provider:
            payload["provider"] = self.provider
        if self.model_id:
            payload["id"] = self.model_id
        if self.revision:
            payload["revision"] = self.revision
        if self.subpath:
            payload["subpath"] = self.subpath
        return payload


@dataclass(frozen=True)
class AssetSpec:
    code: CodeAssetSpec
    env: EnvAssetSpec
    dataset: DatasetAssetSpec
    model: ModelAssetSpec

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.to_dict(),
            "dataset": self.dataset.to_dict(),
            "env": self.env.to_dict(),
            "model": self.model.to_dict(),
        }


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
            assets=AssetSpec(
                code=CodeAssetSpec(source="sync", path="."),
                env=EnvAssetSpec(source="none"),
                dataset=DatasetAssetSpec(source="none"),
                model=ModelAssetSpec(source="none"),
            ),
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
        code_payload = _require_mapping(assets_payload, "code", errors)
        dataset_payload = _require_mapping(assets_payload, "dataset", errors)
        env_payload = _require_mapping(assets_payload, "env", errors)
        model_payload = _require_mapping(assets_payload, "model", errors)
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
                code=CodeAssetSpec(
                    source=_require_string(code_payload, "source", errors),
                    path=_require_string(code_payload, "path", errors),
                ),
                env=EnvAssetSpec(
                    source=_require_string(env_payload, "source", errors),
                    path=_optional_string(env_payload, "path"),
                    build_type=_optional_string(env_payload, "type"),
                    file=_optional_string(env_payload, "file"),
                    name=_optional_string(env_payload, "name"),
                ),
                dataset=DatasetAssetSpec(
                    source=_require_string(dataset_payload, "source", errors),
                    path=_optional_string(dataset_payload, "path"),
                ),
                model=ModelAssetSpec(
                    source=_require_string(model_payload, "source", errors),
                    path=_optional_string(model_payload, "path"),
                    provider=_optional_string(model_payload, "provider"),
                    model_id=_optional_string(model_payload, "id"),
                    revision=_optional_string(model_payload, "revision") or "main",
                    subpath=_optional_string(model_payload, "subpath"),
                ),
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
            issues.append("launch.scheduler must be 'slurm' in v2")
        if self.notify.email.enabled and not self.notify.email.to:
            issues.append("notify.email.to must contain at least one recipient when email is enabled")
        if not self.fetch.include:
            issues.append("fetch.include must contain at least one pattern")
        _validate_assets(self.assets, issues)
        _validate_fetch_patterns(self.fetch.include, issues)
        if issues:
            raise SpecValidationError(issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project": self.project,
            "run_name": self.run_name,
            "assets": self.assets.to_dict(),
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


def _validate_assets(assets: AssetSpec, errors: list[str]) -> None:
    if assets.code.source != "sync":
        errors.append("assets.code.source must be 'sync'")
    if not assets.code.path.strip():
        errors.append("assets.code.path must be a non-empty string")

    dataset_source = assets.dataset.source
    if dataset_source not in DATASET_SOURCES:
        errors.append(f"assets.dataset.source must be one of: {', '.join(sorted(DATASET_SOURCES))}")
    elif dataset_source != "none" and not assets.dataset.path.strip():
        errors.append("assets.dataset.path must be set when dataset source is not 'none'")
    elif dataset_source == "shared_path" and not _is_absolute_posix_path(assets.dataset.path):
        errors.append("assets.dataset.path must be an absolute remote path when dataset source is 'shared_path'")

    env_source = assets.env.source
    if env_source not in ENV_SOURCES:
        errors.append(f"assets.env.source must be one of: {', '.join(sorted(ENV_SOURCES))}")
    elif env_source in {"shared_path", "upload"} and not assets.env.path.strip():
        errors.append(f"assets.env.path must be set when env source is '{env_source}'")
    elif env_source == "shared_path" and not _is_absolute_posix_path(assets.env.path):
        errors.append("assets.env.path must be an absolute remote path when env source is 'shared_path'")
    elif env_source == "build":
        if assets.env.build_type not in ENV_BUILD_TYPES:
            errors.append(f"assets.env.type must be one of: {', '.join(sorted(ENV_BUILD_TYPES))}")
        if not assets.env.file.strip():
            errors.append("assets.env.file must be set when env source is 'build'")
        if not assets.env.name.strip():
            errors.append("assets.env.name must be set when env source is 'build'")

    model_source = assets.model.source
    if model_source not in MODEL_SOURCES:
        errors.append(f"assets.model.source must be one of: {', '.join(sorted(MODEL_SOURCES))}")
    elif model_source in {"shared_path", "upload"} and not assets.model.path.strip():
        errors.append(f"assets.model.path must be set when model source is '{model_source}'")
    elif model_source == "shared_path" and not _is_absolute_posix_path(assets.model.path):
        errors.append("assets.model.path must be an absolute remote path when model source is 'shared_path'")
    elif model_source == "hub":
        if assets.model.provider not in MODEL_PROVIDERS:
            errors.append(f"assets.model.provider must be one of: {', '.join(sorted(MODEL_PROVIDERS))}")
        if not assets.model.model_id.strip():
            errors.append("assets.model.id must be set when model source is 'hub'")
    if assets.model.subpath:
        if _is_absolute_posix_path(assets.model.subpath):
            errors.append("assets.model.subpath must be relative to the resolved model root")
        elif _contains_parent_escape(assets.model.subpath):
            errors.append("assets.model.subpath must not escape the resolved model root")

def _is_absolute_posix_path(path: str) -> bool:
    return path.strip().startswith("/")


def _contains_parent_escape(path: str) -> bool:
    return any(part == ".." for part in PurePosixPath(path).parts)


def _validate_fetch_patterns(patterns: tuple[str, ...], errors: list[str]) -> None:
    for pattern in patterns:
        value = pattern.strip()
        if not value:
            errors.append("fetch.include entries must be non-empty strings")
            continue
        if _is_absolute_posix_path(value):
            errors.append("fetch.include entries must be relative to the run root")
            continue
        if _contains_parent_escape(value):
            errors.append("fetch.include entries must not escape the run root")


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


def _optional_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


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
