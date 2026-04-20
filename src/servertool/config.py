from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from . import __version__


def _default_cache_file() -> Path:
    cache_root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")).expanduser()
    return cache_root / "servertool" / "disk-cache.json"


@dataclass(frozen=True)
class Config:
    name: str
    version: str
    author: str
    root: Path
    shared_account: str
    shared_home: Path
    auth_url: str
    network_probe_url: str
    a40_partition: str
    a6000_partition: str
    default_compute_host: str
    a40_max_time: str
    a6000_max_time: str
    quota_limit: str
    cache_file: Path
    test_output_dir: Path
    install_path: str

    @classmethod
    def from_root(cls, root: Path) -> "Config":
        shared_account = os.getenv("SERVERTOOL_SHARED_ACCOUNT", "clusteruser")
        shared_home = Path(os.getenv("SERVERTOOL_SHARED_HOME", f"/cluster/home/{shared_account}")).expanduser()

        return cls(
            name=os.getenv("SERVERTOOL_NAME", "servertool"),
            version=os.getenv("SERVERTOOL_VERSION", __version__),
            author=os.getenv("SERVERTOOL_AUTHOR", "zanewang"),
            root=root,
            shared_account=shared_account,
            shared_home=shared_home,
            auth_url=os.getenv("SERVERTOOL_AUTH_URL", "https://auth.example.com"),
            network_probe_url=os.getenv("SERVERTOOL_NETWORK_PROBE_URL", "https://example.com"),
            a40_partition=os.getenv("SERVERTOOL_A40_PARTITION", "A40"),
            a6000_partition=os.getenv("SERVERTOOL_A6000_PARTITION", "A6000"),
            default_compute_host=os.getenv("SERVERTOOL_DEFAULT_COMPUTE_HOST", "compute01"),
            a40_max_time=os.getenv("SERVERTOOL_A40_MAX_TIME", "15 days"),
            a6000_max_time=os.getenv("SERVERTOOL_A6000_MAX_TIME", "25 days"),
            quota_limit=os.getenv("SERVERTOOL_QUOTA_LIMIT", "300G"),
            cache_file=Path(os.getenv("SERVERTOOL_CACHE_FILE", str(_default_cache_file()))).expanduser(),
            test_output_dir=Path(os.getenv("SERVERTOOL_TEST_OUTPUT_DIR", "/tmp/servertool")).expanduser(),
            install_path=os.getenv(
                "SERVERTOOL_INSTALL_PATH",
                "/usr/local/bin/servertool",
            ),
        )

    @property
    def gpu_partitions(self) -> tuple[str, str]:
        return (self.a40_partition, self.a6000_partition)

    def partition_max_time(self, partition: str) -> str:
        if partition == self.a6000_partition:
            return self.a6000_max_time
        return self.a40_max_time

    def recommended_request(self) -> list[str]:
        return [
            "srun",
            "-p",
            self.a40_partition,
            "-N",
            "1",
            "-n",
            "8",
            "--mem=32G",
            "--gres=gpu:1",
            "--pty",
            "bash",
            "-i",
        ]
