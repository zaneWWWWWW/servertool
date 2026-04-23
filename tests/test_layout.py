from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.layout import build_run_id, build_run_layout  # noqa: E402


class RunLayoutTest(unittest.TestCase):
    def test_build_run_id_slugifies_run_name(self) -> None:
        run_id = build_run_id(
            "ResNet 50 / LR=1e-3",
            now=datetime(2026, 4, 21, 12, 34, 56, tzinfo=timezone.utc),
            submitted_by="Zane Wang",
            token="abc123",
        )
        self.assertEqual(run_id, "20260421-123456-zane-wang-resnet-50-lr-1e-3-abc123")

    def test_build_run_layout_uses_posix_paths(self) -> None:
        layout = build_run_layout(
            PurePosixPath("/share/home/gpu2003/zanewang/.servertool"),
            "Vision Project",
            "20260421-123456-smoke",
        )
        self.assertEqual(layout.project_slug, "vision-project")
        self.assertEqual(
            layout.project_root,
            PurePosixPath("/share/home/gpu2003/zanewang/.servertool/projects/vision-project"),
        )
        self.assertEqual(
            layout.run_root,
            PurePosixPath("/share/home/gpu2003/zanewang/.servertool/projects/vision-project/runs/20260421-123456-smoke"),
        )
        self.assertEqual(
            layout.status_path,
            PurePosixPath(
                "/share/home/gpu2003/zanewang/.servertool/projects/vision-project/runs/20260421-123456-smoke/status.json"
            ),
        )
