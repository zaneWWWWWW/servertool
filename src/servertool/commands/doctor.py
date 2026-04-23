from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction

from ..context import AppContext
from . import remote as remote_command


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "doctor",
        help="Run member preflight checks",
        description="Check your local setup, lab config, shared runner access, and member-scoped remote state.",
    )
    parser.set_defaults(func=run)
    return parser


def run(_: Namespace, context: AppContext) -> int:
    return remote_command.run_doctor_command(
        context,
        include_admin_checks=False,
        heading="DOCTOR",
        rerun_command="servertool doctor",
    )
