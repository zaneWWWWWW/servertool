import contextlib
import io
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servertool.app import main  # noqa: E402


class LegacyCommandRemovalTest(unittest.TestCase):
    def test_removed_local_helper_commands_fail_to_parse(self) -> None:
        for command in ("quickstart", "status", "jobs", "disk", "request", "test"):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exit_error:
                    main([command])

            self.assertEqual(exit_error.exception.code, 2)
            self.assertIn(command, stderr.getvalue())
