from __future__ import annotations

from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter
from pathlib import Path
from typing import Optional, Sequence
import re
import sys

from .shared.config import Config
from .context import AppContext
from .output import Console
from .commands import admin, configure, doctor, init, remote, run, runner, spec


class PublicCommandParser(ArgumentParser):
    hidden_subcommands: tuple[str, ...] = ()

    def format_help(self) -> str:
        text = super().format_help()
        if not self.hidden_subcommands:
            return text

        hidden = set(self.hidden_subcommands)

        def _filter_choice_block(match: re.Match[str]) -> str:
            items = [item for item in match.group(1).split(",") if item not in hidden]
            return "{" + ",".join(items) + "}"

        lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if any(stripped.startswith(f"{name} ") and "==SUPPRESS==" in stripped for name in hidden):
                continue
            lines.append(line)

        sanitized = "\n".join(lines)
        sanitized = re.sub(r"\{([^{}]+)\}", _filter_choice_block, sanitized)
        sanitized = sanitized.replace(",,", ",").replace("{,", "{").replace(",}", "}")
        if text.endswith("\n"):
            sanitized += "\n"
        return sanitized


def _build_parser(context: AppContext) -> ArgumentParser:
    help_topics = [
        "init",
        "config",
        "doctor",
        "spec",
        "run",
        "admin",
    ]
    hidden_commands = ("runner", "remote")
    parser = PublicCommandParser(
        prog=context.config.name,
        description="Servertool is a training CLI for shared-account lab workflows.",
        epilog=(
            "Examples:\n"
            "  servertool init\n"
            "  servertool config show\n"
            "  servertool doctor\n"
            "  servertool spec init spec.json\n"
            "  servertool run submit --dry-run spec.json\n"
            "  servertool run list --json --all-members\n"
            "  servertool run cleanup RUN_ID --dry-run\n"
            "  servertool admin deploy\n"
            "  servertool admin rollback 2.9.0\n"
            "  servertool admin doctor"
        ),
        formatter_class=RawDescriptionHelpFormatter,
    )
    parser.hidden_subcommands = hidden_commands
    parser.add_argument("--version", action="version", version=f"{context.config.name} {context.config.version}")
    subparsers = parser.add_subparsers(dest="command")

    context.topic_parsers["main"] = parser
    context.topic_parsers["init"] = init.register(subparsers)
    context.topic_parsers["config"] = configure.register(subparsers)
    context.topic_parsers["doctor"] = doctor.register(subparsers)
    context.topic_parsers["spec"] = spec.register(subparsers)
    context.topic_parsers["run"] = run.register(subparsers)
    context.topic_parsers["admin"] = admin.register(subparsers)

    context.topic_parsers["runner"] = runner.register(subparsers, hidden=True)
    context.topic_parsers["remote"] = remote.register(subparsers, hidden=True)

    help_parser = subparsers.add_parser("help", help="Show help for a command")
    help_parser.add_argument(
        "topic",
        nargs="?",
        choices=help_topics,
    )
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
