from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction

from ..context import AppContext
from ..system import clear_screen, shlex_join


def register(subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
    parser = subparsers.add_parser(
        "quickstart",
        help="Interactive onboarding guide",
        description="Launch an interactive quickstart guide for new cluster users.",
    )
    parser.set_defaults(func=run)
    return parser


def _pause() -> None:
    input("Press Enter to continue...")


def run(_: Namespace, context: AppContext) -> int:
    config = context.config
    clear_screen()
    print("==============================================")
    print("    WELCOME TO SERVERTOOL")
    print("    Quick Start Guide for New Cluster Users")
    print("==============================================")
    print("")
    print("This guide will help you get started with the cluster workflow.")
    print("")

    print("STEP 1: Understanding the Server")
    print("----------------------------------------------")
    print("This is a SLURM-managed GPU cluster with:")
    print(f"  - {config.a40_partition} GPUs")
    print(f"  - {config.a6000_partition} GPUs")
    print("")
    print("You cannot use GPUs directly on the login node.")
    print("You must request resources through SLURM first.")
    print("")
    _pause()

    clear_screen()
    print("STEP 2: Create Your Working Directory")
    print("----------------------------------------------")
    print(f"  cd {config.shared_home}")
    print("  mkdir YOUR_NAME")
    print("  cd YOUR_NAME")
    print("")
    _pause()

    clear_screen()
    print("STEP 3: Request GPU Resources")
    print("----------------------------------------------")
    print("See the presets first:")
    print("  servertool request guide")
    print("")
    print("Recommended command for beginners:")
    print("  servertool request medium")
    print("")
    print("Manual command:")
    print(f"  {shlex_join(config.recommended_request())}")
    print("")
    _pause()

    clear_screen()
    print("STEP 4: Check Your Resources")
    print("----------------------------------------------")
    print("  servertool status")
    print("  servertool status quick")
    print("  nvidia-smi")
    print("  echo $CUDA_VISIBLE_DEVICES")
    print("")
    _pause()

    clear_screen()
    print("STEP 5: Network Access")
    print("----------------------------------------------")
    print("Compute nodes may not have internet access.")
    print("If you need network, authenticate at:")
    print(f"  {config.auth_url}")
    print("")
    _pause()

    clear_screen()
    print("STEP 6: Monitor Your Jobs")
    print("----------------------------------------------")
    print("  servertool jobs")
    print("  servertool jobs who")
    print("  servertool jobs info <JOB_ID>")
    print("  servertool jobs cancel <JOB_ID>")
    print("")
    _pause()

    clear_screen()
    print("STEP 7: Important Notes")
    print("----------------------------------------------")
    print(f"  * {config.a40_partition} jobs can run up to {config.a40_max_time}")
    print(f"  * {config.a6000_partition} jobs can run up to {config.a6000_max_time}")
    print(f"  * Shared disk quota: {config.quota_limit}")
    print("  * Always release resources when done (exit the shell)")
    print("  * Do not run heavy tasks on the login node")
    print("")
    print("==============================================")
    print("    QUICK REFERENCE COMMANDS")
    print("==============================================")
    print("")
    print("  servertool request guide   - Show resource presets")
    print("  servertool request medium  - Request a recommended GPU node")
    print("  servertool status          - Check server status")
    print("  servertool jobs            - Manage your jobs")
    print("  servertool disk show       - Check shared disk usage")
    print("")
    print("==============================================")
    print("    YOU'RE READY TO START!")
    print("==============================================")
    print("")
    return 0
