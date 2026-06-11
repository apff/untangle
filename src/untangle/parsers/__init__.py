"""Ecosystem parser registry.

To add an ecosystem: create a module in this package exposing ``name`` and
``parse(repo_dir, patterns) -> ParseResult`` (see ``base.py`` for the contract),
then append it here. Registry order is the order ecosystems/dependencies appear
in the report.
"""

from __future__ import annotations

from . import docker, gitlab_ci, nodejs, python, terraform
from .base import ParseResult

PARSERS = [python, nodejs, docker, gitlab_ci, terraform]

__all__ = ["PARSERS", "ParseResult"]
