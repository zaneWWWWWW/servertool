from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Iterator
import json
import os

from ..shared.config import Config
from ..shared.spec import RunSpec
from ..shared.system import command_exists, run_command, shlex_join


ENV_BUILD_METADATA = ".servertool-env-build.json"
MODEL_SOURCE_METADATA = ".servertool-model-source.json"


def prepare_run_assets(config: Config, spec: RunSpec, spec_dir: Path) -> dict[str, str]:
    code_path = _resolve_path(spec_dir, spec.assets.code.path)
    if not code_path.exists():
        raise FileNotFoundError(f"Code asset path does not exist: {code_path}")

    asset_env = {"SERVERTOOL_CODE_PATH": code_path.as_posix()}
    dataset_path = _prepare_dataset_asset(spec, spec_dir)
    if dataset_path:
        asset_env["SERVERTOOL_DATASET_PATH"] = dataset_path

    env_path = _prepare_env_asset(config, spec, spec_dir)
    if env_path:
        asset_env["SERVERTOOL_ENV_PATH"] = env_path

    model_path = _prepare_model_asset(config, spec, spec_dir)
    if model_path:
        asset_env["SERVERTOOL_MODEL_PATH"] = model_path
    return asset_env


def _prepare_dataset_asset(spec: RunSpec, spec_dir: Path) -> str:
    if spec.assets.dataset.source == "none":
        return ""
    dataset_path = _resolve_path(spec_dir, spec.assets.dataset.path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset asset path does not exist: {dataset_path}")
    return dataset_path.as_posix()


def _prepare_env_asset(config: Config, spec: RunSpec, spec_dir: Path) -> str:
    env_spec = spec.assets.env
    if env_spec.source == "none":
        return ""
    if env_spec.source in {"shared_path", "upload"}:
        env_path = _resolve_path(spec_dir, env_spec.path)
        if not env_path.exists():
            raise FileNotFoundError(f"Environment path does not exist: {env_path}")
        return env_path.as_posix()

    env_root = _resolve_env_root(config, spec_dir, spec)
    build_file = _resolve_path(spec_dir, env_spec.file)
    if not build_file.exists():
        raise FileNotFoundError(f"Environment build file does not exist: {build_file}")

    metadata = {
        "source": env_spec.source,
        "type": env_spec.build_type,
        "name": env_spec.name,
        "file": build_file.name,
        "file_sha256": _file_sha256(build_file),
    }
    metadata_path = env_root / ENV_BUILD_METADATA
    if env_root.exists():
        if metadata_path.exists():
            try:
                existing_metadata = json.loads(metadata_path.read_text())
            except json.JSONDecodeError:
                existing_metadata = None
            if existing_metadata == metadata:
                return env_root.as_posix()
        if any(env_root.iterdir()):
            raise RuntimeError(
                "Shared environment already exists with different build metadata; choose a new assets.env.name: "
                + env_root.as_posix()
            )

    env_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        if env_spec.build_type == "pip":
            _build_pip_env(config, env_root, build_file)
        else:
            _build_conda_env(config, env_root, build_file)
    except Exception:
        if env_root.exists() and not metadata_path.exists():
            shutil.rmtree(env_root, ignore_errors=True)
        raise
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return env_root.as_posix()


def _prepare_model_asset(config: Config, spec: RunSpec, spec_dir: Path) -> str:
    model_spec = spec.assets.model
    if model_spec.source == "none":
        return ""
    if model_spec.source in {"shared_path", "upload"}:
        model_root = _resolve_path(spec_dir, model_spec.path)
        if not model_root.exists():
            raise FileNotFoundError(f"Model path does not exist: {model_root}")
        return _resolve_model_path(model_root, model_spec.subpath).as_posix()

    model_root = _resolve_model_root(config, spec_dir, spec)
    metadata_path = model_root / MODEL_SOURCE_METADATA
    expected_metadata = _expected_model_source_metadata(spec)
    if model_root.exists() and any(model_root.iterdir()):
        if not metadata_path.exists():
            raise RuntimeError(
                "Shared model root already exists without hub metadata; use assets.model.source='shared_path' "
                "or clean the directory: "
                + model_root.as_posix()
            )
        try:
            existing_metadata = json.loads(metadata_path.read_text())
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid model metadata in {metadata_path}") from error
        if not _model_source_metadata_matches(existing_metadata, expected_metadata):
            raise RuntimeError(
                "Shared model root already exists with different hub metadata; choose a different "
                "assets.model revision or use assets.model.source='shared_path': "
                + model_root.as_posix()
            )
    else:
        model_root.parent.mkdir(parents=True, exist_ok=True)
        try:
            if model_spec.provider == "huggingface":
                _download_huggingface_model(config, model_root, model_spec.model_id, model_spec.revision or "main")
            else:
                _download_modelscope_model(config, model_root, model_spec.model_id, model_spec.revision or "main")
        except Exception:
            if model_root.exists() and not metadata_path.exists():
                shutil.rmtree(model_root, ignore_errors=True)
            raise
        metadata_path.write_text(json.dumps(expected_metadata, indent=2) + "\n")
    return _resolve_model_path(model_root, model_spec.subpath).as_posix()


def _expected_model_source_metadata(spec: RunSpec) -> dict[str, str]:
    return {
        "provider": spec.assets.model.provider,
        "id": spec.assets.model.model_id,
        "revision": spec.assets.model.revision or "main",
    }


def _model_source_metadata_matches(existing: object, expected: dict[str, str]) -> bool:
    if not isinstance(existing, dict):
        return False
    return {
        "provider": str(existing.get("provider", "")).strip(),
        "id": str(existing.get("id", "")).strip(),
        "revision": str(existing.get("revision", "")).strip() or "main",
    } == expected


def _resolve_env_root(config: Config, spec_dir: Path, spec: RunSpec) -> Path:
    raw_path = spec.assets.env.path.strip()
    if raw_path:
        return _resolve_path(spec_dir, raw_path)
    return Path((config.shared_env_root_posix / _slug(spec.assets.env.name)).as_posix())


def _resolve_model_root(config: Config, spec_dir: Path, spec: RunSpec) -> Path:
    raw_path = spec.assets.model.path.strip()
    if raw_path:
        return _resolve_path(spec_dir, raw_path)
    model_parts = [_slug(part) for part in spec.assets.model.model_id.split("/") if part.strip()]
    root = config.shared_model_root_posix.joinpath(
        spec.assets.model.provider,
        *model_parts,
        _slug(spec.assets.model.revision or "main"),
    )
    return Path(root.as_posix())


def _resolve_model_path(model_root: Path, subpath: str) -> Path:
    if not subpath.strip():
        return model_root
    resolved = model_root / PurePosixPath(subpath).as_posix()
    if not resolved.exists():
        raise FileNotFoundError(f"Model subpath does not exist: {resolved}")
    return resolved


def _build_pip_env(config: Config, env_root: Path, build_file: Path) -> None:
    if not command_exists(config.remote_python):
        raise RuntimeError(f"Python interpreter is not available for env build: {config.remote_python}")
    pip_cache_dir = Path(config.shared_pip_cache_root.as_posix())
    pip_cache_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PIP_CACHE_DIR"] = pip_cache_dir.as_posix()
    if config.pip_index_url:
        env["PIP_INDEX_URL"] = config.pip_index_url
    if config.pip_extra_index_url:
        env["PIP_EXTRA_INDEX_URL"] = config.pip_extra_index_url

    _run_checked_command([config.remote_python, "-m", "venv", env_root.as_posix()], env=env)
    env_python = env_root / "bin" / "python"
    _run_checked_command([env_python.as_posix(), "-m", "pip", "install", "--upgrade", "pip"], env=env)
    _run_checked_command([env_python.as_posix(), "-m", "pip", "install", "-r", build_file.as_posix()], env=env)


def _build_conda_env(config: Config, env_root: Path, build_file: Path) -> None:
    if not command_exists("conda"):
        raise RuntimeError("conda is not available for assets.env.source=build with type=conda")
    conda_cache_dir = Path(config.shared_conda_cache_root.as_posix())
    conda_cache_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CONDA_PKGS_DIRS"] = conda_cache_dir.as_posix()

    command = ["conda", "env", "create", "--prefix", env_root.as_posix(), "--file", build_file.as_posix(), "--yes"]
    channels = [item.strip() for item in config.conda_channels.replace(";", ",").split(",") if item.strip()]
    with _temporary_condarc(channels) as condarc_path:
        if condarc_path:
            env["CONDARC"] = condarc_path
        _run_checked_command(command, env=env)


def _download_huggingface_model(config: Config, target_dir: Path, model_id: str, revision: str) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError("huggingface_hub is required for assets.model.source=hub with provider=huggingface") from error

    cache_root = Path(config.shared_huggingface_cache_root.as_posix())
    cache_root.mkdir(parents=True, exist_ok=True)
    env = {
        "HF_HOME": cache_root.as_posix(),
        "HF_HUB_CACHE": (cache_root / "hub").as_posix(),
    }
    if config.hf_endpoint:
        env["HF_ENDPOINT"] = config.hf_endpoint

    with _temporary_env(env):
        kwargs = {
            "repo_id": model_id,
            "revision": revision,
            "local_dir": target_dir.as_posix(),
        }
        try:
            snapshot_download(local_dir_use_symlinks=False, **kwargs)
        except TypeError:
            snapshot_download(**kwargs)


def _download_modelscope_model(config: Config, target_dir: Path, model_id: str, revision: str) -> None:
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError as error:
        raise RuntimeError("modelscope is required for assets.model.source=hub with provider=modelscope") from error

    cache_root = Path(config.shared_modelscope_cache_root.as_posix())
    cache_root.mkdir(parents=True, exist_ok=True)
    env = {"MODELSCOPE_CACHE": cache_root.as_posix()}
    if config.modelscope_endpoint:
        env["MODELSCOPE_ENDPOINT"] = config.modelscope_endpoint

    with _temporary_env(env):
        try:
            snapshot_download(model_id, revision=revision, cache_dir=cache_root.as_posix(), local_dir=target_dir.as_posix())
        except TypeError:
            snapshot_download(model_id, revision=revision, cache_dir=cache_root.as_posix())


def _run_checked_command(command: list[str], *, env: dict[str, str]) -> None:
    result = run_command(command, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or shlex_join(command))


def _resolve_path(base_dir: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _slug(value: str) -> str:
    from ..shared.layout import slugify

    return slugify(value)


@contextmanager
def _temporary_condarc(channels: list[str]) -> Iterator[str | None]:
    if not channels:
        yield None
        return

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".condarc", delete=False) as handle:
        handle.write("channels:\n")
        for channel in channels:
            handle.write(f"  - {channel}\n")
        handle.write("default_channels: []\n")
        condarc_path = Path(handle.name)
    try:
        yield condarc_path.as_posix()
    finally:
        try:
            condarc_path.unlink()
        except OSError:
            pass


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
