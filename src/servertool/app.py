from __future__ import annotations

from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter
from pathlib import Path
from typing import Optional, Sequence
import sys

from .config import Config
from .context import AppContext
from .output import Console
from .commands import disk, jobs, quickstart, request, status, testjob


def _build_parser(context: AppContext) -> ArgumentParser:
    parser = ArgumentParser(
        prog=context.config.name,
        description="Servertool is a Python CLI for Ubuntu cluster resource operations.",
        epilog=(
            "Examples:\n"
            "  servertool status\n"
            "  servertool jobs who\n"
            "  servertool disk update\n"
            "  servertool request guide\n"
            "  servertool request medium"
        ),
        formatter_class=RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"{context.config.name} {context.config.version}")
    subparsers = parser.add_subparsers(dest="command")

    context.topic_parsers["main"] = parser
    context.topic_parsers["status"] = status.register(subparsers)
    context.topic_parsers["jobs"] = jobs.register(subparsers)
    context.topic_parsers["disk"] = disk.register(subparsers)
    context.topic_parsers["request"] = request.register(subparsers)
    context.topic_parsers["quickstart"] = quickstart.register(subparsers)
    context.topic_parsers["test"] = testjob.register(subparsers)

    help_parser = subparsers.add_parser("help", help="Show help for a command")
    help_parser.add_argument("topic", nargs="?", choices=["status", "jobs", "disk", "request", "quickstart", "test"])
    help_parser.set_defaults(func=_run_help)

    version_parser = subparsers.add_parser("version", help="Show version")
    version_parser.set_defaults(func=_run_version)

    return parser


def _run_help(args: Namespace, context: AppContext) -> int:
    topic = args.topic or "main"
    context.topic_parsers[topic].print_help()
    return 0


def _run_version(_: Namespace, context: AppContext) -> int:
    print(f"{context.config.name} {context.config.version}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    root = Path(__file__).resolve().parents[1]
    config = Config.from_root(root)
    context = AppContext(config=config, console=Console(config))
    parser = _build_parser(context)

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        parser.print_help()
        return 0

    args = parser.parse_args(arguments)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return int(func(args, context))
