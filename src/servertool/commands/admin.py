from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction

from ..context import AppContext
from . import remote as remote_command


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "admin",
        help="Manage the shared lab deployment",
        description="Deploy the shared runner, inspect lab configuration, and manage shared admin-side setup.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["deploy", "rollback", "doctor", "show-config"],
        help="Admin action",
    )
    parser.add_argument("target", nargs="?", help="Runner version for rollback")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned admin workflow")
    parser.set_defaults(func=run)
    return parser


def _run_show_config(context: AppContext) -> int:
    config = context.config
    context.console.header("ADMIN CONFIGURATION")
    context.console.info(f"Lab config file: {config.lab_config_file}")
    context.console.info(f"Lab config exists: {'yes' if config.lab_config_exists else 'no'}")
    context.console.info(f"SMTP secrets file: {config.smtp_secrets_file}")
    print("")
    context.console.info(f"Remote lab config file: {config.remote_lab_config_file.as_posix()}")
    context.console.info(f"Remote SMTP secrets file: {config.remote_lab_smtp_secrets_file.as_posix()}")
    context.console.info(f"Runner release: {config.version}")
    context.console.info(f"Runner staged release root: {config.remote_runner_release_root().as_posix()}")
    context.console.info(f"Runner current link: {config.remote_runner_current_root.as_posix()}")
    context.console.info(f"Runner module root: {config.remote_runner_module_root.as_posix()}")
    print("")
    context.console.info(f"Remote host: {config.remote_host or '(not set)'}")
    context.console.info(f"Remote user: {config.remote_user}")
    context.console.info(f"Remote port: {config.remote_port}")
    context.console.info(f"Shared home: {config.shared_home}")
    context.console.info(f"Shared trainhub root: {config.remote_root}")
    context.console.info(f"Runner install root: {config.remote_runner_install_root.as_posix()}")
    context.console.info(f"Runner releases root: {config.remote_runner_releases_root.as_posix()}")
    context.console.info(f"Runner current link: {config.remote_runner_current_root.as_posix()}")
    context.console.info(f"Shared env root: {config.shared_env_root}")
    context.console.info(f"Shared model root: {config.shared_model_root}")
    context.console.info(f"Shared cache root: {config.shared_cache_root}")
    context.console.info(f"A40 partition: {config.a40_partition}")
    context.console.info(f"A6000 partition: {config.a6000_partition}")
    context.console.info(f"Notify email from: {config.notify_email_from or '(not set)'}")
    context.console.info(f"SMTP host: {config.smtp_host}")
    context.console.info(f"SMTP port: {config.smtp_port}")
    context.console.info(f"SMTP use SSL: {'yes' if config.smtp_use_ssl else 'no'}")
    context.console.info(f"PIP index URL: {config.pip_index_url or '(not set)'}")
    context.console.info(f"PIP extra index URL: {config.pip_extra_index_url or '(not set)'}")
    context.console.info(f"Conda channels: {config.conda_channels or '(not set)'}")
    context.console.info(f"HF endpoint: {config.hf_endpoint or '(not set)'}")
    context.console.info(f"ModelScope endpoint: {config.modelscope_endpoint or '(not set)'}")
    context.console.footer()
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode is None:
        context.topic_parsers["admin"].print_help()
        return 0
    if args.mode == "deploy":
        return remote_command.run_bootstrap_lab_command(context, dry_run=args.dry_run)
    if args.mode == "rollback":
        if not args.target:
            context.console.fail("Provide an installed runner version, for example: servertool admin rollback 2.9.0")
            return 1
        return remote_command.run_rollback_runner_command(context, args.target, dry_run=args.dry_run)
    if args.mode == "doctor":
        return remote_command.run_doctor_command(
            context,
            include_admin_checks=True,
            heading="ADMIN DOCTOR",
            rerun_command="servertool admin doctor",
        )
    if args.mode == "show-config":
        return _run_show_config(context)
    context.console.fail(f"Unknown admin subcommand: {args.mode}")
    return 1
