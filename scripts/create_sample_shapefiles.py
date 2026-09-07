from __future__ import annotations

import math
import struct
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "smaple data"

WGS84_PRJ = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],'
    'AUTHORITY["EPSG","4326"]]'
)


def close_ring(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if coords[0] == coords[-1]:
        return coords
    return coords + [coords[0]]


def area_m2(coords: list[tuple[float, float]]) -> float:
    ring = close_ring(coords)
    lat0 = math.radians(sum(y for _, y in ring[:-1]) / (len(ring) - 1))
    meters_per_deg_lon = 111_320.0 * math.cos(lat0)
    meters_per_deg_lat = 110_574.0
    points = [(x * meters_per_deg_lon, y * meters_per_deg_lat) for x, y in ring]
    twice_area = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        twice_area += x1 * y2 - x2 * y1
    return abs(twice_area) / 2.0


def shp_header(file_length_words: int, bbox: tuple[float, float, float, float]) -> bytes:
    xmin, ymin, xmax, ymax = bbox
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into(">i", header, 24, file_length_words)
    struct.pack_into("<i", header, 28, 1000)
    struct.pack_into("<i", header, 32, 5)  # Polygon
    struct.pack_into("<4d", header, 36, xmin, ymin, xmax, ymax)
    return bytes(header)


def polygon_record(record_number: int, coords: list[tuple[float, float]]) -> bytes:
    ring = close_ring(coords)
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    content = bytearray()
    content += struct.pack("<i", 5)
    content += struct.pack("<4d", min(xs), min(ys), max(xs), max(ys))
    content += struct.pack("<2i", 1, len(ring))
    content += struct.pack("<i", 0)
    for x, y in ring:
        content += struct.pack("<2d", x, y)
    record = bytearray()
    record += struct.pack(">2i", record_number, len(content) // 2)
    record += content
    return bytes(record)


def write_shp_shx(base: Path, polygons: list[list[tuple[float, float]]]) -> None:
    records = [polygon_record(i, poly) for i, poly in enumerate(polygons, start=1)]
    all_points = [pt for poly in polygons for pt in close_ring(poly)]
    xs = [x for x, _ in all_points]
    ys = [y for _, y in all_points]
    bbox = (min(xs), min(ys), max(xs), max(ys))

    shp_length_words = (100 + sum(len(r) for r in records)) // 2
    shp_bytes = bytearray(shp_header(shp_length_words, bbox))
    offset_words = 50
    shx_entries = []
    for rec in records:
        content_words = (len(rec) - 8) // 2
        shx_entries.append((offset_words, content_words))
        shp_bytes += rec
        offset_words += len(rec) // 2

    shx_length_words = (100 + len(shx_entries) * 8) // 2
    shx_bytes = bytearray(shp_header(shx_length_words, bbox))
    for offset, content_len in shx_entries:
        shx_bytes += struct.pack(">2i", offset, content_len)

    (base.with_suffix(".shp")).write_bytes(bytes(shp_bytes))
    (base.with_suffix(".shx")).write_bytes(bytes(shx_bytes))


def dbf_field(name: str, field_type: str, length: int, decimals: int = 0) -> bytes:
    raw = bytearray(32)
    raw[: min(10, len(name))] = name[:10].encode("ascii")
    raw[11] = ord(field_type)
    raw[16] = length
    raw[17] = decimals
    return bytes(raw)


def dbf_value(value, field_type: str, length: int, decimals: int = 0) -> bytes:
    if field_type == "N":
        if isinstance(value, float):
            text = f"{value:.{decimals}f}" if decimals else f"{round(value):.0f}"
        else:
            text = str(value)
        return text.rjust(length)[:length].encode("ascii")
    text = str(value)
    return text[:length].ljust(length).encode("ascii")


def write_dbf(base: Path, fields: list[tuple[str, str, int, int]], rows: list[dict]) -> None:
    header_len = 32 + len(fields) * 32 + 1
    record_len = 1 + sum(length for _, _, length, _ in fields)
    header = bytearray()
    header += struct.pack("<BBBBLHH20x", 3, 126, 6, 3, len(rows), header_len, record_len)
    for field in fields:
        header += dbf_field(*field)
    header += b"\r"

    body = bytearray()
    for row in rows:
        body += b" "
        for name, field_type, length, decimals in fields:
            body += dbf_value(row.get(name, ""), field_type, length, decimals)
    body += b"\x1a"
    base.with_suffix(".dbf").write_bytes(bytes(header + body))


def write_dataset(
    name: str,
    polygons: list[list[tuple[float, float]]],
    fields: list[tuple[str, str, int, int]],
    rows: list[dict],
) -> None:
    base = OUT / name
    write_shp_shx(base, polygons)
    write_dbf(base, fields, rows)
    base.with_suffix(".prj").write_text(WGS84_PRJ, encoding="ascii")
    base.with_suffix(".cpg").write_text("UTF-8", encoding="ascii")
    zip_path = base.with_name(f"{base.name}_bandarawela_irregular.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            component = base.with_suffix(suffix)
            archive.write(component, arcname=component.name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # Approximate test location near Bandarawela - Liyangahawela - Poonagala Road.
    # Coordinates are WGS84 lon/lat; the shapes are synthetic import-test parcels.
    parcel_001 = [
        (81.001250, 6.814470),
        (81.001430, 6.814410),
        (81.001620, 6.814505),
        (81.001705, 6.814690),
        (81.001555, 6.814815),
        (81.001335, 6.814770),
        (81.001205, 6.814610),
    ]
    parcel_002 = [
        (81.001760, 6.814560),
        (81.001950, 6.814480),
        (81.002180, 6.814585),
        (81.002230, 6.814780),
        (81.002060, 6.814910),
        (81.001830, 6.814855),
        (81.001710, 6.814705),
    ]
    building_001 = [
        (81.001395, 6.814565),
        (81.001510, 6.814545),
        (81.001585, 6.814625),
        (81.001560, 6.814710),
        (81.001455, 6.814730),
        (81.001375, 6.814660),
    ]

    land_fields = [
        ("PARCEL_ID", "C", 24, 0),
        ("SU_ID", "N", 10, 0),
        ("LAYER_ID", "N", 5, 0),
        ("NAME", "C", 40, 0),
        ("LAND_USE", "C", 20, 0),
        ("AREA_M2", "N", 12, 2),
    ]
    building_fields = [
        ("BLDG_ID", "C", 24, 0),
        ("PARCEL_ID", "C", 24, 0),
        ("LAYER_ID", "N", 5, 0),
        ("FLOORS", "N", 5, 0),
        ("UNITS", "N", 5, 0),
        ("AREA_M2", "N", 12, 2),
    ]

    write_dataset(
        "land_parcel_001",
        [parcel_001],
        land_fields,
        [{
            "PARCEL_ID": "LP-TEST-001",
            "SU_ID": 12505,
            "LAYER_ID": 1,
            "NAME": "Sample Land Parcel 001",
            "LAND_USE": "Residential",
            "AREA_M2": area_m2(parcel_001),
        }],
    )
    write_dataset(
        "land_parcel_002",
        [parcel_002],
        land_fields,
        [{
            "PARCEL_ID": "LP-TEST-002",
            "SU_ID": 12506,
            "LAYER_ID": 1,
            "NAME": "Sample Land Parcel 002",
            "LAND_USE": "Mixed Use",
            "AREA_M2": area_m2(parcel_002),
        }],
    )
    write_dataset(
        "building_footprint_001",
        [building_001],
        building_fields,
        [{
            "BLDG_ID": "BLDG-TEST-001",
            "PARCEL_ID": "LP-TEST-001",
            "LAYER_ID": 3,
            "FLOORS": 3,
            "UNITS": 9,
            "AREA_M2": area_m2(building_001),
        }],
    )

    readme = OUT / "README.txt"
    readme.write_text(
        "\n".join([
            "InfoBhoomi sample shapefiles",
            "",
            "Coordinate system: WGS84 / EPSG:4326.",
            "",
            "Datasets:",
            "- land_parcel_001.*: one residential land parcel, PARCEL_ID=LP-TEST-001, SU_ID=12505.",
            "- land_parcel_002.*: one mixed-use land parcel, PARCEL_ID=LP-TEST-002, SU_ID=12506.",
            "- building_footprint_001.*: one building footprint inside LP-TEST-001.",
            "",
            "Location:",
            "- Synthetic parcels are placed close to Bandarawela - Liyangahawela - Poonagala Road.",
            "- Approximate anchor: latitude 6.814626, longitude 81.001518.",
            "",
            "Each shapefile dataset must be imported with its .shp, .shx, .dbf, .prj, and .cpg files together.",
            "ZIP files are included for direct import.",
        ]),
        encoding="utf-8",
    )

    for path in sorted(OUT.iterdir()):
        print(path)


if __name__ == "__main__":
    main()
