import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from subprocess import CompletedProcess
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.app import main  # noqa: E402


class CliSurfaceTest(unittest.TestCase):
    def test_main_help_lists_new_public_commands_only(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["help"])

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()
        self.assertIn("{init,config,doctor,spec,run,admin,help,version}", rendered)
        self.assertIn("    init", rendered)
        self.assertIn("    doctor", rendered)
        self.assertIn("    admin", rendered)
        self.assertIn("    config", rendered)
        self.assertIn("    spec", rendered)
        self.assertIn("    run", rendered)
        self.assertNotIn("    quickstart", rendered)
        self.assertNotIn("    request", rendered)
        self.assertNotIn("    status", rendered)
        self.assertNotIn("    jobs", rendered)
        self.assertNotIn("    disk", rendered)
        self.assertNotIn("    remote", rendered)
        self.assertNotIn("    runner", rendered)

    def test_admin_deploy_dry_run_prints_lab_sync_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            smtp_path = temp_path / "smtp.env"
            smtp_path.write_text(
                "export SERVERTOOL_SMTP_USERNAME=notify@example.com\n"
                "export SERVERTOOL_SMTP_PASSWORD=secret\n"
            )
            env = {
                "SERVERTOOL_USER_CONFIG_FILE": str(temp_path / "user.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                "SERVERTOOL_NOTIFY_EMAIL_FROM": "notify@example.com",
                "SERVERTOOL_SMTP_SECRETS_FILE": str(smtp_path),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["admin", "deploy", "--dry-run"])

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()
        self.assertIn("Runner release: 3.0.0", rendered)
        self.assertIn("Remote lab config file: /share/home/gpu2003/trainhub/lab/lab.env", rendered)
        self.assertIn("Shared env root: /share/home/gpu2003/trainhub/envs", rendered)
        self.assertIn("Shared model root: /share/home/gpu2003/trainhub/models", rendered)
        self.assertIn("Shared cache root: /share/home/gpu2003/trainhub/cache", rendered)
        self.assertIn("Upload shared lab config", rendered)
        self.assertIn("Upload SMTP secrets", rendered)

    def test_admin_show_config_prints_release_and_remote_config_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env = {
                "SERVERTOOL_USER_CONFIG_FILE": str(temp_path / "user.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["admin", "show-config"])

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()
        self.assertIn("Remote lab config file: /share/home/gpu2003/trainhub/lab/lab.env", rendered)
        self.assertIn("Remote SMTP secrets file: /share/home/gpu2003/trainhub/lab/smtp.env", rendered)
        self.assertIn("Runner staged release root: /share/home/gpu2003/trainhub/.runner/releases/3.0.0", rendered)
        self.assertIn("Runner current link: /share/home/gpu2003/trainhub/.runner/current", rendered)
        self.assertIn("Runner module root: /share/home/gpu2003/trainhub/.runner/current", rendered)

    def test_doctor_uses_member_facing_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_USER_CONFIG_FILE": str(Path(temp_dir) / "user.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("servertool.commands.remote.command_exists", return_value=True):
                    with mock.patch(
                        "servertool.commands.remote.run_command",
                        return_value=CompletedProcess(
                            args=["rsync", "--version"],
                            returncode=0,
                            stdout="rsync version 3.2.0\n",
                            stderr="",
                        ),
                    ):
                        with mock.patch(
                            "servertool.commands.remote.remote_ops.run_ssh_command",
                            side_effect=[
                                CompletedProcess(args=["ssh"], returncode=0, stdout="Python 3.11.9\n", stderr=""),
                                CompletedProcess(args=["ssh"], returncode=0, stdout="/share/home/gpu2003/trainhub\n", stderr=""),
                                CompletedProcess(args=["ssh"], returncode=0, stdout="/share/home/gpu2003/zanewang/.servertool\n", stderr=""),
                                CompletedProcess(args=["ssh"], returncode=0, stdout="/share/home/gpu2003/trainhub/.runner/current\n", stderr=""),
                                CompletedProcess(args=["ssh"], returncode=0, stdout="/share/home/gpu2003/trainhub/lab/lab.env\n", stderr=""),
                                CompletedProcess(args=["ssh"], returncode=0, stdout="/share/home/gpu2003/zanewang/.servertool/config.env\n", stderr=""),
                                CompletedProcess(args=["ssh"], returncode=0, stdout="/usr/bin/sbatch\n", stderr=""),
                                CompletedProcess(args=["ssh"], returncode=0, stdout="servertool 3.0.0\n", stderr=""),
                            ],
                        ):
                            stdout = io.StringIO()
                            with contextlib.redirect_stdout(stdout):
                                exit_code = main(["doctor"])

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()
        self.assertIn("Servertool preflight passed", rendered)
        self.assertIn("default notify email", rendered)
        self.assertNotIn("local smtp secrets", rendered)


if __name__ == "__main__":
    unittest.main()
