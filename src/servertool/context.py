from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass, field
from typing import Dict

from .config import Config
from .output import Console


@dataclass
class AppContext:
    config: Config
    console: Console
    topic_parsers: Dict[str, ArgumentParser] = field(default_factory=dict)
