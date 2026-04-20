from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
import os
import re
from typing import Optional

from ..context import AppContext
from ..system import command_exists, print_table, run_command


WORKDIR_PATTERN = re.compile(r"WorkDir=([^ ]+)")
CPU_PATTERN = re.compile(r"NumCPUs=(\d+)")
GPU_PATTERN = re.compile(r"gpu:(\d+)")


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "jobs",
        help="SLURM job inspection and control",
        description="Inspect SLURM jobs, ownership, GPU usage, and cancel jobs when needed.",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["list", "all", "who", "gpu", "info", "cancel"],
        default="list",
        help="Jobs action",
    )
    parser.add_argument("job_id", nargs="?", help="Job ID for info or cancel")
    parser.set_defaults(func=run)
    return parser


def _require(context: AppContext, command: str, message: str) -> bool:
    if command_exists(command):
        return True
    context.console.fail(message)
    return False


def get_job_workdir(context: AppContext, job_id: str) -> str:
    if not _require(context, "scontrol", "scontrol is not available on this node"):
        return ""
    result = run_command(["scontrol", "show", "job", job_id])
    if result.returncode != 0:
        return ""
    match = WORKDIR_PATTERN.search(result.stdout)
    return match.group(1) if match else ""


def extract_owner_from_workdir(context: AppContext, workdir: str) -> str:
    shared_home = str(context.config.shared_home)
    prefix = f"{shared_home}/"
    if not workdir.startswith(prefix):
        return "unknown"
    owner = workdir[len(prefix) :].split("/", 1)[0]
    if owner and owner != context.config.shared_account:
        return owner
    return context.config.shared_account


def get_job_owner(context: AppContext, job_id: str) -> str:
    return extract_owner_from_workdir(context, get_job_workdir(context, job_id))


def _job_ids(context: AppContext, partition: Optional[str] = None) -> list[str]:
    if not _require(context, "squeue", "SLURM is not available on this node"):
        return []
    command = ["squeue", "-h", "-o", "%i"]
    if partition:
        command = ["squeue", "-p", partition, "-h", "-o", "%i"]
    result = run_command(command)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def render_compact_cluster_status(context: AppContext) -> None:
    if not _require(context, "squeue", "SLURM is not available on this node"):
        return
    if not _require(context, "scontrol", "scontrol is not available on this node"):
        return

    job_ids = _job_ids(context)
    if not job_ids:
        context.console.info("No active jobs")
        return

    context.console.ok(f"{len(job_ids)} active job(s) in cluster")
    print("")
    rows: list[list[str]] = []
    for job_id in job_ids:
        result = run_command(["squeue", "-h", "-j", job_id, "-o", "%i|%P|%T|%M|%D"])
        if result.returncode != 0 or not result.stdout.strip():
            continue
        fields = result.stdout.strip().split("|")
        if len(fields) != 5:
            continue
        rows.append([fields[0], fields[1], get_job_owner(context, job_id), fields[2], fields[3], fields[4]])

    if rows:
        print_table(["JOBID", "PARTITION", "OWNER", "STATE", "TIME", "NODES"], rows)


def _run_list(context: AppContext) -> int:
    if not _require(context, "squeue", "SLURM is not available on this node"):
        return 1

    context.console.header("YOUR JOBS")
    result = run_command(
        [
            "squeue",
            "-u",
            os.getenv("USER", "unknown"),
            "-o",
            "%.10i %.12P %.20j %.8u %.8T %.10M %.9l %.6D %R",
        ]
    )
    print(result.stdout.rstrip() or "No jobs found")
    print("")
    count_result = run_command(["squeue", "-u", os.getenv("USER", "unknown"), "-h"])
    count = len([line for line in count_result.stdout.splitlines() if line.strip()]) if count_result.returncode == 0 else 0
    print(f"Total jobs: {count}")
    context.console.footer()
    return 0


def _run_all(context: AppContext) -> int:
    if not _require(context, "squeue", "SLURM is not available on this node"):
        return 1
    if not _require(context, "scontrol", "scontrol is not available on this node"):
        return 1

    context.console.header("ALL CLUSTER JOBS")
    rows: list[list[str]] = []
    for job_id in _job_ids(context):
        result = run_command(["squeue", "-h", "-j", job_id, "-o", "%i|%P|%T|%M|%D|%R"])
        if result.returncode != 0 or not result.stdout.strip():
            continue
        fields = result.stdout.strip().split("|")
        if len(fields) != 6:
            continue
        rows.append([fields[0], fields[1], get_job_owner(context, job_id), fields[2], fields[3], fields[4], fields[5]])

    if rows:
        print_table(["JOBID", "PARTITION", "OWNER", "STATE", "TIME", "NODES", "NODELIST"], rows)
    else:
        print("No jobs found")
    print("")
    print(f"Total jobs: {len(rows)}")
    context.console.footer()
    return 0


def _run_info(context: AppContext, job_id: Optional[str]) -> int:
    if not job_id:
        context.console.fail("Please provide a job ID")
        return 1
    if not _require(context, "scontrol", "scontrol is not available on this node"):
        return 1

    context.console.header(f"JOB DETAILS: {job_id}")
    context.console.info(f"Owner (from WorkDir): {get_job_owner(context, job_id)}")
    print("")
    result = run_command(["scontrol", "show", "job", job_id])
    print(result.stdout.rstrip() or result.stderr.rstrip() or "No job details available")
    context.console.footer()
    return 0 if result.returncode == 0 else 1


def _run_cancel(context: AppContext, job_id: Optional[str]) -> int:
    if not job_id:
        context.console.fail("Please provide a job ID")
        return 1
    if not _require(context, "scancel", "scancel is not available on this node"):
        return 1

    print(f"Cancelling job {job_id}...")
    result = run_command(["scancel", job_id], capture_output=True)
    if result.returncode == 0:
        print(f"Job {job_id} has been cancelled.")
        context.console.footer()
        return 0
    print(result.stderr.rstrip() or f"Failed to cancel job {job_id}.")
    context.console.footer()
    return 1


def _run_gpu(context: AppContext) -> int:
    if not _require(context, "sinfo", "sinfo is not available on this node"):
        return 1
    if not _require(context, "squeue", "squeue is not available on this node"):
        return 1
    if not _require(context, "scontrol", "scontrol is not available on this node"):
        return 1

    context.console.header("GPU PARTITION STATUS")
    partition_arg = ",".join(context.config.gpu_partitions)
    print("Partition Information:")
    info_result = run_command(["sinfo", "-p", partition_arg, "-o", "%P %a %l %D %T %C %G"])
    if info_result.returncode != 0:
        info_result = run_command(["sinfo", "-o", "%P %a %l %D %T %C %G"])
    print(info_result.stdout.rstrip() or "No partition information available")
    print("")
    print("Jobs on GPU partitions (with owners):")
    print("")

    rows: list[list[str]] = []
    for job_id in _job_ids(context, partition_arg):
        result = run_command(["squeue", "-h", "-j", job_id, "-o", "%i|%P|%T|%M|%R"])
        if result.returncode != 0 or not result.stdout.strip():
            continue
        fields = result.stdout.strip().split("|")
        if len(fields) != 5:
            continue
        rows.append([fields[0], fields[1], get_job_owner(context, job_id), fields[2], fields[3], fields[4]])

    if rows:
        print_table(["JOBID", "PARTITION", "OWNER", "STATE", "TIME", "NODELIST"], rows)
    else:
        print("No GPU jobs found")
    print("")
    context.console.footer()
    return 0


def _run_who(context: AppContext) -> int:
    if not _require(context, "squeue", "SLURM is not available on this node"):
        return 1
    if not _require(context, "scontrol", "scontrol is not available on this node"):
        return 1

    context.console.header("RESOURCE USAGE BY OWNER")
    totals: dict[str, dict[str, int]] = {}
    for job_id in _job_ids(context):
        owner = get_job_owner(context, job_id)
        info_result = run_command(["scontrol", "show", "job", job_id])
        if info_result.returncode != 0:
            continue
        info = info_result.stdout
        gpus = int(GPU_PATTERN.search(info).group(1)) if GPU_PATTERN.search(info) else 0
        cpus = int(CPU_PATTERN.search(info).group(1)) if CPU_PATTERN.search(info) else 0
        owner_totals = totals.setdefault(owner, {"jobs": 0, "gpus": 0, "cpus": 0})
        owner_totals["jobs"] += 1
        owner_totals["gpus"] += gpus
        owner_totals["cpus"] += cpus

    rows = [
        [owner, str(values["jobs"]), str(values["gpus"]), str(values["cpus"])]
        for owner, values in sorted(
            totals.items(),
            key=lambda item: (item[1]["gpus"], item[1]["jobs"], item[0]),
            reverse=True,
        )
    ]
    if rows:
        print_table(["OWNER", "JOBS", "GPUS", "CPUS"], rows)
    else:
        print("No jobs found")
    print("")
    print(f"Total jobs: {sum(values['jobs'] for values in totals.values())}")
    context.console.footer()
    return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode == "list":
        return _run_list(context)
    if args.mode == "all":
        return _run_all(context)
    if args.mode == "who":
        return _run_who(context)
    if args.mode == "gpu":
        return _run_gpu(context)
    if args.mode == "info":
        return _run_info(context, args.job_id)
    if args.mode == "cancel":
        return _run_cancel(context, args.job_id)
    context.console.fail(f"Unknown jobs subcommand: {args.mode}")
    return 1
