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

            self.assertEqual(loaded.project, "vision")
            self.assertEqual(loaded.run_name, "baseline")
            self.assertEqual(loaded.notify.email.to, ("notify@example.com",))
            self.assertEqual(loaded.fetch.include, ("outputs/**", "ckpts/**"))

    def test_invalid_spec_is_rejected(self) -> None:
        with self.assertRaises(SpecValidationError):
            RunSpec.from_dict(
                {
                    "version": "1",
                    "project": "demo",
                    "run_name": "broken",
                    "assets": {"code": ".", "env": "", "dataset": "", "model": ""},
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

    def test_spec_init_command_writes_file(self) -> None:
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
            self.assertEqual(payload["project"], "vision")
            self.assertEqual(payload["run_name"], "smoke")
            self.assertEqual(payload["notify"]["email"]["to"], ["notify@example.com"])

    def test_training_smoke_spec_is_valid(self) -> None:
        spec = load_spec(ROOT / "spec.smoke.train.json")
        self.assertEqual(spec.project, "servertool")
        self.assertEqual(spec.run_name, "smoke-train")
        self.assertIn("examples/smoke_train.py", spec.launch.command)
        self.assertTrue((ROOT / "examples" / "smoke_train.py").exists())
