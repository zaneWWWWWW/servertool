from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
import os
import socket
from typing import Callable

from ..context import AppContext
from ..system import command_exists, cpu_count_text, memory_summary, run_command, shlex_join
from . import jobs
from .disk import get_usage_summary


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "status",
        help="Cluster health and node checks",
        description="Show server status, GPU visibility, jobs, partitions, network, and local resource summaries.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["full", "quick", "gpu", "jobs", "network"],
        default="full",
        help="Status view mode",
    )
    parser.set_defaults(func=run)
    return parser


def _print_gpu_status(context: AppContext, section_label: str = "1") -> None:
    console = context.console
    console.section(section_label, "GPU Status")
    if command_exists("nvidia-smi"):
        probe = run_command(["nvidia-smi"])
        if probe.returncode == 0:
            console.ok("GPU driver available")
            visible = run_command(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ]
            )
            allocated = os.getenv("CUDA_VISIBLE_DEVICES")
            if allocated:
                console.info(f"Allocated GPUs: {allocated}")
            else:
                console.info("CUDA_VISIBLE_DEVICES is not set")
            print("")
            for line in visible.stdout.splitlines():
                parts = [part.strip() for part in line.split(",")]
                if len(parts) == 5:
                    console.info(
                        f"GPU {parts[0]}: {parts[1]} | Memory: {parts[2]}/{parts[3]} MiB | Util: {parts[4]}%"
                    )
            print("")
            return

    console.fail("GPU not accessible on this node")
    console.info(f"Request GPU: {shlex_join(context.config.recommended_request())}")
    print("")


def _print_jobs_status(context: AppContext, section_label: str = "2") -> None:
    context.console.section(section_label, "Active Jobs")
    jobs.render_compact_cluster_status(context)
    print("")


def _print_partition_status(context: AppContext, section_label: str = "3") -> None:
    context.console.section(section_label, "Available Partitions")
    if command_exists("sinfo"):
        result = run_command(["sinfo", "-o", "  %10P %6a %11l %6D %6T"])
        if result.returncode == 0:
            print("  PARTITION  AVAIL  TIMELIMIT   NODES  STATE")
            lines = result.stdout.splitlines()[1:]
            for line in lines:
                print(line)
        else:
            context.console.fail("Unable to query partitions with sinfo")
    else:
        context.console.fail("sinfo is not available")
    print("")


def _internet_connected(context: AppContext, timeout_seconds: str) -> bool:
    if not command_exists("curl"):
        return False
    result = run_command(
        [
            "curl",
            "-fsS",
            "--connect-timeout",
            timeout_seconds,
            "-o",
            "/dev/null",
            context.config.network_probe_url,
        ]
    )
    return result.returncode == 0


def _print_network_status(context: AppContext, section_label: str = "4") -> None:
    context.console.section(section_label, "Network Connectivity")
    if command_exists("curl"):
        if _internet_connected(context, "3"):
            context.console.ok("Internet: Connected")
        else:
            context.console.fail("Internet: NOT connected")
            context.console.info(f"Authenticate at: {context.config.auth_url}")
    else:
        context.console.fail("curl is not available")

    if command_exists("ping"):
        ping_result = run_command(["ping", "-c", "1", "-W", "2", context.config.default_compute_host])
        if ping_result.returncode == 0:
            context.console.ok("Cluster network: Connected")
        else:
            context.console.info(f"Cluster network: Cannot reach {context.config.default_compute_host}")
    else:
        context.console.info("ping is not available")
    print("")


def _print_resource_status(context: AppContext, section_label: str = "5") -> None:
    context.console.section(section_label, "System Resources")
    available, total = memory_summary()
    disk_usage, quota, timestamp = get_usage_summary(context)
    context.console.info(f"CPU cores: {cpu_count_text()}")
    context.console.info(f"Memory: {available} available / {total} total")
    context.console.info(f"Disk usage: {disk_usage} / {quota} quota")
    context.console.info(f"Last scan: {timestamp}")
    context.console.info(f"Hostname: {socket.gethostname()}")
    print("")


def _run_quick(context: AppContext) -> int:
    context.console.header("QUICK SERVER STATUS")
    if command_exists("nvidia-smi") and run_command(["nvidia-smi"]).returncode == 0:
        result = run_command(["nvidia-smi", "--query-gpu=count", "--format=csv,noheader"])
        gpu_count = result.stdout.splitlines()[0].strip() if result.returncode == 0 and result.stdout.strip() else "unknown"
        print(f"  GPU:     [OK] {gpu_count} GPU(s) available")
    else:
        print("  GPU:     [FAIL] Not on a GPU node")

    if command_exists("squeue"):
        job_result = run_command(["squeue", "-u", os.getenv("USER", "unknown"), "-h"])
        job_count = len([line for line in job_result.stdout.splitlines() if line.strip()]) if job_result.returncode == 0 else "unknown"
        print(f"  Jobs:    {job_count} active job(s)")
    else:
        print("  Jobs:    unknown")

    if _internet_connected(context, "2"):
        print("  Network: [OK] Connected")
    else:
        print("  Network: [FAIL] Not connected")

    available, _ = memory_summary()
    print(f"  Memory:  {available} available")
    print("")
    print("Run 'servertool status' for detailed info")
    context.console.footer()
    return 0


def _run_full(context: AppContext) -> int:
    context.console.header(f"SERVERTOOL - v{context.config.version}")
    _print_gpu_status(context, "1")
    _print_jobs_status(context, "2")
    _print_partition_status(context, "3")
    _print_network_status(context, "4")
    _print_resource_status(context, "5")
    print("==================================================")
    print("       STATUS CHECK COMPLETE")
    print("==================================================\n")
    context.console.footer()
    return 0


def _run_single(context: AppContext, title: str, action: Callable[..., None]) -> int:
    context.console.header(title)
    action(context)
    context.console.footer()
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode == "full":
        return _run_full(context)
    if args.mode == "quick":
        return _run_quick(context)
    if args.mode == "gpu":
        return _run_single(context, "GPU STATUS", _print_gpu_status)
    if args.mode == "jobs":
        return _run_single(context, "ACTIVE JOBS", _print_jobs_status)
    if args.mode == "network":
        return _run_single(context, "NETWORK STATUS", _print_network_status)
    context.console.fail(f"Unknown status subcommand: {args.mode}")
    return 1
