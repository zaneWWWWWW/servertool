from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path, PurePosixPath
import json
import re
import shlex
import sys

from ..context import AppContext
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


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "runner",
        help="Manage runner-side run state",
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
) -> str:
    return (
        "#!/bin/sh\n"
        "set -eu\n\n"
        f"RUN_DIR={shlex.quote(layout.as_posix())}\n"
        f"WORKDIR={shlex.quote(workdir)}\n"
        f"RUNNER_PYTHON={shlex.quote(runner_python)}\n"
        f"RUNNER_MODULE_ROOT={shlex.quote(runner_module_root)}\n"
        "mkdir -p \"$RUN_DIR/outputs\" \"$RUN_DIR/ckpts\"\n"
        "cd \"$WORKDIR\"\n"
        "set +e\n"
        f"{command}\n"
        "EXIT_CODE=$?\n"
        "set -e\n"
        "env PYTHONPATH=\"$RUNNER_MODULE_ROOT\" \"$RUNNER_PYTHON\" -m servertool runner finalize \"$RUN_DIR\" --exit-code \"$EXIT_CODE\" || true\n"
        "exit \"$EXIT_CODE\"\n"
    )


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


def _run_prepare(args: Namespace, context: AppContext) -> int:
    spec_path = Path(args.target or "spec.json").expanduser()
    try:
        spec = load_spec(spec_path)
    except (OSError, json.JSONDecodeError, SpecValidationError) as error:
        context.console.fail(str(error))
        return 1

    run_id = args.run_id or build_run_id(spec.run_name)
    layout = build_run_layout(PurePosixPath(context.config.runner_root.as_posix()), spec.project, run_id)
    run_dir = _as_local_path(layout.run_root)
    if run_dir.exists():
        context.console.fail(f"Run directory already exists: {run_dir}")
        return 1

    _as_local_path(layout.outputs_dir).mkdir(parents=True, exist_ok=True)
    _as_local_path(layout.ckpts_dir).mkdir(parents=True, exist_ok=True)
    write_spec(_as_local_path(layout.spec_path), spec)

    created_at = build_meta(spec, run_id, layout)["created_at"]
    write_json(_as_local_path(layout.meta_path), build_meta(spec, run_id, layout, created_at=created_at))
    write_json(
        _as_local_path(layout.status_path),
        build_status(
            run_id,
            layout,
            state="prepared",
            message="Run directory prepared",
            created_at=created_at,
        ),
    )
    _write_executable(
        _as_local_path(layout.launch_path),
        _render_launch_script(
            layout.run_root,
            _resolve_workdir(layout.run_root, spec.launch.workdir),
            spec.launch.command,
            sys.executable,
            context.config.root.as_posix(),
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
        run_dir = _resolve_run_dir(context.config.runner_root, args.target)
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
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"Multiple runs match '{target}'; pass an explicit run path instead")
    raise FileNotFoundError(f"Run not found: {target}")


def _run_status(args: Namespace, context: AppContext) -> int:
    try:
        run_dir = _resolve_run_dir(context.config.runner_root, args.target)
        status = read_json(run_dir / "status.json")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        context.console.fail(str(error))
        return 1
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def _run_tail(args: Namespace, context: AppContext) -> int:
    try:
        run_dir = _resolve_run_dir(context.config.runner_root, args.target)
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
        run_dir = _resolve_run_dir(context.config.runner_root, args.target)
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
        run_dir = _resolve_run_dir(context.config.runner_root, args.target)
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
