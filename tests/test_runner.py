import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from subprocess import CompletedProcess
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.app import main  # noqa: E402
from servertool.config import Config  # noqa: E402
from servertool.runner.assets import _build_conda_env, prepare_run_assets  # noqa: E402
from servertool.spec import RunSpec  # noqa: E402


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
                "SERVERTOOL_SUBMITTED_BY": "alice",
                "SERVERTOOL_CONTROLLER_USER": "alice",
                "SERVERTOOL_CONTROLLER_HOST": "controller-mac",
                "SERVERTOOL_CONTROLLER_PLATFORM": "macOS-14-arm64",
                "SERVERTOOL_CONTROLLER_VERSION": "3.0.0",
                "SERVERTOOL_SOURCE_GIT_REV": "abc123",
                "SERVERTOOL_SOURCE_GIT_DIRTY": "1",
                "SERVERTOOL_SPEC_SHA256": "deadbeef",
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

                meta_payload = json.loads((run_dir / "meta.json").read_text())
                self.assertEqual(meta_payload["member_id"], "YOUR_NAME")
                self.assertEqual(meta_payload["audit"]["submitted_by"], "alice")
                self.assertEqual(meta_payload["audit"]["controller_host"], "controller-mac")
                self.assertEqual(meta_payload["audit"]["git_rev"], "abc123")
                self.assertEqual(meta_payload["audit"]["git_dirty"], True)
                self.assertEqual(meta_payload["audit"]["spec_sha256"], "deadbeef")

                job_script = (run_dir / "job.sbatch").read_text()
                self.assertIn("#SBATCH --partition=A40", job_script)
                self.assertIn("#SBATCH --gres=gpu:1", job_script)

                status_stdout = io.StringIO()
                with contextlib.redirect_stdout(status_stdout):
                    exit_code = main(["runner", "status", "manual-run"])

                self.assertEqual(exit_code, 0)
                printed = json.loads(status_stdout.getvalue())
                self.assertEqual(printed["run_id"], "manual-run")
                self.assertEqual(printed["member_id"], "YOUR_NAME")
                self.assertEqual(printed["paths"]["run_root"], run_dir.as_posix())
                self.assertEqual(printed["assets"]["code"]["source"], "sync")
                self.assertEqual(printed["fetch"]["include"], ["outputs/**", "ckpts/**"])

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

    def test_runner_prepare_exports_structured_asset_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runner_root = temp_path / "trainhub"
            dataset_root = temp_path / "datasets" / "imagenet"
            env_root = temp_path / "shared-env"
            model_root = temp_path / "models" / "bert-base" / "weights"
            dataset_root.mkdir(parents=True)
            (env_root / "bin").mkdir(parents=True)
            model_root.mkdir(parents=True)
            spec_path = temp_path / "spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "version": "2",
                        "project": "vision",
                        "run_name": "smoke",
                        "assets": {
                            "code": {"source": "sync", "path": "."},
                            "dataset": {"source": "shared_path", "path": str(dataset_root)},
                            "env": {"source": "shared_path", "path": str(env_root)},
                            "model": {
                                "source": "shared_path",
                                "path": str(model_root.parent),
                                "subpath": "weights",
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
                "SERVERTOOL_RUNNER_ROOT": str(runner_root),
                "SERVERTOOL_SHARED_CACHE_ROOT": str(temp_path / "shared-cache"),
                "SERVERTOOL_HF_ENDPOINT": "https://hf-mirror.example",
                "SERVERTOOL_MODELSCOPE_ENDPOINT": "https://modelscope-mirror.example",
            }

            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(main(["runner", "prepare", str(spec_path), "--run-id", "manual-run"]), 0)

            launch_script = (runner_root / "projects" / "vision" / "runs" / "manual-run" / "launch.sh").read_text()
            self.assertIn(f"export SERVERTOOL_DATASET_PATH={shlex.quote(dataset_root.as_posix())}", launch_script)
            self.assertIn(f"export SERVERTOOL_ENV_PATH={shlex.quote(env_root.as_posix())}", launch_script)
            self.assertIn(f"export SERVERTOOL_MODEL_PATH={shlex.quote(model_root.as_posix())}", launch_script)
            self.assertIn('export PATH="$SERVERTOOL_ENV_PATH/bin:$PATH"', launch_script)
            self.assertIn(f"export HF_HOME={shlex.quote((temp_path / 'shared-cache' / 'huggingface').as_posix())}", launch_script)
            self.assertIn(
                f"export HF_HUB_CACHE={shlex.quote((temp_path / 'shared-cache' / 'huggingface' / 'hub').as_posix())}",
                launch_script,
            )
            self.assertIn(
                f"export MODELSCOPE_CACHE={shlex.quote((temp_path / 'shared-cache' / 'modelscope').as_posix())}",
                launch_script,
            )
            self.assertIn("export HF_ENDPOINT=https://hf-mirror.example", launch_script)
            self.assertIn("export MODELSCOPE_ENDPOINT=https://modelscope-mirror.example", launch_script)

    def test_prepare_run_assets_builds_shared_env_and_hub_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            shared_env_root = temp_path / "shared" / "envs"
            shared_model_root = temp_path / "shared" / "models"
            shared_cache_root = temp_path / "shared" / "cache"
            project_dir = temp_path / "project"
            project_dir.mkdir()
            (project_dir / "requirements.txt").write_text("requests==2.31.0\n")
            (project_dir / "train.py").write_text("print('hello')\n")
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_SHARED_ENV_ROOT": str(shared_env_root),
                "SERVERTOOL_SHARED_MODEL_ROOT": str(shared_model_root),
                "SERVERTOOL_SHARED_CACHE_ROOT": str(shared_cache_root),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(temp_path)
                spec = RunSpec.from_dict(
                    {
                        "version": "2",
                        "project": "vision",
                        "run_name": "smoke",
                        "assets": {
                            "code": {"source": "sync", "path": "."},
                            "dataset": {"source": "none"},
                            "env": {
                                "source": "build",
                                "type": "pip",
                                "file": "requirements.txt",
                                "name": "Torch 2.3",
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
                    }
                )

                def fake_build_env(_: Config, env_root: Path, build_file: Path) -> None:
                    self.assertEqual(build_file.resolve(), (project_dir / "requirements.txt").resolve())
                    (env_root / "bin").mkdir(parents=True)

                def fake_download_model(_: Config, target_dir: Path, model_id: str, revision: str) -> None:
                    self.assertEqual(model_id, "bert-base-uncased")
                    self.assertEqual(revision, "main")
                    target_dir.mkdir(parents=True)

                with mock.patch("servertool.runner.assets._build_pip_env", side_effect=fake_build_env) as mocked_build:
                    with mock.patch(
                        "servertool.runner.assets._download_huggingface_model",
                        side_effect=fake_download_model,
                    ) as mocked_download:
                        asset_env = prepare_run_assets(config, spec, project_dir)

            self.assertEqual(mocked_build.call_count, 1)
            self.assertEqual(mocked_download.call_count, 1)
            self.assertEqual(asset_env["SERVERTOOL_ENV_PATH"], str(shared_env_root / "torch-2-3"))
            self.assertEqual(
                asset_env["SERVERTOOL_MODEL_PATH"],
                str(shared_model_root / "huggingface" / "bert-base-uncased" / "main"),
            )

    def test_build_conda_env_uses_condarc_for_legacy_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            build_file = temp_path / "environment.yml"
            build_file.write_text("name: manual-env-build\ndependencies:\n  - python=3.9\n")
            env_root = temp_path / "envs" / "manual-env-build"
            shared_cache_root = temp_path / "shared" / "cache"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_SHARED_CACHE_ROOT": str(shared_cache_root),
                "SERVERTOOL_CONDA_CHANNELS": "pytorch,nvidia,conda-forge",
            }

            captured: dict[str, object] = {}

            def fake_run_checked(command: list[str], *, env: dict[str, str]) -> None:
                captured["command"] = list(command)
                captured["condarc_path"] = env.get("CONDARC", "")
                captured["conda_pkgs_dirs"] = env.get("CONDA_PKGS_DIRS", "")
                condarc_path = Path(str(env.get("CONDARC", "")))
                captured["condarc_text"] = condarc_path.read_text()

            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(temp_path)
                with mock.patch("servertool.runner.assets.command_exists", return_value=True):
                    with mock.patch("servertool.runner.assets._run_checked_command", side_effect=fake_run_checked):
                        _build_conda_env(config, env_root, build_file)

            self.assertEqual(
                captured["command"],
                [
                    "conda",
                    "env",
                    "create",
                    "--prefix",
                    env_root.as_posix(),
                    "--file",
                    build_file.as_posix(),
                    "--yes",
                ],
            )
            self.assertEqual(captured["conda_pkgs_dirs"], str(shared_cache_root / "conda"))
            self.assertIn("channels:\n", str(captured["condarc_text"]))
            self.assertIn("  - pytorch\n", str(captured["condarc_text"]))
            self.assertIn("  - nvidia\n", str(captured["condarc_text"]))
            self.assertIn("  - conda-forge\n", str(captured["condarc_text"]))
            self.assertIn("default_channels: []\n", str(captured["condarc_text"]))
            self.assertFalse(Path(str(captured["condarc_path"])).exists())

    def test_prepare_run_assets_cleans_partial_env_root_after_build_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            shared_env_root = temp_path / "shared" / "envs"
            project_dir = temp_path / "project"
            project_dir.mkdir()
            (project_dir / "environment.yml").write_text("name: broken\ndependencies:\n  - python=3.9\n")
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_SHARED_ENV_ROOT": str(shared_env_root),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(temp_path)
                spec = RunSpec.from_dict(
                    {
                        "version": "2",
                        "project": "vision",
                        "run_name": "smoke",
                        "assets": {
                            "code": {"source": "sync", "path": "."},
                            "dataset": {"source": "none"},
                            "env": {
                                "source": "build",
                                "type": "conda",
                                "file": "environment.yml",
                                "name": "Broken Env",
                            },
                            "model": {"source": "none"},
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
                    }
                )

                def fail_build(_: Config, env_root: Path, build_file: Path) -> None:
                    env_root.mkdir(parents=True, exist_ok=True)
                    (env_root / "partial.txt").write_text(build_file.name)
                    raise RuntimeError("conda build failed")

                with mock.patch("servertool.runner.assets._build_conda_env", side_effect=fail_build):
                    with self.assertRaises(RuntimeError):
                        prepare_run_assets(config, spec, project_dir)

            self.assertFalse((shared_env_root / "broken-env").exists())

    def test_prepare_run_assets_cleans_partial_model_root_after_download_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            shared_model_root = temp_path / "shared" / "models"
            project_dir = temp_path / "project"
            project_dir.mkdir()
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_SHARED_MODEL_ROOT": str(shared_model_root),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(temp_path)
                spec = RunSpec.from_dict(
                    {
                        "version": "2",
                        "project": "vision",
                        "run_name": "smoke",
                        "assets": {
                            "code": {"source": "sync", "path": "."},
                            "dataset": {"source": "none"},
                            "env": {"source": "none"},
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
                    }
                )

                def fail_download(_: Config, target_dir: Path, model_id: str, revision: str) -> None:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    (target_dir / "partial.bin").write_text(f"{model_id}@{revision}\n")
                    raise RuntimeError("download failed")

                with mock.patch("servertool.runner.assets._download_huggingface_model", side_effect=fail_download):
                    with self.assertRaises(RuntimeError):
                        prepare_run_assets(config, spec, project_dir)

            self.assertFalse((shared_model_root / "huggingface" / "bert-base-uncased" / "main").exists())

    def test_prepare_run_assets_rejects_hub_model_root_with_mismatched_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            shared_model_root = temp_path / "shared" / "models"
            model_root = shared_model_root / "huggingface" / "bert-base-uncased" / "main"
            model_root.mkdir(parents=True)
            (model_root / "weights.bin").write_text("weights\n")
            (model_root / ".servertool-model-source.json").write_text(
                json.dumps(
                    {
                        "provider": "huggingface",
                        "id": "different-model",
                        "revision": "main",
                    }
                )
                + "\n"
            )
            project_dir = temp_path / "project"
            project_dir.mkdir()
            (project_dir / "train.py").write_text("print('hello')\n")
            env = {
                "SERVERTOOL_CONFIG_FILE": str(temp_path / "config.env"),
                "SERVERTOOL_SHARED_MODEL_ROOT": str(shared_model_root),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(temp_path)
                spec = RunSpec.from_dict(
                    {
                        "version": "2",
                        "project": "vision",
                        "run_name": "smoke",
                        "assets": {
                            "code": {"source": "sync", "path": "."},
                            "dataset": {"source": "none"},
                            "env": {"source": "none"},
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
                    }
                )

                with self.assertRaises(RuntimeError) as error:
                    prepare_run_assets(config, spec, project_dir)

            self.assertIn("different hub metadata", str(error.exception))

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
