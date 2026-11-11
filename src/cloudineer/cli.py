"""Command-line entry point for running a Cloudineer cost assessment.

Usage:
    python -m cloudineer.cli run --customer-config config/customers/example-customer.yaml
    python -m cloudineer.cli run --customer-config <path> --stub   # no real AWS access
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from cloudineer.core.config import load_customer_config
from cloudineer.core.orchestrator import AssessmentOrchestrator
from cloudineer.reports.dashboard_builder import build_dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudineer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run an assessment for one customer")
    run_parser.add_argument(
        "--customer-config", required=True, help="Path to config/customers/<id>.yaml"
    )
    run_parser.add_argument(
        "--stub",
        action="store_true",
        help="Use local/default AWS credentials instead of assuming the customer role "
        "(useful for local development without live cross-account access).",
    )
    run_parser.add_argument(
        "--out", help="Write the dashboard JSON to this file instead of stdout"
    )
    run_parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "run":
        config = load_customer_config(args.customer_config)
        orchestrator = AssessmentOrchestrator(stub_mode=args.stub)
        results = orchestrator.run(config)
        dashboard = build_dashboard(
            customer_id=config.customer_id,
            account_id=config.account_id,
            results=results,
        )
        output = json.dumps(dashboard, indent=2, default=str)
        if args.out:
            with open(args.out, "w") as fh:
                fh.write(output)
        else:
            print(output)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
