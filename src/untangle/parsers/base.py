"""The ecosystem-parser contract.

A parser is a module (see ``parsers/__init__.py`` for the registry) exposing:

    name: str                                                  # ecosystem id
    def parse(repo_dir: Path, patterns: DetectionPatterns) -> ParseResult

Each parser owns one ecosystem's file formats and returns everything it found
as a ``ParseResult``; the orchestrator merges results in registry order. To add
support for a new ecosystem (Go modules, Cargo, Maven…), write one module with
those two attributes and append it to ``PARSERS``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParseResult:
    """Everything one ecosystem parser discovered in a repo.

    ``ecosystems``       ecosystem ids to tag the project with (usually 0 or 1).
    ``manifest``         report manifest sections: section name -> entries.
                         Entries are dicts like ``{"name", "raw"|"version", "source"}``
                         for packages or ``{"image", "source"[, "service"]}`` for images.
    ``internal``         internal dependency records: ``{"target", "type", "source", ...}``.
    ``shared_networks``  docker-compose network names (cross-repo infra signal).
    """

    ecosystems: list[str] = field(default_factory=list)
    manifest: dict[str, list] = field(default_factory=dict)
    internal: list[dict] = field(default_factory=list)
    shared_networks: list[str] = field(default_factory=list)

    def merge(self, other: ParseResult) -> None:
        for eco in other.ecosystems:
            if eco not in self.ecosystems:
                self.ecosystems.append(eco)
        for section, entries in other.manifest.items():
            self.manifest.setdefault(section, []).extend(entries)
        self.internal.extend(other.internal)
        self.shared_networks.extend(other.shared_networks)
