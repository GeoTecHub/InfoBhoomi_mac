"""
InfoBhoomi IFC Building Agent
=============================

Creates simple IFC4 building artifacts for 3D cadastre testing:

- building-only IFC model; no land parcel geometry is created
- WGS84 site anchor plus building local metre coordinates
- one building with configurable storeys
- apartment/unit IfcSpace objects per storey
- lightweight walls and slabs for viewer/converter testing
- companion JSON metadata for GIS/API use
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.guid


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "3D-Cadastre" / "IFC"


@dataclass
class IfcBuildingSpec:
    parcel_id: str = "DB-LAND-PARCEL-ID-001"
    building_name: str = "InfoBhoomi IFC Building"
    output_name: str = "agent_generated_ifc_building"
    output_dir: Path = DEFAULT_OUTPUT_DIR
    origin_latitude: float = 6.927079
    origin_longitude: float = 79.861244
    origin_height_m: float = 10.0
    building_width_m: float = 18.0
    building_length_m: float = 12.0
    building_offset_east_m: float = 0.0
    building_offset_north_m: float = 0.0
    storeys: int = 3
    units_per_storey: int = 3
    storey_height_m: float = 3.2
    space_height_m: float = 3.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IfcBuildingSpec":
        values = dict(data)
        # Older specs included parcel dimensions when this agent also created parcel geometry.
        values.pop("parcel_width_m", None)
        values.pop("parcel_length_m", None)
        if "output_dir" in values:
            values["output_dir"] = Path(values["output_dir"])
        return cls(**values)

    def normalized_output_name(self) -> str:
        return Path(self.output_name).stem

    def validate(self) -> None:
        if self.storeys < 1:
            raise ValueError("storeys must be at least 1")
        if self.units_per_storey < 1:
            raise ValueError("units_per_storey must be at least 1")
        if not str(self.parcel_id).strip():
            raise ValueError("parcel_id must reference the database land parcel")
        if self.building_width_m <= 0 or self.building_length_m <= 0:
            raise ValueError("building dimensions must be positive")
        if self.building_offset_east_m < 0 or self.building_offset_north_m < 0:
            raise ValueError("building offsets cannot be negative")


class IfcBuildingAgent:
    def __init__(self, spec: IfcBuildingSpec | None = None):
        self.spec = spec or IfcBuildingSpec()
        self.model: ifcopenshell.file | None = None
        self.body_context = None

    @staticmethod
    def guid() -> str:
        return ifcopenshell.guid.new()

    @staticmethod
    def dms(value: float) -> tuple[int, int, int, int]:
        degrees = int(abs(value))
        minutes_float = (abs(value) - degrees) * 60.0
        minutes = int(minutes_float)
        seconds_float = (minutes_float - minutes) * 60.0
        seconds = int(seconds_float)
        millionths = int(round((seconds_float - seconds) * 1_000_000))
        if value < 0:
            degrees = -degrees
        return degrees, minutes, seconds, millionths

    def local_to_wgs84(self, east_m: float, north_m: float) -> tuple[float, float]:
        meters_per_degree_lat = 110_574.0
        meters_per_degree_lon = 111_320.0 * math.cos(math.radians(self.spec.origin_latitude))
        lat = self.spec.origin_latitude + north_m / meters_per_degree_lat
        lon = self.spec.origin_longitude + east_m / meters_per_degree_lon
        return round(lat, 8), round(lon, 8)

    def axis(self, x=0.0, y=0.0, z=0.0):
        assert self.model is not None
        point = self.model.create_entity("IfcCartesianPoint", (float(x), float(y), float(z)))
        axis = self.model.create_entity("IfcDirection", (0.0, 0.0, 1.0))
        ref = self.model.create_entity("IfcDirection", (1.0, 0.0, 0.0))
        return self.model.create_entity("IfcAxis2Placement3D", point, axis, ref)

    def placement(self, parent, x=0.0, y=0.0, z=0.0):
        assert self.model is not None
        return self.model.create_entity("IfcLocalPlacement", parent, self.axis(x, y, z))

    def rect_shape(self, width_m: float, length_m: float, height_m: float):
        assert self.model is not None
        profile = self.model.create_entity(
            "IfcRectangleProfileDef", "AREA", None, None, float(width_m), float(length_m)
        )
        solid = self.model.create_entity(
            "IfcExtrudedAreaSolid",
            profile,
            self.axis(),
            self.model.create_entity("IfcDirection", (0.0, 0.0, 1.0)),
            float(height_m),
        )
        shape_rep = self.model.create_entity(
            "IfcShapeRepresentation", self.body_context, "Body", "SweptSolid", (solid,)
        )
        return self.model.create_entity("IfcProductDefinitionShape", None, None, (shape_rep,))

    def nominal_value(self, value: Any):
        assert self.model is not None
        if isinstance(value, bool):
            return self.model.create_entity("IfcBoolean", value)
        if isinstance(value, int):
            return self.model.create_entity("IfcInteger", value)
        if isinstance(value, float):
            return self.model.create_entity("IfcReal", value)
        if isinstance(value, str):
            return self.model.create_entity("IfcText", value)
        return self.model.create_entity("IfcText", json.dumps(value))

    def property_set(self, name: str, values: dict[str, Any]):
        assert self.model is not None
        props = [
            self.model.create_entity(
                "IfcPropertySingleValue", key, None, self.nominal_value(value), None
            )
            for key, value in values.items()
        ]
        return self.model.create_entity("IfcPropertySet", self.guid(), None, name, None, props)

    def attach_properties(self, product, name: str, values: dict[str, Any]) -> None:
        assert self.model is not None
        self.model.create_entity(
            "IfcRelDefinesByProperties",
            self.guid(),
            None,
            None,
            None,
            (product,),
            self.property_set(name, values),
        )

    def building_footprint_vertices(self) -> list[tuple[float, float]]:
        s = self.spec
        east = s.building_offset_east_m
        north = s.building_offset_north_m
        return [
            (east, north),
            (east + s.building_width_m, north),
            (east + s.building_width_m, north + s.building_length_m),
            (east, north + s.building_length_m),
            (east, north),
        ]

    def building_footprint_metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "local_m": {"east": east, "north": north, "height": self.spec.origin_height_m},
                "wgs84": {
                    "latitude": self.local_to_wgs84(east, north)[0],
                    "longitude": self.local_to_wgs84(east, north)[1],
                    "height_m": self.spec.origin_height_m,
                },
            }
            for east, north in self.building_footprint_vertices()
        ]

    def create_project_context(self):
        s = self.spec
        self.model = ifcopenshell.file(schema="IFC4")
        metre = self.model.create_entity("IfcSIUnit", None, "LENGTHUNIT", None, "METRE")
        square_metre = self.model.create_entity("IfcSIUnit", None, "AREAUNIT", None, "SQUARE_METRE")
        cubic_metre = self.model.create_entity("IfcSIUnit", None, "VOLUMEUNIT", None, "CUBIC_METRE")
        units = self.model.create_entity("IfcUnitAssignment", (metre, square_metre, cubic_metre))
        context = self.model.create_entity(
            "IfcGeometricRepresentationContext", None, "Model", 3, 1.0e-5, self.axis(), None
        )
        self.body_context = self.model.create_entity(
            "IfcGeometricRepresentationSubContext",
            "Body",
            "Model",
            None,
            None,
            None,
            None,
            context,
            None,
            "MODEL_VIEW",
            None,
        )
        project = self.model.create_entity(
            "IfcProject",
            self.guid(),
            None,
            "InfoBhoomi IFC Building Agent Project",
            "Agent-generated IFC4 cadastral building artifact.",
            None,
            None,
            None,
            (context,),
            units,
        )
        crs = self.model.create_entity(
            "IfcProjectedCRS",
            "Local engineering CRS - WGS84 anchor",
            "Local metre grid anchored to WGS84 parcel origin.",
            "WGS84",
            "MSL",
            "Local tangent plane",
            "InfoBhoomi demo",
            metre,
        )
        self.model.create_entity(
            "IfcMapConversion",
            context,
            crs,
            0.0,
            0.0,
            s.origin_height_m,
            1.0,
            0.0,
            1.0,
        )
        return project

    def create_ifc(self) -> tuple[Path, Path]:
        s = self.spec
        s.validate()
        s.output_dir.mkdir(parents=True, exist_ok=True)
        project = self.create_project_context()
        assert self.model is not None

        site_placement = self.placement(None)
        site = self.model.create_entity(
            "IfcSite",
            self.guid(),
            None,
            "InfoBhoomi Building Coordinate Reference",
            "Coordinate reference site only. No land parcel geometry is included in this IFC.",
            f"DB_PARCEL_REF_{s.parcel_id}",
            site_placement,
            None,
            None,
            "ELEMENT",
            self.dms(s.origin_latitude),
            self.dms(s.origin_longitude),
            s.origin_height_m,
            None,
            None,
        )

        building_placement = self.placement(
            site_placement, s.building_offset_east_m, s.building_offset_north_m, 0.05
        )
        building = self.model.create_entity(
            "IfcBuilding",
            self.guid(),
            None,
            s.building_name,
            "Agent-generated IFC building for 3D cadastre testing.",
            "CADASTRAL_BUILDING",
            building_placement,
            None,
            None,
            "ELEMENT",
            None,
            None,
            None,
        )

        storeys = []
        for index in range(1, s.storeys + 1):
            elevation = (index - 1) * s.storey_height_m
            storey = self.model.create_entity(
                "IfcBuildingStorey",
                self.guid(),
                None,
                f"Level {index}",
                None,
                None,
                self.placement(building_placement, 0.0, 0.0, elevation),
                None,
                None,
                "ELEMENT",
                elevation,
            )
            storeys.append(storey)

        self.model.create_entity("IfcRelAggregates", self.guid(), None, None, None, project, (site,))
        self.model.create_entity("IfcRelAggregates", self.guid(), None, None, None, site, (building,))
        self.model.create_entity("IfcRelAggregates", self.guid(), None, None, None, building, tuple(storeys))

        for storey_index, storey in enumerate(storeys, start=1):
            related = [self.create_slab(storey, storey_index)]
            related.extend(self.create_walls(storey, storey_index))
            related.extend(self.create_spaces(storey, storey_index))
            self.model.create_entity(
                "IfcRelContainedInSpatialStructure",
                self.guid(),
                None,
                None,
                None,
                tuple(related),
                storey,
            )

        footprint_meta = self.building_footprint_metadata()
        self.attach_properties(
            site,
            "Pset_InfoBhoomiGeoreferencing",
            {
                "database_land_parcel_id": s.parcel_id,
                "origin_latitude_wgs84": s.origin_latitude,
                "origin_longitude_wgs84": s.origin_longitude,
                "origin_height_m": s.origin_height_m,
                "local_coordinate_system": "metres, east-north-up",
                "note": "The land parcel is referenced by database ID only; no parcel geometry is included.",
            },
        )
        self.attach_properties(
            building,
            "Pset_InfoBhoomiBuilding",
            {
                "database_land_parcel_id": s.parcel_id,
                "storeys": s.storeys,
                "units_per_storey": s.units_per_storey,
                "footprint_width_m": s.building_width_m,
                "footprint_length_m": s.building_length_m,
                "local_origin_east_m": s.building_offset_east_m,
                "local_origin_north_m": s.building_offset_north_m,
                "footprint_local_vertices_m": self.building_footprint_vertices(),
                "footprint_wgs84_vertices": footprint_meta,
            },
        )

        ifc_path = s.output_dir / f"{s.normalized_output_name()}.ifc"
        metadata_path = s.output_dir / f"{s.normalized_output_name()}_metadata.json"
        self.model.write(str(ifc_path))
        metadata_path.write_text(json.dumps(self.metadata(), indent=2), encoding="utf-8")
        return ifc_path, metadata_path

    def create_slab(self, storey, storey_index: int):
        s = self.spec
        assert self.model is not None
        return self.model.create_entity(
            "IfcSlab",
            self.guid(),
            None,
            f"Level {storey_index} Floor Slab",
            None,
            "FLOOR_SLAB",
            self.placement(storey.ObjectPlacement, s.building_width_m / 2, s.building_length_m / 2, -0.05),
            self.rect_shape(s.building_width_m, s.building_length_m, 0.15),
            f"SLAB-L{storey_index}",
            "FLOOR",
        )

    def create_walls(self, storey, storey_index: int):
        s = self.spec
        assert self.model is not None
        specs = [
            ("North", s.building_width_m, 0.25, s.building_width_m / 2, s.building_length_m + 0.125),
            ("South", s.building_width_m, 0.25, s.building_width_m / 2, -0.125),
            ("East", 0.25, s.building_length_m, s.building_width_m + 0.125, s.building_length_m / 2),
            ("West", 0.25, s.building_length_m, -0.125, s.building_length_m / 2),
        ]
        return [
            self.model.create_entity(
                "IfcWall",
                self.guid(),
                None,
                f"Level {storey_index} {direction} Wall",
                None,
                "EXTERNAL_WALL",
                self.placement(storey.ObjectPlacement, x, y, 0.0),
                self.rect_shape(width, length, s.space_height_m),
                f"WALL-L{storey_index}-{direction.upper()}",
                "STANDARD",
            )
            for direction, width, length, x, y in specs
        ]

    def create_spaces(self, storey, storey_index: int):
        s = self.spec
        assert self.model is not None
        unit_width = s.building_width_m / s.units_per_storey
        spaces = []
        for unit_index in range(1, s.units_per_storey + 1):
            x0 = unit_width * (unit_index - 1)
            x_center = x0 + unit_width / 2
            space_name = f"Unit {storey_index}{unit_index:02d}"
            space = self.model.create_entity(
                "IfcSpace",
                self.guid(),
                None,
                space_name,
                f"Cadastral apartment unit {unit_index} on level {storey_index}.",
                "APARTMENT_UNIT",
                self.placement(storey.ObjectPlacement, x_center, s.building_length_m / 2, 0.0),
                self.rect_shape(unit_width, s.building_length_m, s.space_height_m),
                f"Apartment {space_name}",
                "ELEMENT",
                "INTERNAL",
            )
            self.attach_properties(
                space,
                "Pset_InfoBhoomiUnit",
                {
                    "database_land_parcel_id": s.parcel_id,
                    "storey": storey_index,
                    "unit_index": unit_index,
                    "local_bbox_m": [
                        s.building_offset_east_m + x0,
                        s.building_offset_north_m,
                        (storey_index - 1) * s.storey_height_m,
                        s.building_offset_east_m + x0 + unit_width,
                        s.building_offset_north_m + s.building_length_m,
                        (storey_index - 1) * s.storey_height_m + s.space_height_m,
                    ],
                    "area_m2": unit_width * s.building_length_m,
                    "volume_m3": unit_width * s.building_length_m * s.space_height_m,
                },
            )
            spaces.append(space)
        return spaces

    def metadata(self) -> dict[str, Any]:
        s = self.spec
        return {
            "parcel_id": s.parcel_id,
            "building_name": s.building_name,
            "schema": "IFC4",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "wgs84_origin": {
                "latitude": s.origin_latitude,
                "longitude": s.origin_longitude,
                "height_m": s.origin_height_m,
            },
            "local_coordinate_system": {
                "unit": "metre",
                "axis": "east-north-up",
                "origin": "WGS84 coordinate reference point supplied during generation",
            },
            "building": {
                "storeys": s.storeys,
                "units_per_storey": s.units_per_storey,
                "storey_height_m": s.storey_height_m,
                "space_height_m": s.space_height_m,
                "local_origin_m": {
                    "east": s.building_offset_east_m,
                    "north": s.building_offset_north_m,
                    "height": 0.05,
                },
                "footprint_m": {
                    "width": s.building_width_m,
                    "length": s.building_length_m,
                },
                "footprint_vertices": self.building_footprint_metadata(),
            },
            "contents": {
                "ifc_site": 1,
                "ifc_geographic_element_land_parcel": 0,
                "ifc_building": 1,
                "ifc_building_storey": s.storeys,
                "ifc_space_units": s.storeys * s.units_per_storey,
                "ifc_slabs": s.storeys,
                "ifc_walls": s.storeys * 4,
            },
        }


def load_spec(path: Path | None) -> IfcBuildingSpec:
    if path is None:
        return IfcBuildingSpec()
    return IfcBuildingSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))
