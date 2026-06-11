"""Command-line entry point: ``untangle {clone,analyze,report,all}``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from . import analyze, clone, report
from .config import Settings
from .patterns import DetectionPatterns
from .providers import build_providers, origin_hosts
from .static_config import load_app_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="untangle",
        description="Map and explore internal dependencies across your git repositories.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_clone = sub.add_parser("clone", help="Clone/update all configured repos (shallow)")
    p_clone.add_argument("--dry-run", action="store_true", help="List repos without cloning")

    sub.add_parser("analyze", help="Analyze cloned repos -> dependency_report.json")
    sub.add_parser("report", help="Generate human-facing reports from the analysis")

    p_all = sub.add_parser("all", help="Run clone -> analyze -> report")
    p_all.add_argument("--dry-run", action="store_true", help="Dry-run the clone step")
    p_all.add_argument(
        "--skip-report",
        action="store_true",
        help="Skip the human-facing reports (the webapp only needs the JSON)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Plain messages on stdout, interleaving cleanly with the remaining prints.
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    load_dotenv()  # load a local .env into the environment (no-op in CI/containers)
    settings = Settings.from_env()
    app_config = load_app_config()
    # Providers may be empty: analyze/report work from an existing clone cache.
    providers = build_providers(app_config, os.environ)
    patterns = DetectionPatterns.from_config(app_config.get("detection"), origin_hosts(providers))

    if args.command == "clone":
        return clone.run(settings, providers, dry_run=args.dry_run)
    if args.command == "analyze":
        return analyze.run(settings, patterns)
    if args.command == "report":
        return report.run(settings)
    if args.command == "all":
        # A few failed repos are tolerated (Settings.max_clone_failure_ratio), but a
        # non-zero clone means the failure share blew past that threshold — a likely
        # outage — so abort rather than publish a degraded graph.
        rc = clone.run(settings, providers, dry_run=args.dry_run)
        if args.dry_run:
            return rc
        if rc != 0:
            return rc
        rc = analyze.run(settings, patterns)
        if rc != 0:
            return rc
        if not args.skip_report:
            rc = report.run(settings)
        return rc

    return 2  # unreachable: subparser is required


if __name__ == "__main__":
    raise SystemExit(main())
