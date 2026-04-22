import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from subprocess import CompletedProcess
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.app import main  # noqa: E402


class RunnerCommandsTest(unittest.TestCase):
    def test_runner_prepare_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runner_root = temp_path / "trainhub"
            spec_path = temp_path / "spec.json"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_RUNNER_ROOT": str(runner_root),
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                "SERVERTOOL_NOTIFY_EMAIL_TO": "notify@example.com",
            }

            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    main([
                        "spec",
                        "init",
                        str(spec_path),
                        "--project",
                        "vision",
                        "--run-name",
                        "smoke",
                    ]),
                    0,
                )

                prepare_stdout = io.StringIO()
                with contextlib.redirect_stdout(prepare_stdout):
                    exit_code = main(["runner", "prepare", str(spec_path), "--run-id", "manual-run"])

                self.assertEqual(exit_code, 0)

                run_dir = runner_root / "projects" / "vision" / "runs" / "manual-run"
                self.assertTrue((run_dir / "spec.json").exists())
                self.assertTrue((run_dir / "meta.json").exists())
                self.assertTrue((run_dir / "status.json").exists())
                self.assertTrue((run_dir / "launch.sh").exists())
                self.assertTrue((run_dir / "job.sbatch").exists())

                status_payload = json.loads((run_dir / "status.json").read_text())
                self.assertEqual(status_payload["run_id"], "manual-run")
                self.assertEqual(status_payload["state"], "prepared")

                job_script = (run_dir / "job.sbatch").read_text()
                self.assertIn("#SBATCH --partition=A40", job_script)
                self.assertIn("#SBATCH --gres=gpu:1", job_script)

                status_stdout = io.StringIO()
                with contextlib.redirect_stdout(status_stdout):
                    exit_code = main(["runner", "status", "manual-run"])

                self.assertEqual(exit_code, 0)
                printed = json.loads(status_stdout.getvalue())
                self.assertEqual(printed["run_id"], "manual-run")
                self.assertEqual(printed["paths"]["run_root"], run_dir.as_posix())

    def test_runner_start_updates_status_with_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runner_root = temp_path / "trainhub"
            spec_path = temp_path / "spec.json"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_RUNNER_ROOT": str(runner_root),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    main([
                        "spec",
                        "init",
                        str(spec_path),
                        "--project",
                        "vision",
                        "--run-name",
                        "smoke",
                    ]),
                    0,
                )
                self.assertEqual(main(["runner", "prepare", str(spec_path), "--run-id", "manual-run"]), 0)

                with mock.patch("servertool.commands.runner.command_exists", return_value=True):
                    with mock.patch(
                        "servertool.commands.runner.run_command",
                        return_value=CompletedProcess(
                            args=["sbatch", "job.sbatch"],
                            returncode=0,
                            stdout="Submitted batch job 12345\n",
                            stderr="",
                        ),
                    ):
                        exit_code = main(["runner", "start", "manual-run"])

            self.assertEqual(exit_code, 0)
            status_payload = json.loads(
                (runner_root / "projects" / "vision" / "runs" / "manual-run" / "status.json").read_text()
            )
            self.assertEqual(status_payload["state"], "running")
            self.assertEqual(status_payload["job_id"], "12345")
            self.assertTrue(status_payload["started_at"])

    def test_runner_tail_reads_last_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runner_root = temp_path / "trainhub"
            spec_path = temp_path / "spec.json"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_RUNNER_ROOT": str(runner_root),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    main([
                        "spec",
                        "init",
                        str(spec_path),
                        "--project",
                        "vision",
                        "--run-name",
                        "smoke",
                    ]),
                    0,
                )
                self.assertEqual(main(["runner", "prepare", str(spec_path), "--run-id", "manual-run"]), 0)
                run_dir = runner_root / "projects" / "vision" / "runs" / "manual-run"
                (run_dir / "stdout.log").write_text("line1\nline2\nline3\n")

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["runner", "tail", "manual-run", "--lines", "2"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue().strip(), "line2\nline3")

    def test_runner_prepare_launch_script_finalizes_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runner_root = temp_path / "trainhub"
            spec_path = temp_path / "spec.json"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_RUNNER_ROOT": str(runner_root),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    main([
                        "spec",
                        "init",
                        str(spec_path),
                        "--project",
                        "vision",
                        "--run-name",
                        "smoke",
                    ]),
                    0,
                )
                self.assertEqual(main(["runner", "prepare", str(spec_path), "--run-id", "manual-run"]), 0)

            launch_script = (runner_root / "projects" / "vision" / "runs" / "manual-run" / "launch.sh").read_text()
            self.assertIn("runner finalize", launch_script)
            self.assertIn("PYTHONPATH=\"$RUNNER_MODULE_ROOT\"", launch_script)
            self.assertIn("exit \"$EXIT_CODE\"", launch_script)

    def test_runner_finalize_updates_status_and_sends_notification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runner_root = temp_path / "trainhub"
            spec_path = temp_path / "spec.json"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_RUNNER_ROOT": str(runner_root),
                "SERVERTOOL_NOTIFY_EMAIL_TO": "notify@example.com",
            }

            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    main([
                        "spec",
                        "init",
                        str(spec_path),
                        "--project",
                        "vision",
                        "--run-name",
                        "smoke",
                    ]),
                    0,
                )
                self.assertEqual(main(["runner", "prepare", str(spec_path), "--run-id", "manual-run"]), 0)

                run_dir = runner_root / "projects" / "vision" / "runs" / "manual-run"
                status_path = run_dir / "status.json"
                status_payload = json.loads(status_path.read_text())
                status_payload["state"] = "running"
                status_payload["job_id"] = "12345"
                status_payload["started_at"] = "2026-04-21T12:00:00Z"
                status_path.write_text(json.dumps(status_payload) + "\n")
                (run_dir / "stderr.log").write_text("traceback line\n")

                with mock.patch("servertool.commands.runner.send_email") as mocked_send_email:
                    exit_code = main(["runner", "finalize", "manual-run", "--exit-code", "0"])

            self.assertEqual(exit_code, 0)
            updated_status = json.loads(status_path.read_text())
            self.assertEqual(updated_status["state"], "succeeded")
            self.assertEqual(updated_status["exit_code"], 0)
            self.assertEqual(updated_status["job_id"], "12345")
            self.assertEqual(updated_status["notify_error"], "")
            self.assertTrue(updated_status["ended_at"])

            mocked_send_email.assert_called_once()
            self.assertEqual(mocked_send_email.call_args[0][1], ("notify@example.com",))
            self.assertIn("manual-run", mocked_send_email.call_args[0][2])
            self.assertIn("succeeded", mocked_send_email.call_args[0][2])
            self.assertIn("stderr tail:", mocked_send_email.call_args[0][3])

    def test_runner_finalize_records_notify_error_without_changing_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runner_root = temp_path / "trainhub"
            spec_path = temp_path / "spec.json"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_RUNNER_ROOT": str(runner_root),
                "SERVERTOOL_NOTIFY_EMAIL_TO": "notify@example.com",
            }

            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(
                    main([
                        "spec",
                        "init",
                        str(spec_path),
                        "--project",
                        "vision",
                        "--run-name",
                        "smoke",
                    ]),
                    0,
                )
                self.assertEqual(main(["runner", "prepare", str(spec_path), "--run-id", "manual-run"]), 0)

                run_dir = runner_root / "projects" / "vision" / "runs" / "manual-run"
                status_path = run_dir / "status.json"
                status_payload = json.loads(status_path.read_text())
                status_payload["state"] = "running"
                status_payload["started_at"] = "2026-04-21T12:00:00Z"
                status_path.write_text(json.dumps(status_payload) + "\n")

                with mock.patch(
                    "servertool.commands.runner.send_email",
                    side_effect=RuntimeError("smtp unreachable"),
                ):
                    exit_code = main(["runner", "finalize", "manual-run", "--exit-code", "1"])

            self.assertEqual(exit_code, 0)
            updated_status = json.loads(status_path.read_text())
            self.assertEqual(updated_status["state"], "failed")
            self.assertEqual(updated_status["exit_code"], 1)
            self.assertEqual(updated_status["notify_error"], "smtp unreachable")

    def test_runner_notify_test_sends_test_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("servertool.commands.runner.send_test_email") as mocked_send_test:
                    exit_code = main(["runner", "notify", "--test", "alice@example.com"])

            self.assertEqual(exit_code, 0)
            mocked_send_test.assert_called_once()
            self.assertEqual(mocked_send_test.call_args[0][1], "alice@example.com")
