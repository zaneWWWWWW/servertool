from __future__ import annotations

from argparse import SUPPRESS, ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path, PurePosixPath
import json
import os
import re
import shlex
import sys

from ..context import AppContext
from ..runner.assets import prepare_run_assets
from ..shared.layout import build_run_id, build_run_layout, slugify
from ..runner.notify_email import (
    build_run_notification_body,
    build_run_notification_subject,
    read_log_tail,
    send_email,
    send_test_email,
)
from ..runner.state import build_meta, build_status, read_json, utc_now_text, write_json
from ..shared.spec import SpecValidationError, load_spec, write_spec
from ..shared.system import command_exists, run_command


JOB_ID_PATTERN = re.compile(r"(\d+)")
NOTIFIABLE_STATES = {"succeeded", "failed"}


def register(subparsers: _SubParsersAction[ArgumentParser], *, hidden: bool = False) -> ArgumentParser:
    parser = subparsers.add_parser(
        "runner",
        help=SUPPRESS if hidden else "Manage runner-side run state",
        description="Prepare runs, inspect status, and deliver runner-side notifications on the Linux host.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["prepare", "start", "status", "tail", "notify", "finalize"],
        help="Runner action",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Spec path, run id, run path, or test-recipient email depending on the action",
    )
    parser.add_argument("--run-id", help="Use an explicit run id when preparing a run")
    parser.add_argument("--lines", type=int, default=50, help="Number of log lines to print for tail")
    parser.add_argument("--stderr", action="store_true", help="Read stderr.log instead of stdout.log")
    parser.add_argument(
        "--test",
        nargs="?",
        const="",
        metavar="EMAIL",
        help="Send a test email, optionally to an explicit recipient",
    )
    parser.add_argument("--exit-code", type=int, help="Process exit code for runner finalize")
    parser.set_defaults(func=run)
    return parser


def _as_local_path(path: PurePosixPath) -> Path:
    return Path(path.as_posix())


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


def _resolve_workdir(run_root: PurePosixPath, workdir: str) -> str:
    if not workdir or workdir == ".":
        return run_root.as_posix()
    candidate = PurePosixPath(workdir)
    if candidate.is_absolute():
        return candidate.as_posix()
    return (run_root / candidate).as_posix()


def _render_launch_script(
    layout: PurePosixPath,
    workdir: str,
    command: str,
    runner_python: str,
    runner_module_root: str,
    asset_env: dict[str, str],
    runtime_env: dict[str, str],
) -> str:
    exports: list[str] = []
    for key, value in sorted(asset_env.items()):
        if value:
            exports.append(f"export {key}={shlex.quote(value)}")
    for key, value in sorted(runtime_env.items()):
        if value:
            exports.append(f"export {key}={shlex.quote(value)}")
    if asset_env.get("SERVERTOOL_ENV_PATH"):
        exports.extend(
            [
                'if [ -d "$SERVERTOOL_ENV_PATH/bin" ]; then',
                '  export PATH="$SERVERTOOL_ENV_PATH/bin:$PATH"',
                "fi",
            ]
        )
    exports_block = "\n".join(exports)
    if exports_block:
        exports_block += "\n"
    return (
        "#!/bin/sh\n"
        "set -eu\n\n"
        f"RUN_DIR={shlex.quote(layout.as_posix())}\n"
        f"WORKDIR={shlex.quote(workdir)}\n"
        f"RUNNER_PYTHON={shlex.quote(runner_python)}\n"
        f"RUNNER_MODULE_ROOT={shlex.quote(runner_module_root)}\n"
        f"{exports_block}"
        "mkdir -p \"$RUN_DIR/outputs\" \"$RUN_DIR/ckpts\"\n"
        "cd \"$WORKDIR\"\n"
        "set +e\n"
        f"{command}\n"
        "EXIT_CODE=$?\n"
        "set -e\n"
        "env PYTHONPATH=\"$RUNNER_MODULE_ROOT\" \"$RUNNER_PYTHON\" -m servertool runner finalize \"$RUN_DIR\" --exit-code \"$EXIT_CODE\" || true\n"
        "exit \"$EXIT_CODE\"\n"
    )


def _shared_runtime_env(context: AppContext) -> dict[str, str]:
    config = context.config
    return {
        "PIP_CACHE_DIR": config.shared_pip_cache_root.as_posix(),
        "CONDA_PKGS_DIRS": config.shared_conda_cache_root.as_posix(),
        "HF_HOME": config.shared_huggingface_cache_root.as_posix(),
        "HF_HUB_CACHE": (config.shared_huggingface_cache_root / "hub").as_posix(),
        "MODELSCOPE_CACHE": config.shared_modelscope_cache_root.as_posix(),
        "PIP_INDEX_URL": config.pip_index_url,
        "PIP_EXTRA_INDEX_URL": config.pip_extra_index_url,
        "HF_ENDPOINT": config.hf_endpoint,
        "MODELSCOPE_ENDPOINT": config.modelscope_endpoint,
    }


def _render_job_script(context: AppContext, run_root: PurePosixPath, launch_path: PurePosixPath, stdout_log: PurePosixPath, stderr_log: PurePosixPath, run_name: str, partition: str, gpus: int, cpus: int, mem: str, wall_time: str) -> str:
    job_name = slugify(run_name)[:64]
    install_path = shlex.quote(context.config.install_path)
    return (
        "#!/bin/sh\n"
        f"#SBATCH --job-name={job_name}\n"
        f"#SBATCH --partition={partition}\n"
        "#SBATCH --nodes=1\n"
        "#SBATCH --ntasks=1\n"
        f"#SBATCH --cpus-per-task={cpus}\n"
        f"#SBATCH --mem={mem}\n"
        f"#SBATCH --time={wall_time}\n"
        f"#SBATCH --gres=gpu:{gpus}\n"
        f"#SBATCH --chdir={run_root.as_posix()}\n"
        f"#SBATCH --output={stdout_log.as_posix()}\n"
        f"#SBATCH --error={stderr_log.as_posix()}\n\n"
        f"export SERVERTOOL_RUN_ID={shlex.quote(run_root.name)}\n"
        f"export SERVERTOOL_RUN_DIR={shlex.quote(run_root.as_posix())}\n"
        f"export SERVERTOOL_INSTALL_PATH={install_path}\n"
        f"exec {shlex.quote(launch_path.as_posix())}\n"
    )


def _submission_audit_from_env() -> dict[str, object]:
    values: dict[str, object] = {}
    text_keys = {
        "submitted_by": "SERVERTOOL_SUBMITTED_BY",
        "controller_user": "SERVERTOOL_CONTROLLER_USER",
        "controller_host": "SERVERTOOL_CONTROLLER_HOST",
        "controller_platform": "SERVERTOOL_CONTROLLER_PLATFORM",
        "controller_version": "SERVERTOOL_CONTROLLER_VERSION",
        "git_rev": "SERVERTOOL_SOURCE_GIT_REV",
        "spec_sha256": "SERVERTOOL_SPEC_SHA256",
    }
    for key, env_key in text_keys.items():
        value = os.getenv(env_key, "").strip()
        if value:
            values[key] = value
    dirty = os.getenv("SERVERTOOL_SOURCE_GIT_DIRTY", "").strip().lower()
    if dirty:
        values["git_dirty"] = dirty in {"1", "true", "yes", "on"}
    return values


def _run_prepare(args: Namespace, context: AppContext) -> int:
    spec_path = Path(args.target or "spec.json").expanduser()
    try:
        spec = load_spec(spec_path)
        asset_env = prepare_run_assets(context.config, spec, spec_path.parent)
    except (OSError, RuntimeError, json.JSONDecodeError, SpecValidationError) as error:
        context.console.fail(str(error))
        return 1
    runtime_env = _shared_runtime_env(context)

    run_id = args.run_id or build_run_id(spec.run_name, submitted_by=context.config.member_id)
    layout = build_run_layout(PurePosixPath(context.config.runner_root.as_posix()), spec.project, run_id)
    run_dir = _as_local_path(layout.run_root)
    if run_dir.exists():
        context.console.fail(f"Run directory already exists: {run_dir}")
        return 1

    _as_local_path(layout.outputs_dir).mkdir(parents=True, exist_ok=True)
    _as_local_path(layout.ckpts_dir).mkdir(parents=True, exist_ok=True)
    write_spec(_as_local_path(layout.spec_path), spec)

    meta = build_meta(spec, run_id, layout, member_id=context.config.member_id, audit=_submission_audit_from_env())
    created_at = str(meta["created_at"])
    write_json(_as_local_path(layout.meta_path), meta)
    write_json(
        _as_local_path(layout.status_path),
        build_status(
            run_id,
            layout,
            state="prepared",
            message="Run directory prepared",
            created_at=created_at,
            member_id=context.config.member_id,
            assets=spec.assets.to_dict(),
            fetch_include=spec.fetch.include,
        ),
    )
    _write_executable(
        _as_local_path(layout.launch_path),
        _render_launch_script(
            layout.run_root,
            _resolve_workdir(PurePosixPath(asset_env.get("SERVERTOOL_CODE_PATH", layout.run_root.as_posix())), spec.launch.workdir),
            spec.launch.command,
            sys.executable,
            context.config.root.as_posix(),
            asset_env,
            runtime_env,
        ),
    )
    _write_executable(
        _as_local_path(layout.job_path),
        _render_job_script(
            context,
            layout.run_root,
            layout.launch_path,
            layout.stdout_log,
            layout.stderr_log,
            spec.run_name,
            spec.launch.partition,
            spec.launch.gpus,
            spec.launch.cpus,
            spec.launch.mem,
            spec.launch.time,
        ),
    )

    context.console.ok(f"Prepared run: {run_id}")
    context.console.info(f"Run directory: {run_dir}")
    context.console.info(f"Status file: {_as_local_path(layout.status_path)}")
    return 0


def _extract_job_id(text: str) -> str:
    matches = JOB_ID_PATTERN.findall(text)
    return matches[-1] if matches else ""


def _run_start(args: Namespace, context: AppContext) -> int:
    try:
        run_dir = _resolve_run_dir_with_config(context, args.target)
        status_path = run_dir / "status.json"
        job_path = run_dir / "job.sbatch"
        status = read_json(status_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        context.console.fail(str(error))
        return 1

    if not command_exists("sbatch"):
        context.console.fail("sbatch is not available on this node")
        return 1

    result = run_command(["sbatch", str(job_path)])
    output = (result.stdout.strip() or result.stderr.strip()).strip()
    job_id = _extract_job_id(output)
    if result.returncode != 0 or not job_id:
        status["state"] = "failed"
        status["message"] = output or "sbatch submission failed"
        status["updated_at"] = utc_now_text()
        write_json(status_path, status)
        context.console.fail(status["message"])
        return 1

    started_at = utc_now_text()
    status["state"] = "running"
    status["job_id"] = job_id
    status["started_at"] = started_at
    status["updated_at"] = started_at
    status["message"] = f"Submitted to SLURM as job {job_id}"
    write_json(status_path, status)
    context.console.ok(f"Submitted run {run_dir.name} as SLURM job {job_id}")
    return 0


def _resolve_run_dir(runner_root: Path, target: str | None) -> Path:
    if target is None:
        candidate = Path.cwd()
        if (candidate / "status.json").exists():
            return candidate
        raise FileNotFoundError("status.json not found in the current directory")

    candidate = Path(target).expanduser()
    if candidate.exists():
        return candidate if candidate.is_dir() else candidate.parent

    matches = list((runner_root / "projects").glob(f"*/runs/{target}"))
    return _resolve_run_dir_matches(target, matches)


def _resolve_run_dir_with_config(context: AppContext, target: str | None) -> Path:
    if target is None:
        return _resolve_run_dir(context.config.runner_root, target)

    candidate = Path(target).expanduser()
    if candidate.exists():
        return candidate if candidate.is_dir() else candidate.parent

    search_roots = [context.config.runner_root]
    legacy_root = Path(context.config.remote_root).expanduser()
    if legacy_root != context.config.runner_root:
        search_roots.append(legacy_root)

    matches: list[Path] = []
    for root in search_roots:
        matches.extend((root / "projects").glob(f"*/runs/{target}"))
    return _resolve_run_dir_matches(target, matches)


def _resolve_run_dir_matches(target: str | None, matches: list[Path]) -> Path:
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Multiple runs match '{target}'; pass an explicit run path instead")
    raise FileNotFoundError(f"Run not found: {target}")


def _run_status(args: Namespace, context: AppContext) -> int:
    try:
        run_dir = _resolve_run_dir_with_config(context, args.target)
        status = read_json(run_dir / "status.json")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        context.console.fail(str(error))
        return 1
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def _run_tail(args: Namespace, context: AppContext) -> int:
    try:
        run_dir = _resolve_run_dir_with_config(context, args.target)
    except (OSError, ValueError) as error:
        context.console.fail(str(error))
        return 1

    log_path = run_dir / ("stderr.log" if args.stderr else "stdout.log")
    if not log_path.exists():
        context.console.fail(f"Log file not found: {log_path}")
        return 1

    lines = log_path.read_text().splitlines()
    limit = max(args.lines, 1)
    output = lines[-limit:]
    if output:
        print("\n".join(output))
    return 0


def _load_run_artifacts(run_dir: Path):
    spec = load_spec(run_dir / "spec.json")
    meta = read_json(run_dir / "meta.json")
    status_path = run_dir / "status.json"
    status = read_json(status_path)
    return spec, meta, status_path, status


def _deliver_run_notification(
    context: AppContext,
    run_dir: Path,
    spec: object,
    meta: dict[str, object],
    status_path: Path,
    status: dict[str, object],
    *,
    lines: int,
) -> str:
    subject = build_run_notification_subject(
        str(meta.get("project", spec.project)),
        str(status.get("run_id", run_dir.name)),
        str(status.get("state", "")),
    )
    body = build_run_notification_body(
        meta,
        status,
        read_log_tail(run_dir / "stderr.log", lines=max(lines, 1)),
    )
    try:
        send_email(context.config, spec.notify.email.to, subject, body)
    except Exception as error:
        status["notify_error"] = str(error)
        status["updated_at"] = utc_now_text()
        write_json(status_path, status)
        return str(error)

    status["notify_error"] = ""
    status["updated_at"] = utc_now_text()
    write_json(status_path, status)
    return ""


def _run_notify_test(args: Namespace, context: AppContext) -> int:
    recipient = str(args.test or context.config.notify_email_to).strip()
    if not recipient:
        context.console.fail("Pass a recipient to 'servertool runner notify --test' or configure SERVERTOOL_NOTIFY_EMAIL_TO")
        return 1

    try:
        send_test_email(context.config, recipient)
    except Exception as error:
        context.console.fail(str(error))
        return 1

    context.console.ok(f"Sent test email to {recipient}")
    return 0


def _run_notify(args: Namespace, context: AppContext) -> int:
    if args.test is not None:
        return _run_notify_test(args, context)

    try:
        run_dir = _resolve_run_dir_with_config(context, args.target)
        spec, meta, status_path, status = _load_run_artifacts(run_dir)
    except (OSError, ValueError, json.JSONDecodeError, SpecValidationError) as error:
        context.console.fail(str(error))
        return 1

    if not spec.notify.email.enabled:
        context.console.info("Email notifications are disabled for this run")
        return 0

    if not spec.notify.email.to:
        context.console.fail("No email recipients are configured for this run")
        return 1

    state = str(status.get("state", ""))
    if state not in NOTIFIABLE_STATES:
        context.console.fail(f"Run state '{state or '(unknown)'}' is not eligible for email notification")
        return 1

    error = _deliver_run_notification(
        context,
        run_dir,
        spec,
        meta,
        status_path,
        status,
        lines=args.lines,
    )
    if error:
        context.console.fail(error)
        return 1

    context.console.ok(f"Sent notification for run {run_dir.name}")
    return 0


def _run_finalize(args: Namespace, context: AppContext) -> int:
    if args.exit_code is None:
        context.console.fail("runner finalize requires --exit-code")
        return 1

    try:
        run_dir = _resolve_run_dir_with_config(context, args.target)
        spec, meta, status_path, status = _load_run_artifacts(run_dir)
    except (OSError, ValueError, json.JSONDecodeError, SpecValidationError) as error:
        context.console.fail(str(error))
        return 1

    ended_at = utc_now_text()
    exit_code = args.exit_code
    status["state"] = "succeeded" if exit_code == 0 else "failed"
    status["exit_code"] = exit_code
    status["ended_at"] = ended_at
    status["updated_at"] = ended_at
    status["message"] = (
        "Run completed successfully"
        if exit_code == 0
        else f"Run exited with code {exit_code}"
    )
    write_json(status_path, status)

    if spec.notify.email.enabled and status["state"] in NOTIFIABLE_STATES:
        _deliver_run_notification(
            context,
            run_dir,
            spec,
            meta,
            status_path,
            status,
            lines=args.lines,
        )
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode is None:
        context.topic_parsers["runner"].print_help()
        return 0
    if args.mode == "prepare":
        return _run_prepare(args, context)
    if args.mode == "start":
        return _run_start(args, context)
    if args.mode == "status":
        return _run_status(args, context)
    if args.mode == "tail":
        return _run_tail(args, context)
    if args.mode == "notify":
        return _run_notify(args, context)
    if args.mode == "finalize":
        return _run_finalize(args, context)
    context.console.fail(f"Unknown runner subcommand: {args.mode}")
    return 1
