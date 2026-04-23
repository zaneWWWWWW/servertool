import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.app import main  # noqa: E402
from servertool.config import Config  # noqa: E402
from servertool.spec import RunSpec, SpecValidationError, load_spec, write_spec  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class RunSpecTest(unittest.TestCase):
    def test_default_spec_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_NOTIFY_EMAIL_TO": "notify@example.com",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(Path("/tmp/servertool"))

            spec = RunSpec.defaults(config, project="vision", run_name="baseline")
            spec.validate()
            spec_path = Path(temp_dir) / "spec.json"
            write_spec(spec_path, spec)
            loaded = load_spec(spec_path)

            self.assertEqual(loaded.version, "2")
            self.assertEqual(loaded.project, "vision")
            self.assertEqual(loaded.run_name, "baseline")
            self.assertEqual(loaded.assets.code.source, "sync")
            self.assertEqual(loaded.assets.code.path, ".")
            self.assertEqual(loaded.assets.dataset.source, "none")
            self.assertEqual(loaded.assets.env.source, "none")
            self.assertEqual(loaded.assets.model.source, "none")
            self.assertEqual(loaded.notify.email.to, ("notify@example.com",))
            self.assertEqual(loaded.fetch.include, ("outputs/**", "ckpts/**"))

    def test_structured_asset_spec_round_trip(self) -> None:
        spec = RunSpec.from_dict(
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
                        "name": "torch2.3-cu121",
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
                "notify": {"email": {"enabled": True, "to": ["notify@example.com"]}},
            }
        )

        self.assertEqual(spec.assets.dataset.source, "shared_path")
        self.assertEqual(spec.assets.dataset.path, "/share/datasets/imagenet")
        self.assertEqual(spec.assets.env.source, "build")
        self.assertEqual(spec.assets.env.build_type, "pip")
        self.assertEqual(spec.assets.env.file, "requirements.txt")
        self.assertEqual(spec.assets.env.name, "torch2.3-cu121")
        self.assertEqual(spec.assets.model.source, "hub")
        self.assertEqual(spec.assets.model.provider, "huggingface")
        self.assertEqual(spec.assets.model.model_id, "bert-base-uncased")

    def test_invalid_structured_assets_are_rejected(self) -> None:
        with self.assertRaises(SpecValidationError):
            RunSpec.from_dict(
                {
                    "version": "2",
                    "project": "demo",
                    "run_name": "broken",
                    "assets": {
                        "code": {"source": "copy", "path": "."},
                        "dataset": {"source": "sync", "path": ""},
                        "env": {"source": "build", "type": "pip"},
                        "model": {"source": "hub", "provider": "hf"},
                    },
                    "launch": {
                        "scheduler": "local",
                        "partition": "A40",
                        "gpus": 0,
                        "cpus": 8,
                        "mem": "32G",
                        "time": "01:00:00",
                        "workdir": ".",
                        "command": "python train.py",
                    },
                    "fetch": {"include": []},
                    "notify": {"email": {"enabled": True, "to": []}},
                }
            )

    def test_shared_paths_and_fetch_patterns_require_remote_safe_values(self) -> None:
        with self.assertRaises(SpecValidationError) as error:
            RunSpec.from_dict(
                {
                    "version": "2",
                    "project": "demo",
                    "run_name": "broken-paths",
                    "assets": {
                        "code": {"source": "sync", "path": "."},
                        "dataset": {"source": "shared_path", "path": "datasets/imagenet"},
                        "env": {"source": "shared_path", "path": "envs/torch"},
                        "model": {
                            "source": "shared_path",
                            "path": "models/bert",
                            "subpath": "../weights",
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
                    "fetch": {"include": ["/outputs/**", "../ckpts/**"]},
                    "notify": {"email": {"enabled": False, "to": []}},
                }
            )

        message = str(error.exception)
        self.assertIn("assets.dataset.path must be an absolute remote path", message)
        self.assertIn("assets.env.path must be an absolute remote path", message)
        self.assertIn("assets.model.path must be an absolute remote path", message)
        self.assertIn("assets.model.subpath must not escape the resolved model root", message)
        self.assertIn("fetch.include entries must be relative to the run root", message)
        self.assertIn("fetch.include entries must not escape the run root", message)

    def test_spec_init_command_writes_structured_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            spec_path = Path(temp_dir) / "spec.json"
            env = {
                "SERVERTOOL_CONFIG_FILE": str(Path(temp_dir) / "config.env"),
                "SERVERTOOL_NOTIFY_EMAIL_TO": "notify@example.com",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main([
                        "spec",
                        "init",
                        str(spec_path),
                        "--project",
                        "vision",
                        "--run-name",
                        "smoke",
                    ])

            self.assertEqual(exit_code, 0)
            payload = json.loads(spec_path.read_text())
            self.assertEqual(payload["version"], "2")
            self.assertEqual(payload["project"], "vision")
            self.assertEqual(payload["run_name"], "smoke")
            self.assertEqual(payload["assets"]["code"], {"source": "sync", "path": "."})
            self.assertEqual(payload["assets"]["dataset"], {"source": "none"})
            self.assertEqual(payload["assets"]["env"], {"source": "none"})
            self.assertEqual(payload["assets"]["model"], {"source": "none"})
            self.assertEqual(payload["notify"]["email"]["to"], ["notify@example.com"])

    def test_training_smoke_spec_is_valid(self) -> None:
        spec = load_spec(ROOT / "spec.smoke.train.json")
        self.assertEqual(spec.project, "servertool")
        self.assertEqual(spec.run_name, "smoke-train")
        self.assertEqual(spec.assets.code.source, "sync")
        self.assertEqual(spec.assets.code.path, ".")
        self.assertIn("examples/smoke_train.py", spec.launch.command)
        self.assertTrue((ROOT / "examples" / "smoke_train.py").exists())


if __name__ == "__main__":
    unittest.main()
