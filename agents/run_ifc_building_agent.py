#!/usr/bin/env python3
"""
InfoBhoomi IFC Building Agent - CLI runner

Usage:
  python run_ifc_building_agent.py
  python run_ifc_building_agent.py --spec ..\\3D-Cadastre\\IFC\\ifc_building_agent_sample_spec.json
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from agents.ifc_building_agent import IfcBuildingAgent, IfcBuildingSpec, load_spec


def ask_text(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def ask_int(prompt: str, default: int) -> int:
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            parsed = int(value)
        except ValueError:
            print("Enter a whole number.")
            continue
        if parsed < 1:
            print("Enter a number greater than zero.")
            continue
        return parsed


def ask_float(prompt: str, default: float, minimum: float | None = None) -> float:
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            parsed = float(value)
        except ValueError:
            print("Enter a number.")
            continue
        if minimum is not None and parsed < minimum:
            print(f"Enter a number greater than or equal to {minimum}.")
            continue
        return parsed


def interactive_spec() -> IfcBuildingSpec:
    print("InfoBhoomi IFC Building Agent")
    print("Creates building-only IFC. The selected land parcel is stored as a database ID reference.")
    print()

    parcel_id = ask_text(
        "Parcel ID from the database where this 3D building should be created",
        "DB-LAND-PARCEL-ID-001",
    )
    storeys = ask_int("Number of floors/storeys", 3)
    units_per_storey = ask_int("Units in each floor", 3)
    building_name = ask_text("Building name", "InfoBhoomi IFC Building")
    output_name = ask_text("Output file name", "agent_generated_ifc_building")

    origin_latitude = ask_float("WGS84 latitude of local origin", 6.927079)
    origin_longitude = ask_float("WGS84 longitude of local origin", 79.861244)
    origin_height_m = ask_float("Origin height in metres", 10.0)
    building_width_m = ask_float("Building footprint width in metres", 18.0, minimum=0.01)
    building_length_m = ask_float("Building footprint length in metres", 12.0, minimum=0.01)
    offset_east_m = ask_float("Building local origin east offset in metres", 0.0, minimum=0.0)
    offset_north_m = ask_float("Building local origin north offset in metres", 0.0, minimum=0.0)

    return IfcBuildingSpec(
        parcel_id=parcel_id,
        building_name=building_name,
        output_name=output_name,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
        origin_height_m=origin_height_m,
        building_width_m=building_width_m,
        building_length_m=building_length_m,
        building_offset_east_m=offset_east_m,
        building_offset_north_m=offset_north_m,
        storeys=storeys,
        units_per_storey=units_per_storey,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a building-only IFC4 model linked to an InfoBhoomi database parcel ID."
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="Optional JSON spec file. When omitted, the agent asks for values interactively.",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Override output filename stem without extension.",
    )
    args = parser.parse_args()

    spec = load_spec(args.spec) if args.spec else interactive_spec()
    if args.output_name:
        spec.output_name = args.output_name

    ifc_path, metadata_path = IfcBuildingAgent(spec).create_ifc()
    print(f"IFC created: {ifc_path}")
    print(f"Metadata created: {metadata_path}")


if __name__ == "__main__":
    main()
