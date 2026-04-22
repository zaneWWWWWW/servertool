from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping, Sequence
import os
import smtplib
import ssl

from ..shared.config import Config, load_env_file


SMTP_SECRET_KEYS = {"SERVERTOOL_SMTP_USERNAME", "SERVERTOOL_SMTP_PASSWORD"}


class EmailConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SmtpCredentials:
    username: str
    password: str


def parse_recipient_string(raw_value: str) -> tuple[str, ...]:
    normalized = raw_value.replace(";", ",")
    recipients = [item.strip() for item in normalized.split(",") if item.strip()]
    return tuple(recipients)


def load_smtp_credentials(config: Config) -> SmtpCredentials:
    file_values = load_env_file(config.smtp_secrets_file, lambda key: key in SMTP_SECRET_KEYS)
    username = os.getenv("SERVERTOOL_SMTP_USERNAME", file_values.get("SERVERTOOL_SMTP_USERNAME", ""))
    password = os.getenv("SERVERTOOL_SMTP_PASSWORD", file_values.get("SERVERTOOL_SMTP_PASSWORD", ""))
    if not username or not password:
        raise EmailConfigError(
            f"SMTP credentials are not configured; set SERVERTOOL_SMTP_USERNAME and SERVERTOOL_SMTP_PASSWORD in {config.smtp_secrets_file}"
        )
    return SmtpCredentials(username=username, password=password)


def send_email(config: Config, recipients: Sequence[str], subject: str, body: str) -> None:
    if not config.notify_email_from:
        raise EmailConfigError("SERVERTOOL_NOTIFY_EMAIL_FROM is not configured")
    if not recipients:
        raise EmailConfigError("No email recipients were provided")

    credentials = load_smtp_credentials(config)
    message = EmailMessage()
    message["From"] = config.notify_email_from
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    if config.smtp_use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context) as client:
            client.login(credentials.username, credentials.password)
            client.send_message(message)
        return

    with smtplib.SMTP(config.smtp_host, config.smtp_port) as client:
        client.login(credentials.username, credentials.password)
        client.send_message(message)


def send_test_email(config: Config, recipient: str) -> None:
    send_email(
        config,
        [recipient],
        "[servertool] test email",
        "This is a servertool SMTP test email.\n\nIf you received this message, runner email delivery is configured correctly.\n",
    )


def build_run_notification_subject(project: str, run_id: str, state: str) -> str:
    return f"[servertool] {project} {run_id} {state}"


def build_run_notification_body(
    meta: Mapping[str, Any],
    status: Mapping[str, Any],
    stderr_tail: str,
) -> str:
    paths = status.get("paths") if isinstance(status.get("paths"), dict) else {}
    duration = _duration_text(status.get("started_at"), status.get("ended_at"))
    sections = [
        f"project: {meta.get('project', '')}",
        f"run_id: {status.get('run_id', meta.get('run_id', ''))}",
        f"state: {status.get('state', '')}",
        f"job_id: {status.get('job_id', '') or '(none)'}",
        f"started_at: {status.get('started_at', '') or '(not started)'}",
        f"ended_at: {status.get('ended_at', '') or '(not ended)'}",
        f"duration: {duration}",
        f"remote run path: {paths.get('run_root', '')}",
        f"outputs path: {paths.get('outputs', '')}",
        f"ckpts path: {paths.get('ckpts', '')}",
        "",
        "stderr tail:",
        stderr_tail or "(stderr.log is empty)",
    ]
    return "\n".join(sections).rstrip() + "\n"


def read_log_tail(path: Path, lines: int = 20) -> str:
    if not path.exists():
        return "(stderr.log not found)"
    content = path.read_text().splitlines()
    limit = max(lines, 1)
    return "\n".join(content[-limit:]).strip()


def _duration_text(started_at: object, ended_at: object) -> str:
    start = _parse_utc_text(started_at)
    end = _parse_utc_text(ended_at)
    if start is None or end is None:
        return "(unavailable)"
    delta = end - start
    if delta.total_seconds() < 0:
        return "(unavailable)"
    return str(delta)


def _parse_utc_text(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
