from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from datetime import datetime
import json
import sys
import time
from typing import Any, Optional

from ..context import AppContext
from ..system import directory_size_kb, humanize_kb


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "disk",
        help="Shared quota and cache management",
        description="Monitor the shared home usage and manage the cached disk summary.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["show", "detail", "update", "auto"],
        default="show",
        help="Disk monitor action",
    )
    parser.set_defaults(func=run)
    return parser


def _load_cache(context: AppContext) -> Optional[dict[str, Any]]:
    cache_path = context.config.cache_file
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text())
    except json.JSONDecodeError:
        context.console.fail(f"Cache file is invalid: {cache_path}")
        return None


def _save_cache(context: AppContext, payload: dict) -> None:
    context.config.cache_file.parent.mkdir(parents=True, exist_ok=True)
    context.config.cache_file.write_text(json.dumps(payload, indent=2, sort_keys=True))


def get_usage_summary(context: AppContext) -> tuple[str, str, str]:
    cache = _load_cache(context)
    if not cache:
        return "unknown", context.config.quota_limit, "never"
    return cache.get("total_usage", "unknown"), context.config.quota_limit, cache.get("timestamp", "never")


def _show_progress(current: int, total: int) -> None:
    if not sys.stdout.isatty() or total <= 0:
        return
    width = 40
    percent = int((current * 100) / total)
    filled = int((current * width) / total)
    empty = width - filled
    bar = "#" * filled + "-" * empty
    print(f"\r  Progress: [{bar}] {percent:3d}% ({current}/{total})", end="", flush=True)


def _run_update(context: AppContext) -> int:
    console = context.console
    shared_home = context.config.shared_home
    if not shared_home.exists():
        console.fail(f"Shared home does not exist: {shared_home}")
        return 1

    folders = sorted(path for path in shared_home.iterdir() if path.is_dir())
    if not folders:
        console.fail(f"No subdirectories found under {shared_home}")
        return 1

    print("Updating disk usage cache...\n")
    print(f"  Found {len(folders)} folders to scan\n")
    start_time = time.time()
    total_kb = 0
    entries: list[dict[str, object]] = []

    for index, folder in enumerate(folders, start=1):
        _show_progress(index, len(folders))
        size_kb = directory_size_kb(folder)
        total_kb += size_kb
        if size_kb > 0:
            entries.append(
                {
                    "path": str(folder),
                    "folder": folder.name,
                    "size_kb": size_kb,
                    "size": humanize_kb(size_kb),
                }
            )

    if sys.stdout.isatty():
        print()
    print()

    entries.sort(key=lambda entry: int(entry["size_kb"]), reverse=True)
    duration_seconds = int(time.time() - start_time)
    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": duration_seconds,
        "quota_limit": context.config.quota_limit,
        "total_usage": humanize_kb(total_kb),
        "total_usage_kb": total_kb,
        "entries": entries,
    }
    _save_cache(context, payload)
    print("Cache updated successfully!")
    print(f"  Timestamp: {payload['timestamp']}")
    print(f"  Scan duration: {duration_seconds}s")
    print(f"  Total usage: {payload['total_usage']} / {context.config.quota_limit}")
    print("")
    console.footer()
    return 0


def _run_show(context: AppContext) -> int:
    cache = _load_cache(context)
    if not cache:
        context.console.fail("Cache file not found. Run 'servertool disk update' first.")
        return 1

    context.console.header("DISK USAGE STATUS")
    context.console.info(f"Total Usage:  {cache.get('total_usage', 'unknown')} / {context.config.quota_limit}")
    context.console.info(f"Last Updated: {cache.get('timestamp', 'never')}")
    context.console.info(f"Scan Time:    {cache.get('duration_seconds', 0)}s")
    print("")
    context.console.footer()
    return 0


def _run_detail(context: AppContext) -> int:
    cache = _load_cache(context)
    if not cache:
        context.console.fail("Cache file not found. Run 'servertool disk update' first.")
        return 1

    context.console.header("DISK USAGE DETAIL")
    context.console.info(f"Total: {cache.get('total_usage', 'unknown')} / {context.config.quota_limit}")
    context.console.info(f"Last Updated: {cache.get('timestamp', 'never')}")
    print("")
    print("  Usage by folder:")
    print("  -------------------------------------------")
    for entry in cache.get("entries", []):
        print(f"  {str(entry['size']).ljust(10)} {entry['folder']}")
    print("")
    context.console.footer()
    return 0


def _run_auto(context: AppContext) -> int:
    context.console.header("AUTO-UPDATE SETUP")
    print("To automatically update disk usage every 6 hours, add this to crontab:\n")
    print("  crontab -e\n")
    print("Then add one of these lines:\n")
    print(f"  0 */6 * * * {context.config.install_path} disk update > /dev/null 2>&1")
    print(f"  0 0 * * * {context.config.install_path} disk update > /dev/null 2>&1")
    print("")
    context.console.footer()
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode == "show":
        return _run_show(context)
    if args.mode == "detail":
        return _run_detail(context)
    if args.mode == "update":
        return _run_update(context)
    if args.mode == "auto":
        return _run_auto(context)
    context.console.fail(f"Unknown disk subcommand: {args.mode}")
    return 1
