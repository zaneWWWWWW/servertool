from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path
import json
import tempfile

from ..controller import cleanup as cleanup_ops
from ..controller import records as record_ops
from ..controller import runs as run_ops
from ..context import AppContext
from ..runner.state import utc_now_text
from ..shared.spec import SpecValidationError
from ..shared.system import print_table, run_command, shlex_join


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "run",
        help="Control training runs",
        description="Submit specs to the shared runner and inspect member-scoped run status.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["submit", "status", "logs", "fetch", "list", "cleanup"],
        help="Run action",
    )
    parser.add_argument("target", nargs="?", help="Spec path for submit, run id for status/logs/fetch/cleanup")
    parser.add_argument("--run-id", help="Use an explicit run id when submitting")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned controller workflow")
    parser.add_argument("--dest", help="Local destination directory for fetched run files")
    parser.add_argument("--lines", type=int, default=50, help="Number of log lines to print")
    parser.add_argument("--stderr", action="store_true", help="Read stderr.log instead of stdout.log")
    parser.add_argument("--follow", action="store_true", help="Poll remote logs and print new output")
    parser.add_argument("--json", action="store_true", help="Print JSON output for supported commands")
    parser.add_argument("--all-members", action="store_true", help="Show local records for all member ids")
    parser.add_argument("--force", action="store_true", help="Override cleanup safety checks")
    parser.add_argument("--local-only", action="store_true", help="Cleanup only local run files")
    parser.add_argument("--remote-only", action="store_true", help="Cleanup only remote run files")
    parser.set_defaults(func=run)
    return parser


def _require_remote_host(context: AppContext) -> bool:
    try:
        run_ops.ensure_remote_host(context.config)
        return True
    except ValueError as error:
        context.console.fail(str(error))
        context.console.info("Run 'servertool init' after the admin has provided the lab config and remote host")
        return False


def _execute_command(context: AppContext, label: str, argv: list[str]) -> int:
    try:
        result = run_command(argv)
    except OSError as error:
        context.console.fail(label)
        context.console.info(str(error))
        return 1
    if result.returncode != 0:
        context.console.fail(label)
        context.console.info(result.stderr.strip() or result.stdout.strip() or shlex_join(argv))
        return 1
    context.console.ok(label)
    return 0


def _require_run_target(args: Namespace, context: AppContext) -> str | None:
    if args.target:
        return args.target
    context.topic_parsers["run"].print_help()
    return None


def _print_plan(commands: list[tuple[str, list[str]]]) -> None:
    for index, (label, argv) in enumerate(commands, start=1):
        print(f"[{index}] {label}")
        print(f"    {shlex_join(argv)}")


def _print_cleanup_plan(plan: cleanup_ops.CleanupPlan) -> None:
    print(f"Run ID: {plan.run_id}")
    if plan.remote_run_root is not None:
        print(f"Remote run path: {plan.remote_run_root.as_posix()}")
        if plan.remote_state_confirmed:
            print(f"Remote state: {plan.remote_state or '(unknown)'}")
    if plan.notes:
        print("")
        for note in plan.notes:
            print(f"Note: {note}")
    print("")
    for index, action in enumerate(plan.actions, start=1):
        print(f"[{index}] {action.label}")
        if action.command:
            print(f"    {shlex_join(list(action.command))}")
        elif action.path is not None:
            print(f"    {action.path}")


def _execute_cleanup_action(context: AppContext, action: cleanup_ops.CleanupAction) -> int:
    if action.command:
        return _execute_command(context, action.label, list(action.command))
    if action.path is None:
        return 0
    try:
        cleanup_ops.delete_local_path(action.path)
    except OSError as error:
        context.console.fail(action.label)
        context.console.info(str(error))
        return 1
    context.console.ok(action.label)
    context.console.info(str(action.path))
    return 0


def _run_submit(args: Namespace, context: AppContext) -> int:
    if not _require_remote_host(context):
        return 1

    spec_path = Path(args.target or "spec.json").expanduser().resolve()
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = run_ops.prepare_submit(context.config, spec_path, args.run_id, Path(temp_dir))
            commands = [(label, list(argv)) for label, argv in plan.commands]
            if args.dry_run:
                print(f"Run ID: {plan.run_id}")
                print(f"Remote run path: {plan.layout.run_root.as_posix()}")
                print("")
                _print_plan(commands)
                return 0
            for label, argv in commands:
                if _execute_command(context, label, argv) != 0:
                    return 1
    except (OSError, ValueError, json.JSONDecodeError, SpecValidationError) as error:
        context.console.fail(str(error))
        return 1

    record_ops.write_run_record(
        context.config,
        plan.run_id,
        spec_path,
        plan.remote_spec,
        plan.layout.run_root,
        plan.audit.to_record(),
    )
    context.console.ok(f"Submitted run: {plan.run_id}")
    context.console.info(f"Remote run path: {plan.layout.run_root.as_posix()}")
    return 0


def _run_status(args: Namespace, context: AppContext) -> int:
    if not _require_remote_host(context):
        return 1
    target = _require_run_target(args, context)
    if target is None:
        return 0

    try:
        status = run_ops.load_remote_status(context.config, target)
    except OSError as error:
        context.console.fail(str(error))
        return 1
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        context.console.fail(str(error))
        return 1
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def _run_logs(args: Namespace, context: AppContext) -> int:
    if not _require_remote_host(context):
        return 1
    target = _require_run_target(args, context)
    if target is None:
        return 0

    try:
        if args.follow:
            return run_ops.follow_remote_logs(
                context.config,
                target,
                max(args.lines, 1),
                args.stderr,
                emit=lambda output: print(output, flush=True),
            )
        output = run_ops.load_remote_log_text(context.config, target, max(args.lines, 1), args.stderr)
    except OSError as error:
        context.console.fail(str(error))
        return 1
    except RuntimeError as error:
        context.console.fail(str(error))
        return 1
    if output:
        print(output)
    return 0


def _run_fetch(args: Namespace, context: AppContext) -> int:
    if not _require_remote_host(context):
        return 1
    target = _require_run_target(args, context)
    if target is None:
        return 0

    try:
        destination_base = Path(args.dest).expanduser() if args.dest else None
        plan = run_ops.build_fetch_plan(context.config, target, destination_base)
    except OSError as error:
        context.console.fail(str(error))
        return 1
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        context.console.fail(str(error))
        return 1

    if args.dry_run:
        print(f"Remote run path: {plan.remote_run_root.as_posix()}")
        print(f"Local destination: {plan.local_run_root}")
        if plan.fetch_include:
            print(f"Fetch include: {', '.join(plan.fetch_include)}")
        print("")
        print(shlex_join(list(plan.command)))
        return 0

    plan.destination_base.mkdir(parents=True, exist_ok=True)
    if _execute_command(context, "Fetch remote run", list(plan.command)) != 0:
        return 1
    record_ops.update_run_record(
        context.config,
        plan.run_id,
        {
            "last_fetched_at": utc_now_text(),
            "local_fetch_path": str(plan.local_run_root),
            "run_id": plan.run_id,
            "remote_run_root": plan.remote_run_root.as_posix(),
        },
    )
    context.console.info(f"Fetched files to: {plan.local_run_root}")
    return 0


def _run_list(args: Namespace, context: AppContext) -> int:
    records = (
        record_ops.iter_all_run_records(context.config)
        if args.all_members
        else record_ops.iter_run_records(context.config)
    )
    if not records:
        if args.json:
            print("[]")
            return 0
        if args.all_members:
            context.console.info("No local run records found")
        else:
            context.console.info(f"No local run records found for member '{context.config.member_id}'")
        return 0

    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0

    rows = []
    for record in records:
        rows.append(
            [
                str(record.get("run_id", "")),
                str(record.get("member_id", "") or "(legacy)"),
                str(record.get("project", "")),
                str(record.get("submitted_at", "")),
                str(record.get("remote_host", "")),
            ]
        )
    print_table(["RUN_ID", "MEMBER", "PROJECT", "SUBMITTED_AT", "REMOTE_HOST"], rows)
    return 0


def _run_cleanup(args: Namespace, context: AppContext) -> int:
    target = _require_run_target(args, context)
    if target is None:
        return 0
    if not args.local_only and not _require_remote_host(context):
        return 1

    try:
        plan = cleanup_ops.build_run_cleanup_plan(
            context.config,
            target,
            force=args.force,
            local_only=args.local_only,
            remote_only=args.remote_only,
        )
    except ValueError as error:
        context.console.fail(str(error))
        return 1

    if args.dry_run:
        _print_cleanup_plan(plan)
        return 0

    for action in plan.actions:
        if _execute_cleanup_action(context, action) != 0:
            return 1
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode is None:
        context.topic_parsers["run"].print_help()
        return 0
    if args.mode == "submit":
        return _run_submit(args, context)
    if args.mode == "status":
        return _run_status(args, context)
    if args.mode == "logs":
        return _run_logs(args, context)
    if args.mode == "fetch":
        return _run_fetch(args, context)
    if args.mode == "list":
        return _run_list(args, context)
    if args.mode == "cleanup":
        return _run_cleanup(args, context)
    context.console.fail(f"Unknown run subcommand: {args.mode}")
    return 1
