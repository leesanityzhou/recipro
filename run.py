from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from recipro.config import load_config
from recipro.core.orchestrator import Orchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Recipro, a dual-agent code improvement loop."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the Recipro config file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Override config and skip repository mutations, pushes, and PR creation.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    config = load_config(Path(args.config))
    if args.dry_run:
        config = config.with_overrides(dry_run=True)

    orchestrator = Orchestrator(config)
    report_path = orchestrator.run()
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

