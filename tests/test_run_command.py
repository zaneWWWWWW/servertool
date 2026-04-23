import contextlib
import hashlib
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
from servertool.controller.runs import SubmissionAudit, build_submission_audit, prepare_submit  # noqa: E402
from servertool.shared.config import Config  # noqa: E402
from servertool.shared.spec import RunSpec  # noqa: E402


class RunCommandsTest(unittest.TestCase):
    def test_build_submission_audit_captures_controller_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(temp_path)
                spec = RunSpec.defaults(config, project="vision", run_name="smoke")
                expected_spec_text = json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"))
                with mock.patch(
                    "servertool.controller.runs.platform.platform",
                    return_value="macOS-14-arm64",
                ):
                    with mock.patch("getpass.getuser", return_value="alice"):
                        with mock.patch(
                            "servertool.controller.runs.socket.gethostname",
                            return_value="controller-mac",
                        ):
                            with mock.patch(
                                "servertool.controller.runs.run_command",
                                side_effect=[
                                    CompletedProcess(args=["git", "rev-parse"], returncode=0, stdout="abc123\n", stderr=""),
                                    CompletedProcess(args=["git", "status"], returncode=0, stdout=" M README.md\n", stderr=""),
                                ],
                            ):
                                audit = build_submission_audit(config, spec, submitted_by="alice")

            self.assertEqual(audit.submitted_by, "alice")
            self.assertEqual(audit.controller_user, "alice")
            self.assertEqual(audit.controller_host, "controller-mac")
            self.assertEqual(audit.controller_platform, "macOS-14-arm64")
            self.assertEqual(audit.controller_version, config.version)
            self.assertEqual(audit.git_rev, "abc123")
            self.assertEqual(audit.git_dirty, True)
            self.assertEqual(
                audit.spec_sha256,
                hashlib.sha256(expected_spec_text.encode("utf-8")).hexdigest(),
            )

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
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
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
            self.assertIn("/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run", rendered)
            self.assertIn("/share/home/gpu2003/zanewang/.servertool/projects/vision/assets/code/manual-run", rendered)
            self.assertIn("runner prepare", rendered)
            self.assertIn("runner start", rendered)

    def test_prepare_submit_rewrites_shared_and_built_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_dir = temp_path / "project"
            project_dir.mkdir()
            (project_dir / "train.py").write_text("print('hello')\n")
            (project_dir / "requirements.txt").write_text("requests==2.31.0\n")
            spec_path = project_dir / "spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "version": "2",
                        "project": "vision",
                        "run_name": "smoke",
                        "assets": {
                            "code": {"source": "sync", "path": "."},
                            "dataset": {"source": "shared_path", "path": "/share/datasets/imagenet"},
                            "env": {
                                "source": "build",
                                "type": "pip",
                                "file": "requirements.txt",
                                "name": "Torch 2.3 CU121",
                            },
                            "model": {
                                "source": "hub",
                                "provider": "huggingface",
                                "id": "bert-base-uncased",
                                "revision": "main",
                            },
                        },
                        "launch": {
                            "scheduler": "slurm",
                            "partition": "A40",
                            "gpus": 1,
                            "cpus": 8,
                            "mem": "32G",
                            "time": "01:00:00",
                            "workdir": ".",
                            "command": "python train.py",
                        },
                        "fetch": {"include": ["outputs/**", "ckpts/**"]},
                        "notify": {"email": {"enabled": False, "to": []}},
                    },
                    indent=2,
                )
                + "\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }

            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(temp_path)
                plan = prepare_submit(config, spec_path, "manual-run", temp_path / "stage")

            self.assertEqual(
                plan.remote_spec.assets.code.path,
                "/share/home/gpu2003/zanewang/.servertool/projects/vision/assets/code/manual-run",
            )
            self.assertEqual(plan.remote_spec.assets.dataset.path, "/share/datasets/imagenet")
            self.assertEqual(
                plan.remote_spec.assets.env.file,
                "/share/home/gpu2003/zanewang/.servertool/projects/vision/assets/envs/manual-run/requirements.txt",
            )
            self.assertEqual(
                plan.remote_spec.assets.env.path,
                "/share/home/gpu2003/trainhub/envs/torch-2-3-cu121",
            )
            self.assertEqual(
                plan.remote_spec.assets.model.path,
                "/share/home/gpu2003/trainhub/models/huggingface/bert-base-uncased/main",
            )
            labels = [label for label, _ in plan.commands]
            self.assertIn("Upload environment build file", labels)
            self.assertNotIn("Sync dataset asset", labels)
            self.assertNotIn("Upload model asset", labels)

    def test_prepare_submit_uploads_dataset_env_and_model_fallback_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_dir = temp_path / "project"
            project_dir.mkdir()
            dataset_dir = project_dir / "dataset"
            env_dir = project_dir / "env-pack"
            model_dir = project_dir / "model-pack"
            dataset_dir.mkdir()
            env_dir.mkdir()
            model_dir.mkdir()
            (project_dir / "train.py").write_text("print('hello')\n")
            (dataset_dir / "data.txt").write_text("sample\n")
            (env_dir / "python").write_text("venv\n")
            (model_dir / "weights.bin").write_text("weights\n")
            spec_path = project_dir / "spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "version": "2",
                        "project": "vision",
                        "run_name": "smoke",
                        "assets": {
                            "code": {"source": "sync", "path": "."},
                            "dataset": {"source": "sync", "path": "dataset"},
                            "env": {"source": "upload", "path": "env-pack"},
                            "model": {"source": "upload", "path": "model-pack"},
                        },
                        "launch": {
                            "scheduler": "slurm",
                            "partition": "A40",
                            "gpus": 1,
                            "cpus": 8,
                            "mem": "32G",
                            "time": "01:00:00",
                            "workdir": ".",
                            "command": "python train.py",
                        },
                        "fetch": {"include": ["outputs/**", "ckpts/**"]},
                        "notify": {"email": {"enabled": False, "to": []}},
                    },
                    indent=2,
                )
                + "\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }

            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(temp_path)
                plan = prepare_submit(config, spec_path, "manual-run", temp_path / "stage")

            labels = [label for label, _ in plan.commands]
            self.assertIn("Sync dataset asset", labels)
            self.assertIn("Upload environment asset", labels)
            self.assertIn("Upload model asset", labels)
            self.assertEqual(
                plan.remote_spec.assets.dataset.path,
                "/share/home/gpu2003/zanewang/.servertool/projects/vision/assets/datasets/manual-run",
            )
            self.assertEqual(
                plan.remote_spec.assets.env.path,
                "/share/home/gpu2003/zanewang/.servertool/projects/vision/assets/envs/manual-run",
            )
            self.assertEqual(
                plan.remote_spec.assets.model.path,
                "/share/home/gpu2003/zanewang/.servertool/projects/vision/assets/models/manual-run",
            )

    def test_run_status_prints_remote_runner_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            payload = {
                "run_id": "manual-run",
                "state": "running",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
            }
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
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            status_payload = {
                "run_id": "manual-run",
                "state": "running",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch(
                    "servertool.controller.runs.remote_ops.run_ssh_command",
                    side_effect=[
                        CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(status_payload), stderr=""),
                        CompletedProcess(args=["ssh"], returncode=0, stdout="line1\nline2\n", stderr=""),
                    ],
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
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            running_payload = {
                "run_id": "manual-run",
                "state": "running",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
            }
            terminal_payload = {
                "run_id": "manual-run",
                "state": "succeeded",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch(
                    "servertool.controller.runs.remote_ops.run_ssh_command",
                    side_effect=[
                        CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(running_payload), stderr=""),
                        CompletedProcess(args=["ssh"], returncode=0, stdout="line1\nline2\n", stderr=""),
                        CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(running_payload), stderr=""),
                        CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(terminal_payload), stderr=""),
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
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
            }
            status_payload = {
                "run_id": "manual-run",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
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
            self.assertIn(
                "gpu2003@cluster.example.com:/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run",
                rsync_argv,
            )
            record = json.loads((local_cache / "manual-run.json").read_text())
            self.assertEqual(
                record["remote_run_root"],
                "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run",
            )
            self.assertEqual(record["local_fetch_path"], str(fetch_root / "manual-run"))

    def test_run_fetch_uses_remote_fetch_include_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
            }
            status_payload = {
                "run_id": "manual-run",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
                "fetch": {"include": ["outputs/**", "ckpts/**"]},
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
                        exit_code = main(["run", "fetch", "manual-run"])

            self.assertEqual(exit_code, 0)
            rsync_argv = mocked_run.call_args[0][0]
            self.assertIn("--prune-empty-dirs", rsync_argv)
            self.assertIn("--include=*/", rsync_argv)
            self.assertIn("--include=outputs/**", rsync_argv)
            self.assertIn("--include=ckpts/**", rsync_argv)
            self.assertIn("--exclude=*", rsync_argv)

    def test_run_fetch_refuses_other_member_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
            }
            status_payload = {
                "run_id": "manual-run",
                "member_id": "alice",
                "paths": {"run_root": "/share/home/gpu2003/alice/.servertool/projects/vision/runs/manual-run"},
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch(
                    "servertool.controller.runs.remote_ops.run_ssh_command",
                    return_value=CompletedProcess(args=["ssh"], returncode=0, stdout=json.dumps(status_payload), stderr=""),
                ):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        exit_code = main(["run", "fetch", "manual-run"])

            self.assertEqual(exit_code, 1)
            self.assertIn("belongs to member 'alice'", stdout.getvalue())

    def test_run_submit_records_audit_metadata_and_passes_prepare_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_dir = temp_path / "project"
            project_dir.mkdir()
            (project_dir / "train.py").write_text("print('hello')\n")
            spec_path = project_dir / "spec.json"
            local_cache = temp_path / "runs"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_REMOTE_HOST": "cluster.example.com",
                "SERVERTOOL_REMOTE_USER": "gpu2003",
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
            }
            audit = SubmissionAudit(
                submitted_by="alice",
                controller_user="alice",
                controller_host="controller-mac",
                controller_platform="macOS-14-arm64",
                controller_version="3.0.0",
                git_rev="abc123",
                git_dirty=False,
                spec_sha256="deadbeef",
            )

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
                with mock.patch("servertool.controller.runs.build_submission_audit", return_value=audit):
                    with mock.patch(
                        "servertool.commands.run.run_command",
                        return_value=CompletedProcess(args=["ssh"], returncode=0, stdout="", stderr=""),
                    ) as mocked_run:
                        exit_code = main(["run", "submit", str(spec_path), "--run-id", "manual-run"])

            self.assertEqual(exit_code, 0)
            record = json.loads((local_cache / "manual-run.json").read_text())
            self.assertEqual(record["submitted_by"], "alice")
            self.assertEqual(record["controller_host"], "controller-mac")
            self.assertEqual(record["git_rev"], "abc123")
            self.assertEqual(record["git_dirty"], False)
            self.assertEqual(record["spec_sha256"], "deadbeef")

            prepare_command = next(
                argv
                for argv in (call.args[0] for call in mocked_run.call_args_list)
                if any("runner prepare" in part for part in argv)
            )
            self.assertTrue(any("SERVERTOOL_CONTROLLER_HOST=controller-mac" in part for part in prepare_command))
            self.assertTrue(any("SERVERTOOL_SOURCE_GIT_REV=abc123" in part for part in prepare_command))

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

    def test_run_list_filters_other_members_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            local_cache.mkdir()
            (local_cache / "run-a.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-a",
                        "member_id": "zanewang",
                        "project": "vision",
                        "submitted_at": "2026-04-20T12:00:00Z",
                        "remote_host": "cluster-a",
                    }
                )
                + "\n"
            )
            (local_cache / "run-b.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-b",
                        "member_id": "alice",
                        "project": "nlp",
                        "submitted_at": "2026-04-21T12:00:00Z",
                        "remote_host": "cluster-b",
                    }
                )
                + "\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
                "SERVERTOOL_MEMBER_ID": "zanewang",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["run", "list", "--json"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual([item["run_id"] for item in payload], ["run-a"])

    def test_run_list_all_members_includes_other_member_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_cache = temp_path / "runs"
            local_cache.mkdir()
            (local_cache / "run-a.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-a",
                        "member_id": "zanewang",
                        "project": "vision",
                        "submitted_at": "2026-04-20T12:00:00Z",
                        "remote_host": "cluster-a",
                    }
                )
                + "\n"
            )
            (local_cache / "run-b.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-b",
                        "member_id": "alice",
                        "project": "nlp",
                        "submitted_at": "2026-04-21T12:00:00Z",
                        "remote_host": "cluster-b",
                    }
                )
                + "\n"
            )
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_LOCAL_RUN_CACHE": str(local_cache),
                "SERVERTOOL_MEMBER_ID": "zanewang",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["run", "list", "--json", "--all-members"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual([item["run_id"] for item in payload], ["run-b", "run-a"])

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
                        "remote_run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run",
                        "member_id": "zanewang",
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
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            status_payload = {
                "run_id": "manual-run",
                "state": "succeeded",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
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
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            status_payload = {
                "run_id": "manual-run",
                "state": "running",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
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
                        "remote_run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run",
                        "member_id": "zanewang",
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
                "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
            }
            status_payload = {
                "run_id": "manual-run",
                "state": "succeeded",
                "member_id": "zanewang",
                "paths": {"run_root": "/share/home/gpu2003/zanewang/.servertool/projects/vision/runs/manual-run"},
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
