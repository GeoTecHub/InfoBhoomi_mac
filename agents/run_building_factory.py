#!/usr/bin/env python3
"""
InfoBhoomi Building Factory — CLI runner
=========================================

Creates buildings, seeds attributes, and fills RRR for all land + buildings.
Optionally also creates apartment units (layer_id=12) for each new building.

Usage
-----
  python run_building_factory.py                       # create 1000 buildings, full run
  python run_building_factory.py --count 200           # create 200 buildings
  python run_building_factory.py --dry-run             # simulate without writing anything
  python run_building_factory.py --skip-land-rrr       # skip RRR for existing land parcels
  python run_building_factory.py --skip-attrs          # skip attribute seeding
  python run_building_factory.py --skip-rrr            # skip all RRR seeding
  python run_building_factory.py --limit 50            # cap land-parcel RRR phase at 50
  python run_building_factory.py --count 0 --skip-attrs  # only fill missing land RRR
  python run_building_factory.py --create-apt-units    # also create apartment units

.env file (agents/.env)
-----------------------
  IB_BASE_URL=http://127.0.0.1:8000/api/user
  IB_TOKEN=<your auth token>         # preferred
  IB_USERNAME=admin_bw               # fallback (login)
  IB_PASSWORD=<password>
"""

import argparse
import sys
import os

# Allow running as  python run_building_factory.py  from the agents/ directory
sys.path.insert(0, os.path.dirname(__file__))

from agents.building_factory_agent import BuildingFactoryAgent


def main():
    parser = argparse.ArgumentParser(
        description="InfoBhoomi Building Factory — creates buildings and seeds data"
    )
    parser.add_argument(
        "--count", type=int, default=1000,
        help="Number of buildings to create (default: 1000)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulate the run without writing any data",
    )
    parser.add_argument(
        "--skip-land-rrr", action="store_true",
        help="Skip RRR seeding for existing land parcels",
    )
    parser.add_argument(
        "--skip-attrs", action="store_true",
        help="Skip attribute seeding for newly created buildings",
    )
    parser.add_argument(
        "--skip-rrr", action="store_true",
        help="Skip all RRR seeding (both buildings and land parcels)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap the number of parcels processed in the RRR phase",
    )
    parser.add_argument(
        "--seed-bld-rrr", action="store_true",
        help="Seed RRR for all existing buildings that don't have one yet",
    )
    parser.add_argument(
        "--create-apt-units", action="store_true",
        help="Create apartment units (layer_id=12) for each newly created building",
    )
    args = parser.parse_args()

    agent = BuildingFactoryAgent(
        count             = args.count,
        dry_run           = args.dry_run,
        skip_land_rrr     = args.skip_land_rrr,
        skip_attrs        = args.skip_attrs,
        skip_rrr          = args.skip_rrr,
        seed_bld_rrr      = args.seed_bld_rrr,
        create_apt_units  = args.create_apt_units,
        limit             = args.limit,
    )
    agent.run()


if __name__ == "__main__":
    main()
