from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction

from ..shared.config import lab_config_path, user_config_path
from ..context import AppContext


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "config",
        help="Show effective configuration",
        description="Show the current servertool lab and user configuration files and their effective values.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["show", "path"],
        default="show",
        help="Configuration action",
    )
    parser.set_defaults(func=run)
    return parser


def _warn_if_suspicious_config(context: AppContext) -> None:
    config = context.config
    if config.a40_partition.isdigit():
        context.console.warn(
            f"A40 partition is set to '{config.a40_partition}'. This looks numeric; SLURM partition names are usually labels like 'A40'."
        )
    if config.a6000_partition.isdigit():
        context.console.warn(
            f"A6000 partition is set to '{config.a6000_partition}'. This looks numeric; SLURM partition names are usually labels like 'A6000'."
        )


def _run_path(context: AppContext) -> int:
    user_path = user_config_path()
    lab_path = lab_config_path()
    smtp_path = context.config.smtp_secrets_file
    print(f"User config: {user_path}")
    print(f"Lab config: {lab_path}")
    print(f"Admin SMTP secrets: {smtp_path}")
    if user_path.exists():
        context.console.info("User config file exists")
    else:
        context.console.warn("User config file does not exist yet")
    if lab_path.exists():
        context.console.info("Lab config file exists")
    else:
        context.console.warn("Lab config file does not exist yet")
    if smtp_path.exists():
        context.console.info("Admin SMTP secrets file exists")
    else:
        context.console.warn("Admin SMTP secrets file does not exist yet")
    return 0


def _run_show(context: AppContext) -> int:
    config = context.config
    context.console.header("CONFIGURATION")
    context.console.info(f"User config file: {config.user_config_file}")
    context.console.info(f"User config exists: {'yes' if config.user_config_exists else 'no'}")
    context.console.info(f"Lab config file: {config.lab_config_file}")
    context.console.info(f"Lab config exists: {'yes' if config.lab_config_exists else 'no'}")
    context.console.info("Config precedence: environment > user config > lab config > built-in defaults")
    print("")
    context.console.section("1", "User Values")
    context.console.info(f"Workspace name: {config.workspace_name}")
    context.console.info(f"Member ID: {config.member_id}")
    context.console.info(f"Default notify email: {config.notify_email_to or '(not set)'}")
    context.console.info(f"Local run cache: {config.local_run_cache}")
    print("")
    context.console.section("2", "Lab Values")
    context.console.info(f"Shared account: {config.shared_account}")
    context.console.info(f"Shared home: {config.shared_home}")
    context.console.info(f"Workspace path: {config.workspace_path}")
    context.console.info(f"Remote host: {config.remote_host or '(not set)'}")
    context.console.info(f"Remote user: {config.remote_user}")
    context.console.info(f"Remote port: {config.remote_port}")
    context.console.info(f"Remote python: {config.remote_python}")
    context.console.info(f"Shared trainhub root: {config.remote_root}")
    context.console.info(f"Member remote state root: {config.remote_member_root}")
    context.console.info(f"Shared env root: {config.shared_env_root}")
    context.console.info(f"Shared model root: {config.shared_model_root}")
    context.console.info(f"Shared cache root: {config.shared_cache_root}")
    context.console.info(f"A40 partition: {config.a40_partition}")
    context.console.info(f"A6000 partition: {config.a6000_partition}")
    context.console.info(f"A40 max time: {config.a40_max_time}")
    context.console.info(f"A6000 max time: {config.a6000_max_time}")
    context.console.info(f"PIP index URL: {config.pip_index_url or '(not set)'}")
    context.console.info(f"PIP extra index URL: {config.pip_extra_index_url or '(not set)'}")
    context.console.info(f"Conda channels: {config.conda_channels or '(not set)'}")
    context.console.info(f"HF endpoint: {config.hf_endpoint or '(not set)'}")
    context.console.info(f"ModelScope endpoint: {config.modelscope_endpoint or '(not set)'}")
    context.console.info(f"Notify email from: {config.notify_email_from or '(not set)'}")
    context.console.info(f"SMTP host: {config.smtp_host}")
    context.console.info(f"SMTP port: {config.smtp_port}")
    context.console.info(f"SMTP use SSL: {'yes' if config.smtp_use_ssl else 'no'}")
    context.console.info(f"SMTP secrets file: {config.smtp_secrets_file}")
    context.console.info(f"SSH binary: {config.ssh_bin}")
    context.console.info(f"Rsync binary: {config.rsync_bin}")
    context.console.info(f"Rsync backend: {config.rsync_backend}")
    print("")
    _warn_if_suspicious_config(context)
    context.console.footer()
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode == "show":
        return _run_show(context)
    if args.mode == "path":
        return _run_path(context)
    context.console.fail(f"Unknown config subcommand: {args.mode}")
    return 1
