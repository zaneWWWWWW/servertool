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


class RunCommandsTest(unittest.TestCase):
    def test_submit_dry_run_prints_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_dir = temp_path / "project"
            project_dir.mkdir()
            (project_dir / "train.py").write_text("print('hello')\n")
            spec_path = project_dir / "spec.json"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
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

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main([
                        "run",
                        "submit",
                        str(spec_path),
                        "--run-id",
                        "manual-run",
                        "--dry-run",
                    ])

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Run ID: manual-run", rendered)
            self.assertIn("/share/home/gpu2003/trainhub/projects/vision/runs/manual-run", rendered)
            self.assertIn("/share/home/gpu2003/trainhub/projects/vision/assets/code/manual-run", rendered)
            self.assertIn("runner prepare", rendered)
            self.assertIn("runner start", rendered)

    def test_run_status_prints_remote_runner_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            payload = {"run_id": "manual-run", "state": "running"}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch(
                    "servertool.controller.runs.remote_ops.run_ssh_command",
                    return_value=CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(payload), stderr=""),
                ):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        exit_code = main(["run", "status", "manual-run"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), payload)

    def test_run_logs_prints_remote_tail_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch(
                    "servertool.controller.runs.remote_ops.run_ssh_command",
                    return_value=CompletedProcess(args=["ssh"], returncode=0, stdout="line1\nline2\n", stderr=""),
                ):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        exit_code = main(["run", "logs", "manual-run", "--lines", "2"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue().strip(), "line1\nline2")

    def test_run_logs_follow_polls_and_prints_only_new_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            running_payload = {"run_id": "manual-run", "state": "running"}
            terminal_payload = {"run_id": "manual-run", "state": "succeeded"}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch(
                    "servertool.controller.runs.remote_ops.run_ssh_command",
                    side_effect=[
                        CompletedProcess(args=["ssh"], returncode=0, stdout="line1\nline2\n", stderr=""),
                        CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(running_payload), stderr=""),
                        CompletedProcess(args=["ssh"], returncode=0, stdout="line2\nline3\nline4\n", stderr=""),
                        CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(terminal_payload), stderr=""),
                    ],
                ):
                    with mock.patch(
                        "servertool.controller.runs.time.sleep",
                        side_effect=[None],
                    ):
                        stdout = io.StringIO()
                        with contextlib.redirect_stdout(stdout):
                            exit_code = main(["run", "logs", "manual-run", "--lines", "3", "--follow"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue().strip(), "line1\nline2\nline3\nline4")

    def test_run_fetch_updates_local_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fetch_root = temp_path / "fetches"
            local_cache = temp_path / "runs"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
            }
            status_payload = {
                "run_id": "manual-run",
                "paths": {"run_root": "/share/home/gpu2003/trainhub/projects/vision/runs/manual-run"},
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch(
                    "servertool.controller.runs.remote_ops.run_ssh_command",
                    return_value=CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(status_payload), stderr=""),
                ):
                    with mock.patch(
                        "servertool.commands.run.run_command",
                        return_value=CompletedProcess(args=["rsync"], returncode=0, stdout="", stderr=""),
                    ) as mocked_run:
                        exit_code = main(["run", "fetch", "manual-run", "--dest", str(fetch_root)])

            self.assertEqual(exit_code, 0)
            rsync_argv = mocked_run.call_args[0][0]
            self.assertIn("gpu2003@cluster.example.com:/share/home/gpu2003/trainhub/projects/vision/runs/manual-run", rsync_argv)
            record = json.loads((local_cache / "manual-run.json").read_text())
            self.assertEqual(record["remote_run_root"], "/share/home/gpu2003/trainhub/projects/vision/runs/manual-run")
            self.assertEqual(record["local_fetch_path"], str(fetch_root / "manual-run"))

    def test_run_list_prints_local_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            local_cache.mkdir()
            (local_cache / "run-b.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-b",
                        "project": "vision",
                        "submitted_at": "2026-04-21T12:00:00Z",
                        "remote_host": "cluster-b",
                    }
                )
                + "\n"
            )
            (local_cache / "run-a.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-a",
                        "project": "nlp",
                        "submitted_at": "2026-04-20T12:00:00Z",
                        "remote_host": "cluster-a",
                    }
                )
                + "\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["run", "list"])

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("RUN_ID", rendered)
            self.assertIn("run-b", rendered)
            self.assertIn("run-a", rendered)

    def test_run_list_json_prints_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            local_cache.mkdir()
            (local_cache / "run-a.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-a",
                        "project": "vision",
                        "submitted_at": "2026-04-20T12:00:00Z",
                        "remote_host": "cluster-a",
                    }
                )
                + "\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["run", "list", "--json"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["run_id"], "run-a")

    def test_run_cleanup_dry_run_prints_remote_and_local_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            fetched_dir = local_cache / "fetched" / "manual-run"
            fetched_dir.mkdir(parents=True)
            (local_cache / "manual-run.json").write_text(
                json.dumps(
                    {
                        "run_id": "manual-run",
                        "remote_run_root": "/share/home/gpu2003/trainhub/projects/vision/runs/manual-run",
                        "local_fetch_path": str(fetched_dir),
                    }
                )
                + "\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
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
                        exit_code = main(["run", "cleanup", "manual-run", "--dry-run"])

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Remote state: succeeded", rendered)
            self.assertIn("Remove remote run directory", rendered)
            self.assertIn("Remove local run record", rendered)
            self.assertIn("Remove local fetched directory", rendered)

    def test_run_cleanup_refuses_running_state_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            status_payload = {
                "run_id": "manual-run",
                "state": "running",
                "paths": {"run_root": "/share/home/gpu2003/trainhub/projects/vision/runs/manual-run"},
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("servertool.controller.cleanup.load_remote_status", return_value=status_payload):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        exit_code = main(["run", "cleanup", "manual-run"])

            self.assertEqual(exit_code, 1)
            self.assertIn("Refusing to delete run 'manual-run' while remote state is 'running'", stdout.getvalue())

    def test_run_cleanup_removes_remote_and_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            fetched_dir = local_cache / "fetched" / "manual-run"
            fetched_dir.mkdir(parents=True)
            record_path = local_cache / "manual-run.json"
            record_path.write_text(
                json.dumps(
                    {
                        "run_id": "manual-run",
                        "remote_run_root": "/share/home/gpu2003/trainhub/projects/vision/runs/manual-run",
                        "local_fetch_path": str(fetched_dir),
                    }
                )
                + "\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
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
                    with mock.patch(
                        "servertool.commands.run.run_command",
                        return_value=CompletedProcess(args=["ssh"], returncode=0, stdout="", stderr=""),
                    ) as mocked_run:
                        exit_code = main(["run", "cleanup", "manual-run"])

            self.assertEqual(exit_code, 0)
            self.assertFalse(record_path.exists())
            self.assertFalse(fetched_dir.exists())
            self.assertIn("gpu2003@cluster.example.com", mocked_run.call_args[0][0])

    def test_run_cleanup_local_only_does_not_require_remote_host(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            fetched_dir = local_cache / "fetched" / "manual-run"
            fetched_dir.mkdir(parents=True)
            record_path = local_cache / "manual-run.json"
            record_path.write_text(json.dumps({"run_id": "manual-run", "local_fetch_path": str(fetched_dir)}) + "\n")
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                exit_code = main(["run", "cleanup", "manual-run", "--local-only"])

            self.assertEqual(exit_code, 0)
            self.assertFalse(record_path.exists())
            self.assertFalse(fetched_dir.exists())
