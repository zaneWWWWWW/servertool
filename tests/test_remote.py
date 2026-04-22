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
from servertool.config import Config  # noqa: E402
from servertool.remote import build_rsync_push_command, build_ssh_command, servertool_remote_argv  # noqa: E402


class RemoteHelpersTest(unittest.TestCase):
    def test_command_builders_use_configured_remote_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_PORT": "2222",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(Path("/tmp/servertool"))

            ssh_command = build_ssh_command(config, servertool_remote_argv(config, ["version"]))
            rsync_command = build_rsync_push_command(
                config,
                Path(temp_dir),
                config.remote_root_posix / "projects" / "vision" / "assets" / "code" / "manual-run",
                contents_only=True,
            )

            self.assertEqual(ssh_command[:4], ["ssh", "-p", "2222", "gpu2003@cluster.example.com"])
            self.assertIn("gpu2003@cluster.example.com:/cluster/home/clusteruser/trainhub/projects/vision/assets/code/manual-run", rsync_command)


class RemoteDoctorTest(unittest.TestCase):
    def test_remote_doctor_checks_local_and_remote_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("servertool.commands.remote.command_exists", return_value=True):
                    with mock.patch(
                        "servertool.commands.remote.run_command",
                        return_value=CompletedProcess(args=["rsync", "--version"], returncode=0, stdout="rsync version 3.2.0\n", stderr=""),
                    ):
                        with mock.patch(
                            "servertool.commands.remote.remote_ops.run_ssh_command",
                            side_effect=[
                                CompletedProcess(args=["ssh"], returncode=0, stdout="Python 3.11.9\n", stderr=""),
                                CompletedProcess(args=["ssh"], returncode=0, stdout="servertool 3.0.0\n", stderr=""),
                            ],
                        ):
                            stdout = io.StringIO()
                            with contextlib.redirect_stdout(stdout):
                                exit_code = main(["remote", "doctor"])

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("remote python", rendered)
            self.assertIn("remote servertool", rendered)

    def test_install_runner_dry_run_prints_runner_sync_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["remote", "install-runner", "--dry-run"])

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Remote module root: /share/home/gpu2003/trainhub/.runner", rendered)
            self.assertIn("Sync servertool package", rendered)
            self.assertIn("--delete", rendered)
            self.assertIn("PYTHONPATH=/share/home/gpu2003/trainhub/.runner", rendered)

    def test_remote_bootstrap_dry_run_prints_config_sync_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            smtp_path = temp_path / "smtp.env"
            smtp_path.write_text(
                "export SERVERTOOL_SMTP_USERNAME=notify@example.com\n"
                "export SERVERTOOL_SMTP_PASSWORD=secret\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                "SERVERTOOL_NOTIFY_EMAIL_FROM": "notify@example.com",
                "SERVERTOOL_NOTIFY_EMAIL_TO": "receiver@example.com",
                "SERVERTOOL_SMTP_SECRETS_FILE": str(smtp_path),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["remote", "bootstrap", "--dry-run"])

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Remote config file: /share/home/gpu2003/.config/servertool/config.env", rendered)
            self.assertIn("Remote SMTP secrets: /share/home/gpu2003/.config/servertool/smtp.env", rendered)
            self.assertIn("Upload runner config", rendered)
            self.assertIn("Upload SMTP secrets", rendered)
            self.assertIn("Secure remote config files", rendered)

    def test_remote_cleanup_dry_run_prints_safe_delete_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            status_payload = {
                "run_id": "manual-run",
                "state": "succeeded",
                "paths": {"run_root": "/share/home/gpu2003/trainhub/projects/vision/runs/manual-run"},
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("servertool.controller.cleanup.load_remote_status", return_value=status_payload):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        exit_code = main(["remote", "cleanup", "manual-run", "--dry-run"])

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Remote run path: /share/home/gpu2003/trainhub/projects/vision/runs/manual-run", rendered)
            self.assertIn("Remote state: succeeded", rendered)
            self.assertIn("rm -rf /share/home/gpu2003/trainhub/projects/vision/runs/manual-run", rendered)
