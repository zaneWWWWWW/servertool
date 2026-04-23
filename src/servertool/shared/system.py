from __future__ import annotations

from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import sys
from typing import Iterable, Mapping, Sequence


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(
    command: Sequence[str],
    capture_output: bool = True,
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), capture_output=capture_output, text=True, env=dict(env) if env else None, cwd=cwd)


def shlex_join(command: Sequence[str]) -> str:
    return shlex.join(list(command))


def cpu_count_text() -> str:
    count = os.cpu_count()
    return str(count) if count is not None else "unknown"


def _format_gib(byte_count: int) -> str:
    return f"{byte_count / (1024 ** 3):.1f}Gi"


def _linux_memory_summary() -> tuple[str, str]:
    if command_exists("free"):
        result = run_command(["free", "-h"])
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Mem:"):
                    parts = line.split()
                    if len(parts) >= 7:
                        return parts[6], parts[1]

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values: dict[str, int] = {}
        for line in meminfo.read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0])
        available = values.get("MemAvailable")
        total = values.get("MemTotal")
        if available is not None and total is not None:
            return _format_gib(available * 1024), _format_gib(total * 1024)

    return "unknown", "unknown"


def _darwin_memory_summary() -> tuple[str, str]:
    total_result = run_command(["sysctl", "-n", "hw.memsize"])
    vm_result = run_command(["vm_stat"])
    if total_result.returncode != 0 or vm_result.returncode != 0:
        return "unknown", "unknown"

    try:
        total_bytes = int(total_result.stdout.strip())
    except ValueError:
        return "unknown", "unknown"

    page_size_match = re.search(r"page size of (\d+) bytes", vm_result.stdout)
    page_size = int(page_size_match.group(1)) if page_size_match else 4096

    pages: dict[str, int] = {}
    for line in vm_result.stdout.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip().rstrip(".")
        try:
            pages[key] = int(value)
        except ValueError:
            continue

    available_pages = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)
    available_bytes = available_pages * page_size
    return _format_gib(available_bytes), _format_gib(total_bytes)


def memory_summary() -> tuple[str, str]:
    if sys.platform == "darwin":
        return _darwin_memory_summary()
    return _linux_memory_summary()


def humanize_kb(size_kb: int) -> str:
    if size_kb >= 1_073_741_824:
        return f"{size_kb / 1_073_741_824:.1f}T"
    if size_kb >= 1_048_576:
        return f"{size_kb / 1_048_576:.1f}G"
    if size_kb >= 1024:
        return f"{size_kb / 1024:.1f}M"
    return f"{size_kb}K"


def directory_size_kb(path: Path) -> int:
    if command_exists("du"):
        result = run_command(["du", "-sk", str(path)])
        if result.returncode == 0:
            try:
                return int(result.stdout.split()[0])
            except (IndexError, ValueError):
                pass

    total_bytes = 0
    for child in path.rglob("*"):
        if child.is_file():
            total_bytes += child.stat().st_size
    return total_bytes // 1024


def clear_screen() -> None:
    if command_exists("clear"):
        subprocess.run(["clear"], capture_output=True, text=True)


def print_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    materialized_rows = [list(row) for row in rows]
    widths = [len(header) for header in headers]
    for row in materialized_rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    header_line = " ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    separator = " ".join("-" * width for width in widths)
    print(header_line)
    print(separator)
    for row in materialized_rows:
        print(" ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
