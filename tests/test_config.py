import tempfile
import os
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest import mock
from argparse import ArgumentParser


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.config import Config  # noqa: E402
from servertool.context import AppContext  # noqa: E402
from servertool.output import Console  # noqa: E402
from servertool.commands import configure  # noqa: E402


class ConfigDefaultsTest(unittest.TestCase):
    def test_defaults_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.env"
            with mock.patch.dict(os.environ, {"SERVERTOOL_CONFIG_FILE": str(config_file)}, clear=True):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.shared_account, "clusteruser")
            self.assertEqual(config.shared_home, Path("/cluster/home/clusteruser"))
            self.assertEqual(config.workspace_name, "YOUR_NAME")
            self.assertEqual(config.workspace_path, Path("/cluster/home/clusteruser/YOUR_NAME"))
            self.assertEqual(config.auth_url, "https://auth.example.com")
            self.assertEqual(config.network_probe_url, "https://example.com")
            self.assertEqual(config.cache_file, Path.home() / ".cache" / "servertool" / "disk-cache.json")
            self.assertEqual(config.remote_root, "/cluster/home/clusteruser/trainhub")
            self.assertEqual(config.runner_root, Path("/cluster/home/clusteruser/trainhub"))
            self.assertEqual(config.local_run_cache, Path.home() / ".cache" / "servertool" / "runs")
            self.assertEqual(config.notify_email_to, "")
            self.assertEqual(config.remote_host, "")
            self.assertEqual(config.remote_user, "clusteruser")
            self.assertEqual(config.remote_port, "22")
            self.assertEqual(config.remote_python, "python3")
            self.assertEqual(config.ssh_bin, "ssh")
            self.assertEqual(config.rsync_bin, "rsync")
            self.assertEqual(config.rsync_backend, "wsl" if os.name == "nt" else "native")

    def test_local_config_file_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.env"
            config_file.write_text(
                "# local settings\n"
                "export SERVERTOOL_SHARED_ACCOUNT=gpu2003\n"
                "export SERVERTOOL_WORKSPACE_NAME=zanewang\n"
                "export SERVERTOOL_SHARED_HOME=/share/home/gpu2003\n"
                "export SERVERTOOL_AUTH_URL=https://login.internal.example\n"
                "export SERVERTOOL_NETWORK_PROBE_URL=https://probe.internal.example\n"
                "export SERVERTOOL_A40_MAX_TIME='7 days'\n"
                "export SERVERTOOL_QUOTA_LIMIT=500G\n"
                "export SERVERTOOL_REMOTE_ROOT=/share/home/gpu2003/trainhub\n"
                "export SERVERTOOL_REMOTE_HOST=cluster.example.com\n"
                "export SERVERTOOL_REMOTE_PORT=2222\n"
                "export SERVERTOOL_NOTIFY_EMAIL_TO=notify@example.com\n"
            )
            with mock.patch.dict(os.environ, {"SERVERTOOL_CONFIG_FILE": str(config_file)}, clear=True):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.shared_account, "gpu2003")
            self.assertEqual(config.workspace_name, "zanewang")
            self.assertEqual(config.shared_home, Path("/share/home/gpu2003"))
            self.assertEqual(config.workspace_path, Path("/share/home/gpu2003/zanewang"))
            self.assertEqual(config.auth_url, "https://login.internal.example")
            self.assertEqual(config.network_probe_url, "https://probe.internal.example")
            self.assertEqual(config.a40_max_time, "7 days")
            self.assertEqual(config.quota_limit, "500G")
            self.assertEqual(config.remote_root, "/share/home/gpu2003/trainhub")
            self.assertEqual(config.runner_root, Path("/share/home/gpu2003/trainhub"))
            self.assertEqual(config.notify_email_to, "notify@example.com")
            self.assertEqual(config.remote_host, "cluster.example.com")
            self.assertEqual(config.remote_port, "2222")

    def test_environment_can_inject_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.env"
            config_file.write_text("export SERVERTOOL_SHARED_ACCOUNT=ops-base\n")
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_CONFIG_FILE": str(config_file),
                    "SERVERTOOL_SHARED_ACCOUNT": "ops-user",
                    "SERVERTOOL_WORKSPACE_NAME": "member-a",
                    "SERVERTOOL_SHARED_HOME": "/srv/cluster/ops-user",
                    "SERVERTOOL_AUTH_URL": "https://login.internal.example",
                    "SERVERTOOL_NETWORK_PROBE_URL": "https://intranet-probe.example",
                    "SERVERTOOL_CACHE_FILE": "/tmp/servertool/cache.json",
                    "SERVERTOOL_RUNNER_ROOT": "/tmp/servertool/runner-root",
                    "SERVERTOOL_LOCAL_RUN_CACHE": "/tmp/servertool/local-runs",
                    "SERVERTOOL_REMOTE_USER": "ops-user",
                    "SERVERTOOL_REMOTE_HOST": "ops.cluster.internal",
                },
                clear=True,
            ):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.shared_account, "ops-user")
            self.assertEqual(config.workspace_name, "member-a")
            self.assertEqual(config.shared_home, Path("/srv/cluster/ops-user"))
            self.assertEqual(config.auth_url, "https://login.internal.example")
            self.assertEqual(config.network_probe_url, "https://intranet-probe.example")
            self.assertEqual(config.cache_file, Path("/tmp/servertool/cache.json"))
            self.assertEqual(config.runner_root, Path("/tmp/servertool/runner-root"))
            self.assertEqual(config.local_run_cache, Path("/tmp/servertool/local-runs"))
            self.assertEqual(config.remote_user, "ops-user")
            self.assertEqual(config.remote_host, "ops.cluster.internal")

    def test_legacy_remote_env_aliases_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.env"
            with mock.patch.dict(
                os.environ,
                {
                    "SERVERTOOL_CONFIG_FILE": str(config_file),
                    "SERVERIP": "cluster.example.com",
                    "SERVERUSERNAME": "gpu2003",
                    "SERVERPSD": "topsecret",
                },
                clear=True,
            ):
                config = Config.from_root(Path("/tmp/servertool"))

            self.assertEqual(config.remote_host, "cluster.example.com")
            self.assertEqual(config.remote_user, "gpu2003")
            self.assertEqual(config.remote_password, "topsecret")

    def test_numeric_partition_input_is_rejected(self) -> None:
        with mock.patch("builtins.input", side_effect=["12", "A40"]):
            value = configure._prompt_partition("A40 partition name", "A40", "A40 GPUs")
        self.assertEqual(value, "A40")

    def test_show_warns_for_suspicious_values(self) -> None:
        config = Config.from_root(Path("/tmp/servertool"))
        config = replace(config, a40_partition="12", a6000_partition="4")
        context = AppContext(config=config, console=Console(config), topic_parsers={"main": ArgumentParser()})
        with mock.patch.object(context.console, "warn") as warn:
            configure._warn_if_suspicious_config(context)
        self.assertGreaterEqual(warn.call_count, 4)


if __name__ == "__main__":
    unittest.main()
