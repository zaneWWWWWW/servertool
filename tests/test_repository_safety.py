from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
TEXT_FILE_NAMES = {".env.example", ".gitignore", "LICENSE", "pyproject.toml", "servertool", "README.md", "README.zh-CN.md"}
TEXT_FILE_SUFFIXES = {".md", ".py", ".toml"}
DISALLOWED_RELEASE_PATHS = {
    "architecture_and_training_flow.md",
    "architecture_and_training_flow.zh-CN.md",
    "manual-test",
    "plan.md",
    "spec.smoke.json",
    "改进计划.md",
    "新版本设计定稿.md",
    "框架方案.md",
    "项目报告.md",
}


def iter_repository_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name in TEXT_FILE_NAMES or path.suffix in TEXT_FILE_SUFFIXES:
            files.append(path)
    return files


class RepositorySafetyTest(unittest.TestCase):
    def test_repository_contains_no_literal_ipv4_addresses(self) -> None:
        offenders: list[str] = []
        for path in iter_repository_text_files():
            content = path.read_text()
            if IPV4_PATTERN.search(content):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"Remove literal IPv4 addresses from: {', '.join(offenders)}")

    def test_repository_excludes_release_draft_files(self) -> None:
        offenders = sorted(name for name in DISALLOWED_RELEASE_PATHS if (ROOT / name).exists())
        self.assertEqual(offenders, [], f"Remove draft or retired release paths: {', '.join(offenders)}")


if __name__ == "__main__":
    unittest.main()
