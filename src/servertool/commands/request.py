from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
import subprocess
import time

from ..context import AppContext
from ..system import command_exists, shlex_join


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "request",
        help="GPU resource request presets",
        description="Request GPU resources with standard presets or custom parameters.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["guide", "light", "medium", "heavy", "a6000", "custom"],
        default="guide",
        help="Request preset or guide topic",
    )
    parser.set_defaults(func=run)
    return parser


def _print_guide(context: AppContext) -> None:
    config = context.config
    console = context.console
    console.header("HOW TO REQUEST RESOURCES")
    print("Available GPU partitions:")
    print(f"  {config.a40_partition}   NVIDIA A40 GPUs (4 per node, up to {config.a40_max_time})")
    print(f"  {config.a6000_partition} NVIDIA RTX A6000 GPUs (2 per node, up to {config.a6000_max_time})")
    print("")
    print("Quick commands:")
    print(f"  Light:  srun -p {config.a40_partition} -N 1 -n 4 --mem=16G --gres=gpu:1 --pty bash -i")
    print(f"  Medium: srun -p {config.a40_partition} -N 1 -n 8 --mem=32G --gres=gpu:1 --pty bash -i")
    print(f"  Heavy:  srun -p {config.a40_partition} -N 1 -n 16 --mem=64G --gres=gpu:2 --pty bash -i")
    print(f"  A6000:  srun -p {config.a6000_partition} -N 1 -n 8 --mem=32G --gres=gpu:1 --pty bash -i")
    print("")
    print("Recommended path layout:")
    print(f"  cd {config.shared_home}")
    print(f"  mkdir -p {config.workspace_name}")
    print(f"  cd {config.workspace_name}")
    print(f"  # Full path: {config.workspace_path}")
    print("")
    print("Useful commands after allocation:")
    print("  nvidia-smi")
    print("  echo $CUDA_VISIBLE_DEVICES")
    print("  squeue -u $USER")
    print("  scancel <JOB_ID>")
    print("  exit")
    print("")
    print(f"If compute nodes have no internet access, authenticate at: {config.auth_url}")
    console.footer()


def _request_resources(context: AppContext, partition: str, nodes: int, cpus: int, memory_gb: int, gpus: int) -> int:
    console = context.console
    config = context.config
    if not command_exists("srun"):
        console.fail("srun is not available on this node")
        return 1

    command = [
        "srun",
        "-p",
        partition,
        "-N",
        str(nodes),
        "-n",
        str(cpus),
        f"--mem={memory_gb}G",
        f"--gres=gpu:{gpus}",
        "--pty",
        "bash",
        "-i",
    ]

    print("")
    print("Requesting resources:")
    print(f"  Partition: {partition}")
    print(f"  Nodes: {nodes}")
    print(f"  CPUs: {cpus}")
    print(f"  Memory: {memory_gb}G")
    print(f"  GPUs: {gpus}")
    print("")
    print(f"Executing: {shlex_join(command)}")
    print("")
    print(f"Note: Maximum allocation time on {partition} is {config.partition_max_time(partition)}")
    print("Press Ctrl+C to cancel, or wait 3 seconds to proceed...")
    time.sleep(3)
    return subprocess.run(command).returncode


def _request_custom(context: AppContext) -> int:
    config = context.config
    print("")
    print("Custom Resource Configuration")
    print("----------------------------------------------")
    print("Select GPU partition:")
    print(f"  1) {config.a40_partition}")
    print(f"  2) {config.a6000_partition}")

    partition_choice = input("Enter choice [1]: ").strip() or "1"
    partition = config.a6000_partition if partition_choice == "2" else config.a40_partition
    gpus = int(input("Number of GPUs [1]: ").strip() or "1")
    cpus = int(input("Number of CPU cores [8]: ").strip() or "8")
    memory = int(input("Memory in GB [32]: ").strip() or "32")
    nodes = int(input("Number of nodes [1]: ").strip() or "1")
    return _request_resources(context, partition, nodes, cpus, memory, gpus)


def run(args: Namespace, context: AppContext) -> int:
    mode = args.mode
    if mode == "guide":
        _print_guide(context)
        return 0
    if mode == "light":
        return _request_resources(context, context.config.a40_partition, 1, 4, 16, 1)
    if mode == "medium":
        return _request_resources(context, context.config.a40_partition, 1, 8, 32, 1)
    if mode == "heavy":
        return _request_resources(context, context.config.a40_partition, 1, 16, 64, 2)
    if mode == "a6000":
        return _request_resources(context, context.config.a6000_partition, 1, 8, 32, 1)
    if mode == "custom":
        return _request_custom(context)
    context.console.fail(f"Unknown request subcommand: {mode}")
    return 1
