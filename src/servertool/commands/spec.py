from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path
import json

from ..context import AppContext
from ..shared.spec import SpecValidationError, RunSpec, load_spec, write_spec


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "spec",
        help="Create and validate run specs",
        description="Create, inspect, and validate servertool run spec files.",
    )
    parser.add_argument("mode", nargs="?", choices=["init", "show", "validate"], help="Spec action")
    parser.add_argument("spec", nargs="?", help="Path to spec.json")
    parser.add_argument("--project", help="Project name for spec init")
    parser.add_argument("--run-name", default="baseline", help="Run name for spec init")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing spec file")
    parser.set_defaults(func=run)
    return parser


def _default_project_name() -> str:
    current = Path.cwd().name.strip()
    return current or "project"


def _spec_path(raw_path: str | None) -> Path:
    return Path(raw_path or "spec.json").expanduser()


def _run_init(args: Namespace, context: AppContext) -> int:
    path = _spec_path(args.spec)
    if path.exists() and not args.force:
        context.console.fail(f"Spec already exists: {path}")
        context.console.info("Re-run with --force to overwrite it")
        return 1

    spec = RunSpec.defaults(
        context.config,
        project=args.project or _default_project_name(),
        run_name=args.run_name,
    )
    write_spec(path, spec)
    context.console.ok(f"Wrote run spec to {path}")
    return 0


def _run_show(args: Namespace, context: AppContext) -> int:
    try:
        spec = load_spec(_spec_path(args.spec))
    except (OSError, json.JSONDecodeError, SpecValidationError) as error:
        context.console.fail(str(error))
        return 1
    print(json.dumps(spec.to_dict(), indent=2))
    return 0


def _run_validate(args: Namespace, context: AppContext) -> int:
    path = _spec_path(args.spec)
    try:
        load_spec(path)
    except (OSError, json.JSONDecodeError, SpecValidationError) as error:
        context.console.fail(str(error))
        return 1
    context.console.ok(f"Spec is valid: {path}")
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode is None:
        context.topic_parsers["spec"].print_help()
        return 0
    if args.mode == "init":
        return _run_init(args, context)
    if args.mode == "show":
        return _run_show(args, context)
    if args.mode == "validate":
        return _run_validate(args, context)
    context.console.fail(f"Unknown spec subcommand: {args.mode}")
    return 1
