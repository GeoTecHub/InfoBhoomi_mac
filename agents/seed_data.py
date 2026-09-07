"""
InfoBhoomi Data Seeder — Runner
================================
Standalone script to fill missing attribute data for all land parcels
and buildings. Run from the agents/ directory.

Examples:
    python seed_data.py                   # fill all missing data
    python seed_data.py --dry-run         # preview what would be filled
    python seed_data.py --force           # overwrite even existing data
    python seed_data.py --layer 1         # only process layer_id=1
    python seed_data.py --land-only --su-id 12505  # seed one land parcel
    python seed_data.py --limit 20        # process at most 20 features (spread across types)
    python seed_data.py --dry-run --limit 5   # preview first 5 features
    python seed_data.py --rrr             # also create RRR (owners/leases/mortgages)
    python seed_data.py --no-verify       # skip read-back verification (faster)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser(
        description="Seed missing attribute data for InfoBhoomi land parcels and buildings."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be filled without writing anything to the DB."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-fill attribute tables even when data already exists."
    )
    parser.add_argument(
        "--layer", type=int, default=None, metavar="LAYER_ID",
        help="Only process features from this layer_id (e.g. 1=land, 3=building)."
    )
    parser.add_argument(
        "--su-id", type=int, action="append", default=None, metavar="SU_ID",
        help="Only process this spatial unit ID. Repeat for multiple IDs."
    )
    parser.add_argument(
        "--land-only", action="store_true",
        help="Shortcut for --layer 1. Use --layer 6 if your land parcels are on layer 6."
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Stop after processing N features (distributed across land/buildings/units)."
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip reading each write back. Faster, but cannot detect silently-"
             "rejected PATCHes (e.g. missing edit permission)."
    )
    parser.add_argument(
        "--rrr", action="store_true",
        help="Also create Rights/Restrictions/Responsibilities (builds a party pool first)."
    )
    args = parser.parse_args()
    layer = 1 if args.land_only and args.layer is None else args.layer

    try:
        from agents.data_seeder_agent import DataSeederAgent
    except ModuleNotFoundError as exc:
        missing = exc.name or "a required package"
        print(f"Missing dependency: {missing}")
        print("Install the agent dependencies first:")
        print("  pip install -r requirements.txt")
        sys.exit(1)

    agent = DataSeederAgent(
        dry_run    = args.dry_run,
        force      = args.force,
        only_layer = layer,
        limit      = args.limit,
        only_su_ids = args.su_id,
        verify     = not args.no_verify,
        with_rrr   = args.rrr,
    )
    agent.run()


if __name__ == "__main__":
    main()
