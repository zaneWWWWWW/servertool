import tempfile
import os
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest import mock
from argparse import ArgumentParser, Namespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.config import Config  # noqa: E402
from servertool.controller import bootstrap as bootstrap_ops  # noqa: E402
from servertool.context import AppContext  # noqa: E402
from servertool.output import Console  # noqa: E402
from servertool.commands import configure, init as init_command  # noqa: E402


class ConfigDefaultsTest(unittest.TestCase):
    def test_default_user_config_uses_user_env_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {"XDG_CONFIG_HOME": temp_dir}
            with mock.patch.dict(os.environ, env, clear=True):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.user_config_file, Path(temp_dir) / "servertool" / "user.env")
            self.assertEqual(config.lab_config_file, Path(temp_dir) / "servertool" / "lab.env")

    def test_defaults_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            user_file = Path(temp_dir) / "user.env"
            with mock.patch.dict(os.environ, {"SERVERTOOL_USER_CONFIG_FILE": str(user_file)}, clear=True):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.user_config_file, user_file)
            self.assertEqual(config.user_config_exists, False)
            self.assertEqual(config.shared_account, "clusteruser")
            self.assertEqual(config.shared_home, Path("/cluster/home/clusteruser"))
            self.assertEqual(config.workspace_name, "YOUR_NAME")
            self.assertEqual(config.member_id, "YOUR_NAME")
            self.assertEqual(config.workspace_path, Path("/cluster/home/clusteruser/YOUR_NAME"))
            self.assertEqual(config.remote_root, "/cluster/home/clusteruser/trainhub")
            self.assertEqual(config.remote_member_root, "/cluster/home/clusteruser/YOUR_NAME/.servertool")
            self.assertEqual(config.shared_env_root, "/cluster/home/clusteruser/trainhub/envs")
            self.assertEqual(config.shared_model_root, "/cluster/home/clusteruser/trainhub/models")
            self.assertEqual(config.shared_cache_root, "/cluster/home/clusteruser/trainhub/cache")
            self.assertEqual(config.remote_runner_install_root.as_posix(), "/cluster/home/clusteruser/trainhub/.runner")
            self.assertEqual(config.notify_email_to, "")
            self.assertEqual(config.remote_host, "")
            self.assertEqual(config.remote_user, "clusteruser")
            self.assertEqual(config.remote_port, "22")
            self.assertEqual(config.remote_python, "python3")
            self.assertEqual(config.ssh_bin, "ssh")
            self.assertEqual(config.rsync_bin, "rsync")
            self.assertEqual(config.rsync_backend, "wsl" if os.name == "nt" else "native")

    def test_user_config_file_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            user_file = Path(temp_dir) / "user.env"
            user_file.write_text(
                "# local settings\n"
                "export SERVERTOOL_WORKSPACE_NAME=zanewang\n"
                "export SERVERTOOL_MEMBER_ID=zw\n"
                "export SERVERTOOL_NOTIFY_EMAIL_TO=notify@example.com\n"
                "export SERVERTOOL_LOCAL_RUN_CACHE=/tmp/servertool-runs\n"
            )
            with mock.patch.dict(os.environ, {"SERVERTOOL_USER_CONFIG_FILE": str(user_file)}, clear=True):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.workspace_name, "zanewang")
            self.assertEqual(config.member_id, "zw")
            self.assertEqual(config.notify_email_to, "notify@example.com")
            self.assertEqual(config.local_run_cache, Path("/tmp/servertool-runs"))

    def test_lab_config_file_is_loaded_as_base_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            user_file = temp_path / "user.env"
            lab_file = temp_path / "lab.env"
            lab_file.write_text(
                "export SERVERTOOL_A40_PARTITION=lab-a40\n"
                "export SERVERTOOL_REMOTE_HOST=lab.cluster.example\n"
                "export SERVERTOOL_REMOTE_PORT=2200\n"
                "export SERVERTOOL_PIP_INDEX_URL=https://mirror.example/simple\n"
            )
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_USER_CONFIG_FILE": str(user_file),
                    "SERVERTOOL_LAB_CONFIG_FILE": str(lab_file),
                },
                clear=True,
            ):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.lab_config_file, lab_file)
            self.assertEqual(config.lab_config_exists, True)
            self.assertEqual(config.a40_partition, "lab-a40")
            self.assertEqual(config.remote_host, "lab.cluster.example")
            self.assertEqual(config.remote_port, "2200")
            self.assertEqual(config.pip_index_url, "https://mirror.example/simple")

    def test_user_config_overrides_lab_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            user_file = temp_path / "user.env"
            lab_file = temp_path / "lab.env"
            lab_file.write_text(
                "export SERVERTOOL_REMOTE_HOST=lab.cluster.example\n"
            )
            user_file.write_text(
                "export SERVERTOOL_NOTIFY_EMAIL_TO=user@example.com\n"
                "export SERVERTOOL_MEMBER_ID=member-a\n"
            )
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_USER_CONFIG_FILE": str(user_file),
                    "SERVERTOOL_LAB_CONFIG_FILE": str(lab_file),
                },
                clear=True,
            ):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.remote_host, "lab.cluster.example")
            self.assertEqual(config.notify_email_to, "user@example.com")
            self.assertEqual(config.member_id, "member-a")

    def test_lab_config_ignores_user_only_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            user_file = temp_path / "user.env"
            lab_file = temp_path / "lab.env"
            lab_file.write_text(
                "export SERVERTOOL_REMOTE_HOST=lab.cluster.example\n"
                "export SERVERTOOL_WORKSPACE_NAME=lab-default\n"
                "export SERVERTOOL_NOTIFY_EMAIL_TO=lab@example.com\n"
            )
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_USER_CONFIG_FILE": str(user_file),
                    "SERVERTOOL_LAB_CONFIG_FILE": str(lab_file),
                },
                clear=True,
            ):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.remote_host, "lab.cluster.example")
            self.assertEqual(config.workspace_name, "YOUR_NAME")
            self.assertEqual(config.notify_email_to, "")

    def test_user_config_ignores_lab_only_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            user_file = temp_path / "user.env"
            user_file.write_text(
                "export SERVERTOOL_MEMBER_ID=member-a\n"
                "export SERVERTOOL_REMOTE_HOST=user.cluster.example\n"
                "export SERVERTOOL_A40_PARTITION=user-a40\n"
            )
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_USER_CONFIG_FILE": str(user_file),
                },
                clear=True,
            ):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.member_id, "member-a")
            self.assertEqual(config.remote_host, "")
            self.assertEqual(config.a40_partition, "A40")

    def test_environment_can_override_both_layers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            user_file = Path(temp_dir) / "user.env"
            user_file.write_text("export SERVERTOOL_WORKSPACE_NAME=old-user\n")
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_USER_CONFIG_FILE": str(user_file),
                    "SERVERTOOL_WORKSPACE_NAME": "member-a",
                    "SERVERTOOL_MEMBER_ID": "member-a-id",
                    "SERVERTOOL_SHARED_HOME": "/srv/cluster/ops-user",
                    "SERVERTOOL_REMOTE_HOST": "ops.cluster.internal",
                    "SERVERTOOL_SHARED_ENV_ROOT": "/srv/shared/envs",
                },
                clear=True,
            ):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.workspace_name, "member-a")
            self.assertEqual(config.member_id, "member-a-id")
            self.assertEqual(config.shared_home, Path("/srv/cluster/ops-user"))
            self.assertEqual(config.remote_host, "ops.cluster.internal")
            self.assertEqual(config.shared_env_root, "/srv/shared/envs")

    def test_show_warns_for_suspicious_values(self) -> None:
        config = Config.from_root(Path("/tmp/servertool"))
        config = replace(config, a40_partition="12", a6000_partition="4")
        context = AppContext(config=config, console=Console(config), topic_parsers={"main": ArgumentParser()})
        with mock.patch.object(context.console, "warn") as warn:
            configure._warn_if_suspicious_config(context)
        self.assertGreaterEqual(warn.call_count, 2)

    def test_init_writes_only_user_scoped_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            user_file = temp_path / "user.env"
            lab_file = temp_path / "lab.env"
            lab_file.write_text(
                "export SERVERTOOL_REMOTE_HOST=lab.cluster.example\n"
                "export SERVERTOOL_A40_PARTITION=lab-a40\n"
                "export SERVERTOOL_SMTP_HOST=smtp.lab.example\n"
            )
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_USER_CONFIG_FILE": str(user_file),
                    "SERVERTOOL_LAB_CONFIG_FILE": str(lab_file),
                },
                clear=True,
            ):
                config = Config.from_root(Path("/tmp/servertool"))
                context = AppContext(config=config, console=Console(config), topic_parsers={"main": ArgumentParser()})
                exit_code = init_command.run(
                    Namespace(
                        workspace_name="zanewang",
                        member_id="zanewang",
                        notify_email="user@example.com",
                        local_run_cache=str(temp_path / "runs"),
                        skip_remote=True,
                    ),
                    context,
                )

            self.assertEqual(exit_code, 0)
            content = user_file.read_text()
            self.assertIn("SERVERTOOL_WORKSPACE_NAME", content)
            self.assertIn("SERVERTOOL_MEMBER_ID", content)
            self.assertIn("SERVERTOOL_NOTIFY_EMAIL_TO", content)
            self.assertIn("SERVERTOOL_LOCAL_RUN_CACHE", content)
            self.assertNotIn("SERVERTOOL_REMOTE_HOST", content)
            self.assertNotIn("SERVERTOOL_A40_PARTITION", content)
            self.assertNotIn("SERVERTOOL_SMTP_HOST", content)

    def test_remote_lab_config_contains_only_lab_managed_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            smtp_file = temp_path / "smtp.env"
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_USER_CONFIG_FILE": str(temp_path / "user.env"),
                    "SERVERTOOL_LAB_CONFIG_FILE": str(temp_path / "lab.env"),
                    "SERVERTOOL_SMTP_SECRETS_FILE": str(smtp_file),
                    "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                    "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                    "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                    "SERVERTOOL_MEMBER_ID": "zw",
                    "SERVERTOOL_NOTIFY_EMAIL_TO": "user@example.com",
                    "SERVERTOOL_PIP_INDEX_URL": "https://mirror.example/simple",
                    "SERVERTOOL_CONDA_CHANNELS": "conda-forge,pytorch",
                    "SERVERTOOL_HF_ENDPOINT": "https://hf-mirror.example",
                    "SERVERTOOL_SHARED_ENV_ROOT": "/share/home/gpu2003/trainhub/envs",
                    "SERVERTOOL_SHARED_MODEL_ROOT": "/share/home/gpu2003/trainhub/models",
                    "SERVERTOOL_SHARED_CACHE_ROOT": "/share/home/gpu2003/trainhub/cache",
                },
                clear=True,
            ):
                config = Config.from_root(Path(__file__).resolve().parents[1] / "src")
                paths = bootstrap_ops.bootstrap_paths(config)
                rendered = bootstrap_ops.render_remote_lab_config(config, paths)

            self.assertIn("SERVERTOOL_PIP_INDEX_URL=https://mirror.example/simple", rendered)
            self.assertIn("SERVERTOOL_CONDA_CHANNELS=conda-forge,pytorch", rendered)
            self.assertIn("SERVERTOOL_HF_ENDPOINT=https://hf-mirror.example", rendered)
            self.assertIn("SERVERTOOL_SHARED_ENV_ROOT=/share/home/gpu2003/trainhub/envs", rendered)
            self.assertIn("SERVERTOOL_SHARED_MODEL_ROOT=/share/home/gpu2003/trainhub/models", rendered)
            self.assertIn("SERVERTOOL_SHARED_CACHE_ROOT=/share/home/gpu2003/trainhub/cache", rendered)
            self.assertNotIn("SERVERTOOL_WORKSPACE_NAME", rendered)
            self.assertNotIn("SERVERTOOL_MEMBER_ID", rendered)
            self.assertNotIn("SERVERTOOL_NOTIFY_EMAIL_TO", rendered)

    def test_remote_member_config_contains_only_user_managed_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_USER_CONFIG_FILE": str(temp_path / "user.env"),
                    "SERVERTOOL_LAB_CONFIG_FILE": str(temp_path / "lab.env"),
                    "SERVERTOOL_SHARED_HOME": "/share/home/gpu2003",
                    "SERVERTOOL_REMOTE_ROOT": "/share/home/gpu2003/trainhub",
                    "SERVERTOOL_WORKSPACE_NAME": "zanewang",
                    "SERVERTOOL_MEMBER_ID": "zw",
                    "SERVERTOOL_NOTIFY_EMAIL_TO": "user@example.com",
                    "SERVERTOOL_A40_PARTITION": "lab-a40",
                    "SERVERTOOL_SHARED_ENV_ROOT": "/share/home/gpu2003/trainhub/envs",
                },
                clear=True,
            ):
                config = Config.from_root(Path(__file__).resolve().parents[1] / "src")
                paths = bootstrap_ops.bootstrap_paths(config)
                rendered = bootstrap_ops.render_remote_member_config(config, paths)

            self.assertIn("SERVERTOOL_WORKSPACE_NAME=zanewang", rendered)
            self.assertIn("SERVERTOOL_MEMBER_ID=zw", rendered)
            self.assertIn("SERVERTOOL_NOTIFY_EMAIL_TO=user@example.com", rendered)
            self.assertIn("SERVERTOOL_REMOTE_MEMBER_ROOT=/share/home/gpu2003/zanewang/.servertool", rendered)
            self.assertNotIn("SERVERTOOL_A40_PARTITION", rendered)
            self.assertNotIn("SERVERTOOL_SHARED_ENV_ROOT", rendered)


if __name__ == "__main__":
    unittest.main()
