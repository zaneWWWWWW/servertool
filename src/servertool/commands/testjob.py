from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from pathlib import Path
import re
import subprocess
import tempfile

from ..context import AppContext
from ..system import command_exists


JOB_ID_PATTERN = re.compile(r"(\d+)")


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "test",
        help="Test SLURM job submission",
        description="Submit test jobs to verify SLURM job submission and output handling.",
    )
    parser.add_argument("mode", nargs="?", choices=["job", "quick"], help="Test mode")
    parser.set_defaults(func=run)
    return parser


def _extract_job_id(text: str) -> str:
    matches = JOB_ID_PATTERN.findall(text)
    return matches[-1] if matches else "unknown"


def _write_script(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _run_waited_job(context: AppContext) -> int:
    if not command_exists("sbatch"):
        context.console.fail("sbatch is not available on this node")
        return 1

    context.console.header("TEST JOB SUBMISSION")
    output_dir = context.config.test_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        script_path = temp_dir / "servertool_test_job.sh"
        output_path = temp_dir / "servertool_test_output.txt"
        _write_script(
            script_path,
            "#!/bin/bash\n"
            "echo \"=== SLURM Test Job ===\"\n"
            "echo \"Job ID: $SLURM_JOB_ID\"\n"
            "echo \"Node: $(hostname)\"\n"
            "echo \"Time: $(date)\"\n"
            "echo\n"
            "echo \"Generating 5 random numbers:\"\n"
            "for i in 1 2 3 4 5; do\n"
            "  echo \"  Random $i: $RANDOM\"\n"
            "done\n"
            "echo\n"
            "echo \"Test completed successfully!\"\n",
        )

        print("  Submitting test job...\n")
        result = subprocess.run(
            [
                "sbatch",
                "--job-name=servertool_test_job",
                f"--partition={context.config.a40_partition}",
                "--nodes=1",
                "--ntasks=1",
                "--mem=1G",
                "--time=00:01:00",
                f"--output={output_path}",
                "--wait",
                str(script_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            context.console.fail("Job submission failed")
            context.console.info(f"Error: {result.stderr.strip() or result.stdout.strip()}")
            print("")
            context.console.footer()
            return 1

        job_id = _extract_job_id(result.stdout)
        context.console.ok("Job submitted successfully")
        context.console.info(f"Job ID: {job_id}")
        print("")
        if output_path.exists():
            print("  Job Output:")
            print("  -------------------------------------------")
            for line in output_path.read_text().splitlines():
                print(f"  {line}")
            print("  -------------------------------------------\n")
        context.console.ok("SLURM job system is working correctly")
        print("")
        context.console.footer()
        return 0


def _run_background_job(context: AppContext) -> int:
    if not command_exists("sbatch"):
        context.console.fail("sbatch is not available on this node")
        return 1

    context.console.header("QUICK JOB SUBMISSION TEST")
    output_dir = context.config.test_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        script_path = temp_dir / "servertool_quick_job.sh"
        _write_script(
            script_path,
            "#!/bin/bash\n"
            "echo \"Random numbers test job\"\n"
            "for i in 1 2 3 4 5 6 7 8 9 10; do\n"
            "  echo \"Random $i: $RANDOM\"\n"
            "done\n"
            "echo \"Done at $(date)\"\n",
        )

        print("  Submitting test job in the background...\n")
        result = subprocess.run(
            [
                "sbatch",
                "--job-name=servertool_test_job",
                f"--partition={context.config.a40_partition}",
                "--nodes=1",
                "--ntasks=1",
                "--mem=1G",
                "--time=00:01:00",
                f"--output={output_dir / 'servertool_test_%j.out'}",
                str(script_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            context.console.fail("Job submission failed")
            context.console.info(f"Error: {result.stderr.strip() or result.stdout.strip()}")
            print("")
            context.console.footer()
            return 1

        job_id = _extract_job_id(result.stdout)
        context.console.ok("Job submitted successfully")
        context.console.info(f"Job ID: {job_id}")
        context.console.info(f"Check status with: squeue -j {job_id}")
        context.console.info(f"View output with: cat {output_dir / f'servertool_test_{job_id}.out'}")
        context.console.info(f"Cancel with: scancel {job_id}")
        print("")
        context.console.ok("SLURM job submission is working")
        print("")
        context.console.footer()
        return 0


def run(args: Namespace, context: AppContext) -> int:
    if args.mode is None:
        context.topic_parsers["test"].print_help()
        return 0
    if args.mode == "job":
        return _run_waited_job(context)
    if args.mode == "quick":
        return _run_background_job(context)
    context.console.fail(f"Unknown test subcommand: {args.mode}")
    return 1
