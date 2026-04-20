from __future__ import annotations

import sys

from .config import Config


class Console:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.use_color = sys.stdout.isatty()
        if self.use_color:
            self.red = "\033[0;31m"
            self.green = "\033[0;32m"
            self.yellow = "\033[1;33m"
            self.blue = "\033[0;34m"
            self.reset = "\033[0m"
        else:
            self.red = ""
            self.green = ""
            self.yellow = ""
            self.blue = ""
            self.reset = ""

    def header(self, title: str) -> None:
        print(f"{self.blue}=================================================={self.reset}")
        print(f"{self.blue}       {title}{self.reset}")
        print(f"{self.blue}=================================================={self.reset}\n")

    def section(self, index: str, title: str) -> None:
        print(f"{self.yellow}[{index}] {title}{self.reset}")
        print("---------------------------------------------------")

    def ok(self, message: str) -> None:
        print(f"{self.green}[OK]{self.reset} {message}")

    def fail(self, message: str) -> None:
        print(f"{self.red}[FAIL]{self.reset} {message}")

    def warn(self, message: str) -> None:
        print(f"{self.yellow}[WARN]{self.reset} {message}")

    def info(self, message: str) -> None:
        print(f"  {message}")

    def footer(self) -> None:
        print(f"{self.blue}--------------------------------------------------{self.reset}")
        print(f"  Author: {self.green}{self.config.author}{self.reset} | Version: {self.config.version}\n")
