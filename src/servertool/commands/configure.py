from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path
import os
import shlex

from ..shared.config import local_config_path
from ..context import AppContext


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "config",
        help="Local account configuration",
        description="Show or update the local servertool configuration for the current shared account.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["setup", "show", "path"],
        default="show",
        help="Configuration action",
    )
    parser.set_defaults(func=run)
    return parser


def _prompt(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def _prompt_partition(label: str, default: str, gpu_label: str) -> str:
    while True:
        value = _prompt(label, default)
        if value.isdigit():
            print(
                f"[WARN] '{value}' looks like a GPU count or node count, not a SLURM partition name."
            )
            print(f"[WARN] Enter the partition name for {gpu_label}, for example '{default}'.")
            continue
        return value


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
    if config.auth_url == "https://auth.example.com":
        context.console.warn("Authentication URL is still the public placeholder value")
    if config.network_probe_url == "https://example.com":
        context.console.warn("Network probe URL is still the public placeholder value")


def _suggest_shared_account(context: AppContext) -> str:
    current = context.config.shared_account
    if current != "clusteruser":
        return current
    return os.getenv("USER", current)


def _suggest_shared_home(context: AppContext, shared_account: str) -> str:
    current = str(context.config.shared_home)
    default_cluster_home = f"/cluster/home/{context.config.shared_account}"
    if current == default_cluster_home:
        return f"/share/home/{shared_account}"
    return current


def _write_local_config(config_path: Path, values: list[tuple[str, str]]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Local servertool configuration for this shared account.",
        "# This file is loaded automatically by servertool.",
        "# Do not store passwords or SSH private keys here.",
        "",
    ]
    for key, value in values:
        lines.append(f"export {key}={shlex.quote(value)}")
    config_path.write_text("\n".join(lines) + "\n")


def _run_path(context: AppContext) -> int:
    path = local_config_path()
    print(path)
    if path.exists():
        context.console.info("Local config file exists")
    else:
        context.console.warn("Local config file does not exist yet")
    return 0


def _run_show(context: AppContext) -> int:
    config = context.config
    path = local_config_path()
    context.console.header("LOCAL CONFIGURATION")
    context.console.info(f"Config file: {path}")
    context.console.info(f"Config file exists: {'yes' if path.exists() else 'no'}")
    print("")
    context.console.info(f"Shared account: {config.shared_account}")
    context.console.info(f"Workspace name: {config.workspace_name}")
    context.console.info(f"Shared home: {config.shared_home}")
    context.console.info(f"Workspace path: {config.workspace_path}")
    context.console.info(f"A40 partition: {config.a40_partition}")
    context.console.info(f"A6000 partition: {config.a6000_partition}")
    context.console.info(f"A40 max time: {config.a40_max_time}")
    context.console.info(f"A6000 max time: {config.a6000_max_time}")
    context.console.info(f"Auth URL: {config.auth_url}")
    context.console.info(f"Network probe URL: {config.network_probe_url}")
    context.console.info(f"Default compute host: {config.default_compute_host}")
    context.console.info(f"Quota limit: {config.quota_limit}")
    context.console.info(f"Remote root: {config.remote_root}")
    context.console.info(f"Runner root: {config.runner_root}")
    context.console.info(f"Local run cache: {config.local_run_cache}")
    context.console.info(f"Remote host: {config.remote_host or '(not set)'}")
    context.console.info(f"Remote user: {config.remote_user}")
    context.console.info(f"Remote port: {config.remote_port}")
    context.console.info(f"Remote python: {config.remote_python}")
    context.console.info(f"SSH binary: {config.ssh_bin}")
    context.console.info(f"Rsync binary: {config.rsync_bin}")
    context.console.info(f"Rsync backend: {config.rsync_backend}")
    context.console.info(f"Notify email from: {config.notify_email_from or '(not set)'}")
    context.console.info(
        f"Default notify email: {config.notify_email_to or '(not set)'}"
    )
    context.console.info(f"SMTP host: {config.smtp_host}")
    context.console.info(f"SMTP port: {config.smtp_port}")
    context.console.info(f"SMTP use SSL: {'yes' if config.smtp_use_ssl else 'no'}")
    context.console.info(f"SMTP secrets file: {config.smtp_secrets_file}")
    print("")
    _warn_if_suspicious_config(context)
    context.console.warn("Passwords and SSH keys are intentionally not stored by servertool")
    context.console.footer()
    return 0


def _run_setup(context: AppContext) -> int:
    path = local_config_path()
    config = context.config
    context.console.header("ACCOUNT CONFIG SETUP")
    context.console.info(f"This will write local settings to: {path}")
    context.console.warn("Do not store passwords or SSH keys in this file")
    print("")

    shared_account = _prompt("Shared account", _suggest_shared_account(context))
    workspace_name = _prompt("Workspace folder name", config.workspace_name)
    shared_home = _prompt("Shared home path", _suggest_shared_home(context, shared_account))
    a40_partition = _prompt_partition("A40 partition name", config.a40_partition, "A40 GPUs")
    a6000_partition = _prompt_partition("A6000 partition name", config.a6000_partition, "A6000 GPUs")
    a40_max_time = _prompt("A40 max wall time", config.a40_max_time)
    a6000_max_time = _prompt("A6000 max wall time", config.a6000_max_time)
    auth_url = _prompt("Authentication URL", config.auth_url)
    network_probe_url = _prompt("Network probe URL", config.network_probe_url)
    default_compute_host = _prompt("Default compute host", config.default_compute_host)
    quota_limit = _prompt("Quota limit", config.quota_limit)
    remote_root = _prompt("Remote trainhub root", config.remote_root)
    runner_root = _prompt("Runner local root", str(config.runner_root))
    local_run_cache = _prompt("Local run cache", str(config.local_run_cache))
    remote_host = _prompt("Remote host", config.remote_host)
    remote_user = _prompt("Remote user", config.remote_user)
    remote_port = _prompt("Remote SSH port", config.remote_port)
    remote_python = _prompt("Remote python", config.remote_python)
    ssh_bin = _prompt("SSH binary", config.ssh_bin)
    rsync_bin = _prompt("Rsync binary", config.rsync_bin)
    rsync_backend = _prompt("Rsync backend", config.rsync_backend)
    notify_email_from = _prompt("Notify email from", config.notify_email_from)
    notify_email_to = _prompt("Default notify email", config.notify_email_to)
    smtp_host = _prompt("SMTP host", config.smtp_host)
    smtp_port = _prompt("SMTP port", str(config.smtp_port))
    smtp_use_ssl = _prompt("SMTP use SSL (1/0)", "1" if config.smtp_use_ssl else "0")
    smtp_secrets_file = _prompt("SMTP secrets file", str(config.smtp_secrets_file))

    values = [
        ("SERVERTOOL_SHARED_ACCOUNT", shared_account),
        ("SERVERTOOL_WORKSPACE_NAME", workspace_name),
        ("SERVERTOOL_SHARED_HOME", shared_home),
        ("SERVERTOOL_A40_PARTITION", a40_partition),
        ("SERVERTOOL_A6000_PARTITION", a6000_partition),
        ("SERVERTOOL_A40_MAX_TIME", a40_max_time),
        ("SERVERTOOL_A6000_MAX_TIME", a6000_max_time),
        ("SERVERTOOL_AUTH_URL", auth_url),
        ("SERVERTOOL_NETWORK_PROBE_URL", network_probe_url),
        ("SERVERTOOL_DEFAULT_COMPUTE_HOST", default_compute_host),
        ("SERVERTOOL_QUOTA_LIMIT", quota_limit),
        ("SERVERTOOL_REMOTE_ROOT", remote_root),
        ("SERVERTOOL_RUNNER_ROOT", runner_root),
        ("SERVERTOOL_LOCAL_RUN_CACHE", local_run_cache),
        ("SERVERTOOL_REMOTE_HOST", remote_host),
        ("SERVERTOOL_REMOTE_USER", remote_user),
        ("SERVERTOOL_REMOTE_PORT", remote_port),
        ("SERVERTOOL_REMOTE_PYTHON", remote_python),
        ("SERVERTOOL_SSH_BIN", ssh_bin),
        ("SERVERTOOL_RSYNC_BIN", rsync_bin),
        ("SERVERTOOL_RSYNC_BACKEND", rsync_backend),
        ("SERVERTOOL_NOTIFY_EMAIL_FROM", notify_email_from),
        ("SERVERTOOL_NOTIFY_EMAIL_TO", notify_email_to),
        ("SERVERTOOL_SMTP_HOST", smtp_host),
        ("SERVERTOOL_SMTP_PORT", smtp_port),
        ("SERVERTOOL_SMTP_USE_SSL", smtp_use_ssl),
        ("SERVERTOOL_SMTP_SECRETS_FILE", smtp_secrets_file),
    ]
    _write_local_config(path, values)

    print("")
    context.console.ok(f"Saved local config to {path}")
    context.console.info("Future servertool commands will load this file automatically")
    context.console.info(f"Workspace path will resolve to: {Path(shared_home) / workspace_name}")
    print("")
    context.console.footer()
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode == "setup":
        return _run_setup(context)
    if args.mode == "show":
        return _run_show(context)
    if args.mode == "path":
        return _run_path(context)
    context.console.fail(f"Unknown config subcommand: {args.mode}")
    return 1
