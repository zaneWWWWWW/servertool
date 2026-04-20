import os
from pathlib import Path
import sys
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.config import Config  # noqa: E402


class ConfigDefaultsTest(unittest.TestCase):
    def test_defaults_are_sanitized(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            config = Config.from_root(Path("/tmp/servertool"))

        self.assertEqual(config.shared_account, "clusteruser")
        self.assertEqual(config.shared_home, Path("/cluster/home/clusteruser"))
        self.assertEqual(config.auth_url, "https://auth.example.com")
        self.assertEqual(config.network_probe_url, "https://example.com")
        self.assertEqual(config.cache_file, Path.home() / ".cache" / "servertool" / "disk-cache.json")

    def test_environment_can_inject_private_values(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "SERVERTOOL_SHARED_ACCOUNT": "ops-user",
                "SERVERTOOL_SHARED_HOME": "/srv/cluster/ops-user",
                "SERVERTOOL_AUTH_URL": "https://login.internal.example",
                "SERVERTOOL_NETWORK_PROBE_URL": "https://intranet-probe.example",
                "SERVERTOOL_CACHE_FILE": "/tmp/servertool/cache.json",
            },
            clear=True,
        ):
            config = Config.from_root(Path("/tmp/servertool"))

        self.assertEqual(config.shared_account, "ops-user")
        self.assertEqual(config.shared_home, Path("/srv/cluster/ops-user"))
        self.assertEqual(config.auth_url, "https://login.internal.example")
        self.assertEqual(config.network_probe_url, "https://intranet-probe.example")
        self.assertEqual(config.cache_file, Path("/tmp/servertool/cache.json"))


if __name__ == "__main__":
    unittest.main()
