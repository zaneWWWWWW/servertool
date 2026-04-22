from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
import re


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "run"


def build_run_id(run_name: str, now: datetime | None = None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    return f"{timestamp.astimezone(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slugify(run_name)}"


@dataclass(frozen=True)
class RunLayout:
    root: PurePosixPath
    project_slug: str
    run_id: str
    project_root: PurePosixPath
    assets_root: PurePosixPath
    code_root: PurePosixPath
    envs_root: PurePosixPath
    datasets_root: PurePosixPath
    models_root: PurePosixPath
    runs_root: PurePosixPath
    run_root: PurePosixPath
    spec_path: PurePosixPath
    meta_path: PurePosixPath
    status_path: PurePosixPath
    launch_path: PurePosixPath
    job_path: PurePosixPath
    stdout_log: PurePosixPath
    stderr_log: PurePosixPath
    outputs_dir: PurePosixPath
    ckpts_dir: PurePosixPath


def build_run_layout(root: PurePosixPath, project: str, run_id: str) -> RunLayout:
    project_slug = slugify(project)
    project_root = root / "projects" / project_slug
    assets_root = project_root / "assets"
    runs_root = project_root / "runs"
    run_root = runs_root / run_id
    return RunLayout(
        root=root,
        project_slug=project_slug,
        run_id=run_id,
        project_root=project_root,
        assets_root=assets_root,
        code_root=assets_root / "code",
        envs_root=assets_root / "envs",
        datasets_root=assets_root / "datasets",
        models_root=assets_root / "models",
        runs_root=runs_root,
        run_root=run_root,
        spec_path=run_root / "spec.json",
        meta_path=run_root / "meta.json",
        status_path=run_root / "status.json",
        launch_path=run_root / "launch.sh",
        job_path=run_root / "job.sbatch",
        stdout_log=run_root / "stdout.log",
        stderr_log=run_root / "stderr.log",
        outputs_dir=run_root / "outputs",
        ckpts_dir=run_root / "ckpts",
    )
