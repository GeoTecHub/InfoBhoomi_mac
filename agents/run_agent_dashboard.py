#!/usr/bin/env python3
"""Run the InfoBhoomi Agent QA & Debug Control Center."""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from agent_center.dashboard_server import run_server
from config import AGENT_DASHBOARD_HOST, AGENT_DASHBOARD_PORT


def main():
    parser = argparse.ArgumentParser(description="Run the InfoBhoomi Agent QA & Debug dashboard")
    parser.add_argument("--host", default=AGENT_DASHBOARD_HOST)
    parser.add_argument("--port", type=int, default=AGENT_DASHBOARD_PORT)
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()

