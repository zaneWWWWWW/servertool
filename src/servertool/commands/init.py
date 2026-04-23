from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path

from ..shared.config import Config, render_env_file, user_config_path
from ..context import AppContext
from . import remote as remote_command


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "init",
        help="Create your user config and member state",
        description="Create or update the local user config and initialize your remote member-scoped servertool state.",
    )
    parser.add_argument("--workspace-name", help="Workspace folder name under the shared account")
    parser.add_argument("--member-id", help="Stable member identity; defaults to the workspace name")
    parser.add_argument("--notify-email", help="Default notification email for your runs")
    parser.add_argument("--local-run-cache", help="Local cache directory for run records and fetched runs")
    parser.add_argument("--skip-remote", action="store_true", help="Only write the local user config")
    parser.set_defaults(func=run)
    return parser


def _prompt(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def _write_user_config(path: Path, values: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_env_file(
            values,
            comments=(
                "# Personal servertool configuration.",
                "# This file only stores user-scoped overrides.",
                "# Lab-managed defaults should stay in lab.env.",
            ),
        )
    )


def _collect_values(args: Namespace, context: AppContext) -> list[tuple[str, str]]:
    config = context.config
    workspace_name = args.workspace_name or _prompt("Workspace name", config.workspace_name)
    member_default = config.member_id
    if member_default == config.workspace_name and workspace_name != config.workspace_name:
        member_default = workspace_name
    member_id = args.member_id or _prompt("Member ID", member_default)
    notify_email = args.notify_email or _prompt("Default notify email", config.notify_email_to)
    local_run_cache = args.local_run_cache or _prompt("Local run cache", str(config.local_run_cache))
    return [
        ("SERVERTOOL_WORKSPACE_NAME", workspace_name),
        ("SERVERTOOL_MEMBER_ID", member_id),
        ("SERVERTOOL_NOTIFY_EMAIL_TO", notify_email),
        ("SERVERTOOL_LOCAL_RUN_CACHE", local_run_cache),
    ]


def run(args: Namespace, context: AppContext) -> int:
    path = user_config_path()
    context.console.header("USER INIT")
    context.console.info(f"This will write your user config to: {path}")
    context.console.info("Only user-scoped fields are stored here; lab defaults stay in lab.env")
    print("")

    values = _collect_values(args, context)
    _write_user_config(path, values)
    context.console.ok(f"Saved user config to {path}")

    updated_config = Config.from_root(context.config.root)
    updated_context = AppContext(
        config=updated_config,
        console=context.console,
        topic_parsers=context.topic_parsers,
    )

    if args.skip_remote:
        context.console.info("Skipped remote member initialization")
        context.console.footer()
        return 0

    if not updated_config.remote_host.strip():
        context.console.warn("Remote host is not configured yet, so member initialization was skipped")
        context.console.info("Ask the admin for the lab config, then rerun 'servertool init'.")
        context.console.footer()
        return 0

    print("")
    exit_code = remote_command.run_init_member_command(updated_context)
    if exit_code == 0:
        return 0
    return exit_code
