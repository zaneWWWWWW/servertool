from __future__ import annotations

from argparse import SUPPRESS, ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path
import tempfile

from ..controller import bootstrap as bootstrap_ops
from ..controller import cleanup as cleanup_ops
from ..controller import transport as remote_ops
from ..context import AppContext
from ..shared.system import command_exists, run_command, shlex_join


REMOTE_PATH_CHECK = (
    "from pathlib import Path; import sys; "
    "path = Path(sys.argv[1]).expanduser(); "
    "kind = sys.argv[2]; "
    "exists = path.is_dir() if kind == 'dir' else path.is_file(); "
    "print(path.as_posix() if exists else f'missing {kind}: {path.as_posix()}'); "
    "raise SystemExit(0 if exists else 1)"
)

REMOTE_WHICH_CHECK = (
    "import shutil, sys; "
    "target = sys.argv[1]; "
    "value = shutil.which(target) or ''; "
    "print(value or f'missing command: {target}'); "
    "raise SystemExit(0 if value else 1)"
)


def register(subparsers: _SubParsersAction[ArgumentParser], *, hidden: bool = False) -> ArgumentParser:
    parser = subparsers.add_parser(
        "remote",
        help=SUPPRESS if hidden else "Manage shared remote runner setup",
        description="Verify connectivity, manage versioned shared runner releases, and initialize member-scoped remote config.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["doctor", "install-runner", "rollback-runner", "bootstrap", "bootstrap-lab", "init-member", "cleanup"],
        help="Remote action",
    )
    parser.add_argument("target", nargs="?", help="Run id for cleanup or runner version for rollback")
    parser.add_argument("--dry-run", action="store_true", help="Print planned remote setup commands")
    parser.add_argument("--force", action="store_true", help="Override cleanup safety checks")
    parser.set_defaults(func=run)
    return parser


def _print_check(context: AppContext, ok: bool, label: str, detail: str) -> None:
    if ok:
        context.console.ok(f"{label}: {detail}")
    else:
        context.console.fail(f"{label}: {detail}")


def _print_warning(context: AppContext, label: str, detail: str) -> None:
    context.console.warn(f"{label}: {detail}")


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


def _remote_probe(context: AppContext, argv: list[str]) -> tuple[bool, str]:
    try:
        result = remote_ops.run_ssh_command(context.config, argv)
    except OSError as error:
        return False, str(error)
    detail = result.stdout.strip() or result.stderr.strip() or shlex_join(argv)
    return result.returncode == 0, detail


def _remote_path_probe(context: AppContext, path: str, kind: str) -> tuple[bool, str]:
    return _remote_probe(context, [context.config.remote_python, "-c", REMOTE_PATH_CHECK, path, kind])


def _run_doctor(
    context: AppContext,
    *,
    include_admin_checks: bool,
    heading: str,
    rerun_command: str,
) -> int:
    failures = 0
    warnings = 0
    context.console.header(heading)
    context.console.info(f"Remote host: {context.config.remote_host or '(not set)'}")
    context.console.info(f"Remote user: {context.config.remote_user}")
    context.console.info(f"Shared trainhub root: {context.config.remote_root}")
    context.console.info(f"Member state root: {context.config.remote_member_root}")
    context.console.info(
        f"User config: {context.config.user_config_file} ({'found' if context.config.user_config_exists else 'not found'})"
    )
    context.console.info(
        f"Lab config: {context.config.lab_config_file} ({'found' if context.config.lab_config_exists else 'not found'})"
    )
    print("")

    context.console.section("1", "Local Controller Checks")

    try:
        paths = bootstrap_ops.bootstrap_paths(context.config)
        runner_source_ok = True
        runner_source_detail = str(paths.local_runner_source)
    except OSError as error:
        paths = None
        runner_source_ok = False
        runner_source_detail = str(error)
    _print_check(context, runner_source_ok, "local runner source", runner_source_detail)
    failures += 0 if runner_source_ok else 1

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

    if include_admin_checks:
        notify_from = context.config.notify_email_from.strip()
        if notify_from:
            context.console.ok(f"notify email from: {notify_from}")
        else:
            _print_warning(
                context,
                "notify email from",
                "SERVERTOOL_NOTIFY_EMAIL_FROM is not configured; runner email defaults will stay disabled",
            )
            warnings += 1

        smtp_local_exists = context.config.smtp_secrets_file.exists()
        if smtp_local_exists:
            context.console.ok(f"local smtp secrets: {context.config.smtp_secrets_file}")
        else:
            _print_warning(
                context,
                "local smtp secrets",
                f"Not found: {context.config.smtp_secrets_file}. Admin deploy will skip SMTP sync.",
            )
            warnings += 1
    else:
        notify_to = context.config.notify_email_to.strip()
        if notify_to:
            context.console.ok(f"default notify email: {notify_to}")
        else:
            _print_warning(
                context,
                "default notify email",
                "SERVERTOOL_NOTIFY_EMAIL_TO is not configured; email notifications will stay disabled for your runs by default",
            )
            warnings += 1

    print("")

    if not remote_ops.remote_host_configured(context.config):
        _print_check(context, False, "remote host", "Set SERVERTOOL_REMOTE_HOST or install the lab config first")
        failures += 1
        print("")
        context.console.fail(f"Servertool preflight found {failures} blocking issue(s)")
        context.console.info(f"Configure the remote endpoint, then rerun '{rerun_command}'.")
        context.console.footer()
        return 1
    
    if paths is None:
        print("")
        context.console.fail(f"Servertool preflight found {failures} blocking issue(s)")
        context.console.info(f"Fix the local controller issues above, then rerun '{rerun_command}'.")
        context.console.footer()
        return 1

    context.console.section("2", "Remote Runner Checks")

    python_ok, python_detail = _remote_probe(context, [context.config.remote_python, "--version"])
    _print_check(context, python_ok, "remote python", python_detail)
    failures += 0 if python_ok else 1

    remote_lab_root_ok, remote_lab_root_detail = _remote_path_probe(context, context.config.remote_root, "dir")
    _print_check(context, remote_lab_root_ok, "shared trainhub root", remote_lab_root_detail)
    failures += 0 if remote_lab_root_ok else 1

    remote_member_root_ok, remote_member_root_detail = _remote_path_probe(context, context.config.remote_member_root, "dir")
    _print_check(context, remote_member_root_ok, "member state root", remote_member_root_detail)
    failures += 0 if remote_member_root_ok else 1

    runner_root_ok, runner_root_detail = _remote_path_probe(context, paths.remote_module_root.as_posix(), "dir")
    if runner_root_ok:
        _print_check(context, True, "remote runner module", runner_root_detail)
    else:
        legacy_runner_ok, legacy_runner_detail = _remote_path_probe(
            context,
            context.config.remote_runner_install_root.as_posix(),
            "dir",
        )
        if legacy_runner_ok:
            _print_warning(
                context,
                "remote runner module",
                "missing versioned current release; using legacy install root "
                + legacy_runner_detail
                + ". Run 'servertool remote install-runner' to stage a versioned release.",
            )
            warnings += 1
        else:
            _print_check(context, False, "remote runner module", runner_root_detail)
            failures += 1

    remote_lab_config_ok, remote_lab_config_detail = _remote_path_probe(context, paths.remote_lab_config_file.as_posix(), "file")
    _print_check(context, remote_lab_config_ok, "remote lab config", remote_lab_config_detail)
    failures += 0 if remote_lab_config_ok else 1

    remote_member_config_ok, remote_member_config_detail = _remote_path_probe(
        context,
        paths.remote_member_config_file.as_posix(),
        "file",
    )
    _print_check(context, remote_member_config_ok, "remote member config", remote_member_config_detail)
    failures += 0 if remote_member_config_ok else 1

    sbatch_ok, sbatch_detail = _remote_probe(context, [context.config.remote_python, "-c", REMOTE_WHICH_CHECK, "sbatch"])
    _print_check(context, sbatch_ok, "remote sbatch", sbatch_detail)
    failures += 0 if sbatch_ok else 1

    version_ok, version_detail = _remote_probe(
        context,
        remote_ops.servertool_remote_argv(
            context.config,
            ["version"],
            env=remote_ops.remote_servertool_env(context.config),
        ),
    )
    _print_check(context, version_ok, "remote servertool", version_detail)
    failures += 0 if version_ok else 1

    if include_admin_checks:
        shared_env_ok, shared_env_detail = _remote_path_probe(context, context.config.shared_env_root, "dir")
        _print_check(context, shared_env_ok, "shared env root", shared_env_detail)
        failures += 0 if shared_env_ok else 1

        shared_model_ok, shared_model_detail = _remote_path_probe(context, context.config.shared_model_root, "dir")
        _print_check(context, shared_model_ok, "shared model root", shared_model_detail)
        failures += 0 if shared_model_ok else 1

        shared_cache_ok, shared_cache_detail = _remote_path_probe(context, context.config.shared_cache_root, "dir")
        _print_check(context, shared_cache_ok, "shared cache root", shared_cache_detail)
        failures += 0 if shared_cache_ok else 1

        remote_smtp_ok, remote_smtp_detail = _remote_path_probe(context, paths.remote_smtp_secrets_file.as_posix(), "file")
        if remote_smtp_ok:
            context.console.ok(f"runner smtp secrets: {remote_smtp_detail}")
        else:
            _print_warning(
                context,
                "runner smtp secrets",
                f"{remote_smtp_detail}. Runner email delivery will stay disabled until admin deploy uploads smtp.env.",
            )
            warnings += 1

    print("")
    if failures == 0:
        if warnings == 0:
            context.console.ok("Servertool preflight passed")
        else:
            context.console.warn(f"Servertool preflight passed with {warnings} warning(s)")
            if include_admin_checks:
                context.console.info("Warnings above mainly affect shared notifications or lab defaults.")
            else:
                context.console.info("Warnings above mainly affect your personal defaults or notifications.")
    else:
        context.console.fail(f"Servertool preflight found {failures} blocking issue(s)")
        context.console.info(f"Fix the blocking issues above, then rerun '{rerun_command}'.")

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
        print(f"Runner release: {paths.runner_release}")
        print(f"Remote release root: {paths.remote_runner_release_root.as_posix()}")
        print(f"Remote current link: {paths.remote_runner_current_root.as_posix()}")
        print(f"Remote module root: {paths.remote_module_root.as_posix()}")
        print("")
        _print_plan(commands)
        return 0

    for label, argv in commands:
        if _execute_command(context, label, argv) != 0:
            return 1
    context.console.ok(f"Remote runner release {paths.runner_release} installed")
    return 0


def _run_rollback_runner(args: Namespace, context: AppContext) -> int:
    if not remote_ops.remote_host_configured(context.config):
        context.console.fail("SERVERTOOL_REMOTE_HOST is not configured")
        return 1
    if not args.target:
        context.console.fail("Provide an installed runner version, for example: servertool admin rollback 2.9.0")
        return 1

    release_root = context.config.remote_runner_release_root(args.target)
    commands = bootstrap_ops.build_rollback_runner_commands(context.config, args.target)

    if args.dry_run:
        print(f"Runner release: {args.target}")
        print(f"Remote release root: {release_root.as_posix()}")
        print(f"Remote current link: {context.config.remote_runner_current_root.as_posix()}")
        print("")
        _print_plan(commands)
        return 0

    for label, argv in commands:
        if _execute_command(context, label, argv) != 0:
            return 1
    context.console.ok(f"Remote runner now uses release {args.target}")
    return 0


def _run_bootstrap_lab(args: Namespace, context: AppContext) -> int:
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
        lab_config_path = Path(temp_dir) / "lab.env"
        lab_config_path.write_text(bootstrap_ops.render_remote_lab_config(context.config, paths))
        commands = bootstrap_ops.build_lab_bootstrap_commands(
            context.config,
            paths,
            lab_config_path,
            smtp_source,
        )

        if args.dry_run:
            print(f"Local source: {paths.local_runner_source}")
            print(f"Runner release: {paths.runner_release}")
            print(f"Remote release root: {paths.remote_runner_release_root.as_posix()}")
            print(f"Remote current link: {paths.remote_runner_current_root.as_posix()}")
            print(f"Remote module root: {paths.remote_module_root.as_posix()}")
            print(f"Remote lab config file: {paths.remote_lab_config_file.as_posix()}")
            print(f"Shared env root: {context.config.shared_env_root}")
            print(f"Shared model root: {context.config.shared_model_root}")
            print(f"Shared cache root: {context.config.shared_cache_root}")
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

    context.console.ok("Remote lab bootstrap completed")
    if smtp_source is None:
        context.console.warn(
            f"Local SMTP secrets file not found: {paths.local_smtp_secrets_file}. Runner notifications are not configured yet."
        )
    context.console.info("Next step: ask each member to run 'servertool init' from their controller machine")
    return 0


def _run_init_member(args: Namespace, context: AppContext) -> int:
    if not remote_ops.remote_host_configured(context.config):
        context.console.fail("SERVERTOOL_REMOTE_HOST is not configured")
        return 1

    try:
        paths = bootstrap_ops.bootstrap_paths(context.config)
    except OSError as error:
        context.console.fail(str(error))
        return 1

    with tempfile.TemporaryDirectory() as temp_dir:
        member_config_path = Path(temp_dir) / "member-config.env"
        member_config_path.write_text(bootstrap_ops.render_remote_member_config(context.config, paths))
        commands = bootstrap_ops.build_member_bootstrap_commands(
            context.config,
            paths,
            member_config_path,
        )

        if args.dry_run:
            print(f"Local source: {paths.local_runner_source}")
            print(f"Remote module root: {paths.remote_module_root.as_posix()}")
            print(f"Remote member root: {paths.remote_member_root.as_posix()}")
            print(f"Remote member config file: {paths.remote_member_config_file.as_posix()}")
            print("")
            _print_plan(commands)
            return 0

        for label, argv in commands:
            if _execute_command(context, label, argv) != 0:
                return 1

    context.console.ok("Remote member initialization completed")
    return run_doctor_command(
        context,
        include_admin_checks=False,
        heading="DOCTOR",
        rerun_command="servertool doctor",
    )


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
        lab_config_path = Path(temp_dir) / "lab.env"
        member_config_path = Path(temp_dir) / "member-config.env"
        lab_config_path.write_text(bootstrap_ops.render_remote_lab_config(context.config, paths))
        member_config_path.write_text(bootstrap_ops.render_remote_member_config(context.config, paths))
        commands = bootstrap_ops.build_bootstrap_commands(
            context.config,
            paths,
            lab_config_path,
            member_config_path,
            smtp_source,
        )

        if args.dry_run:
            print(f"Local source: {paths.local_runner_source}")
            print(f"Runner release: {paths.runner_release}")
            print(f"Remote release root: {paths.remote_runner_release_root.as_posix()}")
            print(f"Remote current link: {paths.remote_runner_current_root.as_posix()}")
            print(f"Remote module root: {paths.remote_module_root.as_posix()}")
            print(f"Remote lab config file: {paths.remote_lab_config_file.as_posix()}")
            print(f"Remote member root: {paths.remote_member_root.as_posix()}")
            print(f"Remote member config file: {paths.remote_member_config_file.as_posix()}")
            print(f"Shared env root: {context.config.shared_env_root}")
            print(f"Shared model root: {context.config.shared_model_root}")
            print(f"Shared cache root: {context.config.shared_cache_root}")
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
    return run_doctor_command(
        context,
        include_admin_checks=True,
        heading="REMOTE DOCTOR",
        rerun_command="servertool remote doctor",
    )


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


def run_doctor_command(
    context: AppContext,
    *,
    include_admin_checks: bool,
    heading: str,
    rerun_command: str,
) -> int:
    return _run_doctor(
        context,
        include_admin_checks=include_admin_checks,
        heading=heading,
        rerun_command=rerun_command,
    )


def run_install_runner_command(context: AppContext, *, dry_run: bool = False) -> int:
    return _run_install_runner(Namespace(dry_run=dry_run), context)


def run_rollback_runner_command(context: AppContext, release: str, *, dry_run: bool = False) -> int:
    return _run_rollback_runner(Namespace(target=release, dry_run=dry_run), context)


def run_bootstrap_lab_command(context: AppContext, *, dry_run: bool = False) -> int:
    return _run_bootstrap_lab(Namespace(dry_run=dry_run), context)


def run_init_member_command(context: AppContext, *, dry_run: bool = False) -> int:
    return _run_init_member(Namespace(dry_run=dry_run), context)


def run(args: Namespace, context: AppContext) -> int:
    if args.mode is None:
        context.topic_parsers["remote"].print_help()
        return 0
    if args.mode == "doctor":
        return run_doctor_command(
            context,
            include_admin_checks=True,
            heading="REMOTE DOCTOR",
            rerun_command="servertool remote doctor",
        )
    if args.mode == "install-runner":
        return _run_install_runner(args, context)
    if args.mode == "rollback-runner":
        return _run_rollback_runner(args, context)
    if args.mode == "bootstrap":
        return _run_bootstrap(args, context)
    if args.mode == "bootstrap-lab":
        return _run_bootstrap_lab(args, context)
    if args.mode == "init-member":
        return _run_init_member(args, context)
    if args.mode == "cleanup":
        return _run_cleanup(args, context)
    context.console.fail(f"Unknown remote subcommand: {args.mode}")
    return 1
