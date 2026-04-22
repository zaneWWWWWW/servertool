from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path
import tempfile

from ..controller import bootstrap as bootstrap_ops
from ..controller import cleanup as cleanup_ops
from ..controller import transport as remote_ops
from ..context import AppContext
from ..shared.system import command_exists, run_command, shlex_join


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "remote",
        help="Check controller-to-runner connectivity",
        description="Verify local transport tools and the remote servertool runner endpoint.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["doctor", "install-runner", "bootstrap", "cleanup"],
        help="Remote action",
    )
    parser.add_argument("target", nargs="?", help="Run id for cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Print planned remote setup commands")
    parser.add_argument("--force", action="store_true", help="Override cleanup safety checks")
    parser.set_defaults(func=run)
    return parser


def _print_check(context: AppContext, ok: bool, label: str, detail: str) -> None:
    if ok:
        context.console.ok(f"{label}: {detail}")
    else:
        context.console.fail(f"{label}: {detail}")


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


def _print_plan(commands: list[tuple[str, list[str]]]) -> None:
    for index, (label, argv) in enumerate(commands, start=1):
        print(f"[{index}] {label}")
        print(f"    {shlex_join(argv)}")


def _run_doctor(context: AppContext) -> int:
    failures = 0
    context.console.header("REMOTE DOCTOR")
    context.console.info(f"Remote host: {context.config.remote_host or '(not set)'}")
    context.console.info(f"Remote user: {context.config.remote_user}")
    context.console.info(f"Remote root: {context.config.remote_root}")
    print("")

    ssh_ok = command_exists(context.config.ssh_bin)
    _print_check(context, ssh_ok, "ssh", context.config.ssh_bin)
    failures += 0 if ssh_ok else 1

    if context.config.rsync_backend == "wsl":
        rsync_launcher_ok = command_exists("wsl")
        _print_check(context, rsync_launcher_ok, "wsl", "Windows WSL launcher")
        failures += 0 if rsync_launcher_ok else 1
    elif context.config.rsync_backend != "native":
        _print_check(context, False, "rsync backend", f"Unsupported backend '{context.config.rsync_backend}'")
        failures += 1

    try:
        rsync_result = run_command(remote_ops.build_rsync_version_command(context.config))
        rsync_ok = rsync_result.returncode == 0
    except OSError:
        rsync_ok = False
    _print_check(context, rsync_ok, "rsync", f"{context.config.rsync_bin} via {context.config.rsync_backend}")
    failures += 0 if rsync_ok else 1

    if not remote_ops.remote_host_configured(context.config):
        _print_check(context, False, "remote host", "Set SERVERTOOL_REMOTE_HOST or run 'servertool config setup'")
        failures += 1
        context.console.footer()
        return 1

    try:
        python_check = remote_ops.run_ssh_command(context.config, [context.config.remote_python, "--version"])
        python_ok = python_check.returncode == 0
        python_detail = python_check.stdout.strip() or python_check.stderr.strip() or context.config.remote_python
    except OSError as error:
        python_ok = False
        python_detail = str(error)
    _print_check(context, python_ok, "remote python", python_detail)
    failures += 0 if python_ok else 1

    try:
        version_check = remote_ops.run_ssh_command(
            context.config,
            remote_ops.servertool_remote_argv(
                context.config,
                ["version"],
                env=remote_ops.remote_servertool_env(context.config),
            ),
        )
        version_ok = version_check.returncode == 0
        version_detail = version_check.stdout.strip() or version_check.stderr.strip() or "servertool"
    except OSError as error:
        version_ok = False
        version_detail = str(error)
    _print_check(context, version_ok, "remote servertool", version_detail)
    failures += 0 if version_ok else 1

    context.console.footer()
    return 0 if failures == 0 else 1

def _run_install_runner(args: Namespace, context: AppContext) -> int:
    if not remote_ops.remote_host_configured(context.config):
        context.console.fail("SERVERTOOL_REMOTE_HOST is not configured")
        return 1

    try:
        paths = bootstrap_ops.bootstrap_paths(context.config)
    except OSError as error:
        context.console.fail(str(error))
        return 1

    commands = bootstrap_ops.build_install_runner_commands(context.config, paths)

    if args.dry_run:
        print(f"Local source: {paths.local_runner_source}")
        print(f"Remote module root: {paths.remote_module_root.as_posix()}")
        print("")
        _print_plan(commands)
        return 0

    for label, argv in commands:
        if _execute_command(context, label, argv) != 0:
            return 1
    return 0


def _run_bootstrap(args: Namespace, context: AppContext) -> int:
    if not remote_ops.remote_host_configured(context.config):
        context.console.fail("SERVERTOOL_REMOTE_HOST is not configured")
        return 1

    try:
        paths = bootstrap_ops.bootstrap_paths(context.config)
    except OSError as error:
        context.console.fail(str(error))
        return 1

    smtp_source = paths.local_smtp_secrets_file if paths.local_smtp_secrets_file.exists() else None
    with tempfile.TemporaryDirectory() as temp_dir:
        runner_config_path = Path(temp_dir) / "config.env"
        runner_config_path.write_text(bootstrap_ops.render_remote_runner_config(context.config, paths))
        commands = bootstrap_ops.build_bootstrap_commands(
            context.config,
            paths,
            runner_config_path,
            smtp_source,
        )

        if args.dry_run:
            print(f"Local source: {paths.local_runner_source}")
            print(f"Remote module root: {paths.remote_module_root.as_posix()}")
            print(f"Remote config file: {paths.remote_config_file.as_posix()}")
            print(
                "Local SMTP secrets: "
                + (str(smtp_source) if smtp_source is not None else "(not found; SMTP sync will be skipped)")
            )
            print(f"Remote SMTP secrets: {paths.remote_smtp_secrets_file.as_posix()}")
            print("")
            _print_plan(commands)
            return 0

        for label, argv in commands:
            if _execute_command(context, label, argv) != 0:
                return 1

    context.console.ok("Remote bootstrap completed")
    if smtp_source is None:
        context.console.warn(
            f"Local SMTP secrets file not found: {paths.local_smtp_secrets_file}. Runner notifications are not configured yet."
        )
    return _run_doctor(context)


def _run_cleanup(args: Namespace, context: AppContext) -> int:
    if not remote_ops.remote_host_configured(context.config):
        context.console.fail("SERVERTOOL_REMOTE_HOST is not configured")
        return 1
    if not args.target:
        context.topic_parsers["remote"].print_help()
        return 0

    try:
        plan = cleanup_ops.build_remote_cleanup_plan(context.config, args.target, force=args.force)
    except ValueError as error:
        context.console.fail(str(error))
        return 1

    if args.dry_run:
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
        _print_plan([(action.label, list(action.command)) for action in plan.actions])
        return 0

    for action in plan.actions:
        if _execute_command(context, action.label, list(action.command)) != 0:
            return 1
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode is None:
        context.topic_parsers["remote"].print_help()
        return 0
    if args.mode == "doctor":
        return _run_doctor(context)
    if args.mode == "install-runner":
        return _run_install_runner(args, context)
    if args.mode == "bootstrap":
        return _run_bootstrap(args, context)
    if args.mode == "cleanup":
        return _run_cleanup(args, context)
    context.console.fail(f"Unknown remote subcommand: {args.mode}")
    return 1
