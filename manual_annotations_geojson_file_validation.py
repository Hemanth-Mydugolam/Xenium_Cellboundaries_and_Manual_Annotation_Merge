"""
GeoJSON QC Checker for QuPath Annotations (10x Xenium Bundles)
--------------------------------------------------------------
Iterates over every immediate subfolder inside a root directory, finds all
.geojson files within each subfolder, and counts feature types
(Polygon, MultiPolygon, LineString, etc.) per file.

Each file is assigned a Pass/Fail status for Xenium import (only Polygon
geometries are allowed). Non-Polygon features are extracted from every file;
any file containing them is marked FAIL and the extracted features are saved
as a QuPath-compatible GeoJSON under {subfolder}/non_polygon_exports/.

A formatted Excel QC log summarising all results is written to the output path.

Usage:
    python manual_annotations_geojson_file_validation.py --root /path/to/root_folder --output qc_log.xlsx

    OR edit ROOT_DIR and OUTPUT_FILE below and run directly.
"""

import os
import json
import argparse
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side
)
from openpyxl.utils import get_column_letter

# ── Inline defaults (override with CLI args) ─────────────────────────────────
ROOT_DIR    = r"C:\\Users\\hxm220004\\Box\\Xenium_to annotate\\First Batch"
OUTPUT_FILE = "geojson_qc_log.xlsx"            # saved in current working dir
# ─────────────────────────────────────────────────────────────────────────────

# Xenium import requires ONLY Polygon / MultiPolygon features.
# Any other geometry type → FAIL.
XENIUM_ALLOWED = {"Polygon"}

# Geometry types tracked explicitly; everything else lands in "Other"
TRACKED_TYPES = [
    "Polygon",
    "MultiPolygon",
    "LineString",
    "MultiLineString",
    "Point",
    "MultiPoint",
    "GeometryCollection",
]


def export_non_polygon_features(
    geojson_path: Path,
    subfolder_name: str,
    export_dir: Path,
) -> str:
    """
    Extract features whose geometry type is NOT in XENIUM_ALLOWED from a
    GeoJSON file and save them as a QuPath-compatible GeoJSON FeatureCollection.

    Each exported feature gets QuPath-required 'name' and 'classification'
    properties so it loads correctly in QuPath.

    Output filename: {subfolder_name}_{original_stem}_non_polygon.geojson
    Returns the exported file path as a string, or "" if nothing to export.
    """
    with open(geojson_path, encoding="utf-8") as f:
        data = json.load(f)

    if data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    elif isinstance(data, list):
        features = data
    else:
        features = [data]

    non_polygon = []
    for i, feat in enumerate(features):
        if feat.get("type") == "Feature":
            geom = feat.get("geometry") or {}
        else:
            geom = feat
        gtype = geom.get("type", "Unknown")
        if gtype not in XENIUM_ALLOWED:
            # Preserve existing properties, overlay QuPath-required fields
            existing_props = feat.get("properties") or {}
            qupath_feature = {
                "type": "Feature",
                "geometry": geom if feat.get("type") == "Feature" else feat,
                "properties": {
                    **existing_props,
                    "name": existing_props.get("name") or f"{gtype}_{i}",
                    "classification": existing_props.get("classification") or {
                        "name": gtype,
                        "color": [255, 165, 0],   # orange — visually distinct in QuPath
                    },
                },
            }
            non_polygon.append(qupath_feature)

    if not non_polygon:
        return ""

    export_dir.mkdir(parents=True, exist_ok=True)
    out_name = (
        f"{subfolder_name}_{geojson_path.stem}_non_polygon.geojson"
        if subfolder_name
        else f"{geojson_path.stem}_non_polygon.geojson"
    )
    out_path = export_dir / out_name

    feature_collection = {"type": "FeatureCollection", "features": non_polygon}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(feature_collection, f, indent=2)

    print(f"  📤  Exported {len(non_polygon)} non-Polygon feature(s) → {out_path}")
    return str(out_path)


def count_features(geojson_path: Path) -> dict:
    """Load a GeoJSON file and return feature-type counts."""
    with open(geojson_path, encoding="utf-8") as f:
        data = json.load(f)

    counts = defaultdict(int)

    # Support both FeatureCollection and bare geometry arrays
    if data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    elif isinstance(data, list):
        features = data
    else:
        features = [data]

    for feat in features:
        # Feature wrapper
        if feat.get("type") == "Feature":
            geom = feat.get("geometry") or {}
        else:
            geom = feat

        gtype = geom.get("type", "Unknown")
        counts[gtype] += 1

    return counts


def scan_root(root: str) -> list[dict]:
    """
    For each immediate subfolder inside root, find all .geojson files,
    count feature types per file, and return one result dict per file.
    Non-Polygon features from FAIL files are exported to
    {subfolder}/non_polygon_exports/.
    """
    root_path = Path(root)
    results = []

    subfolders = sorted(d for d in root_path.iterdir() if d.is_dir())

    if not subfolders:
        print(f"  ⚠️  No subfolders found in '{root_path}'.")
        return results

    for subfolder in subfolders:
        geojson_files = sorted(subfolder.glob("*.geojson"))

        if not geojson_files:
            print(f"  ⚠️  No .geojson files found in subfolder '{subfolder.name}' — skipping.")
            continue

        export_dir = subfolder / "non_polygon_exports"

        for gj in geojson_files:
            counts = count_features(gj)
            total_features = sum(counts.values())

            non_xenium = {k: v for k, v in counts.items()
                          if k not in XENIUM_ALLOWED and v > 0}
            status = "FAIL" if non_xenium else "PASS"

            other = sum(v for k, v in counts.items()
                        if k not in TRACKED_TYPES)

            exported_file = export_non_polygon_features(
                gj, subfolder.name, export_dir
            )

            results.append({
                "subfolder":          subfolder.name,
                "geojson_files":      gj.name,
                "total_features":     total_features,
                "Polygon":            counts.get("Polygon", 0),
                "MultiPolygon":       counts.get("MultiPolygon", 0),
                "LineString":         counts.get("LineString", 0),
                "MultiLineString":    counts.get("MultiLineString", 0),
                "Point":              counts.get("Point", 0),
                "MultiPoint":         counts.get("MultiPoint", 0),
                "GeometryCollection": counts.get("GeometryCollection", 0),
                "Other":              other,
                "status":             status,
                "fail_reason":        (
                    "; ".join(f"{k}={v}" for k, v in non_xenium.items())
                    if non_xenium else ""
                ),
                "exported_file":      exported_file,
            })

    return results


# ── Excel helpers ─────────────────────────────────────────────────────────────

HEADER_FILL   = PatternFill("solid", fgColor="1F4E79")   # dark blue
PASS_FILL     = PatternFill("solid", fgColor="C6EFCE")   # light green
FAIL_FILL     = PatternFill("solid", fgColor="FFC7CE")   # light red
ALT_FILL      = PatternFill("solid", fgColor="EBF3FB")   # very light blue
WHITE_FILL    = PatternFill("solid", fgColor="FFFFFF")

THIN_BORDER = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)

HEADERS = [
    ("Root Folder",                  28),
    ("GeoJSON File(s)",              40),
    ("Total Features",               16),
    ("Polygon",                      14),
    ("MultiPolygon",                 16),
    ("LineString",                   14),
    ("MultiLineString",              18),
    ("Point",                        10),
    ("MultiPoint",                   14),
    ("GeometryCollection",           22),
    ("Other",                        10),
    ("Xenium Import",                16),
    ("Fail Reason",                  35),
    ("Exported Non-Polygon GeoJSON", 55),
]

FIELD_KEYS = [
    "subfolder", "geojson_files", "total_features",
    "Polygon", "MultiPolygon", "LineString", "MultiLineString",
    "Point", "MultiPoint", "GeometryCollection", "Other",
    "status", "fail_reason", "exported_file",
]


def write_excel(results: list[dict], output_path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "GeoJSON QC Log"

    # ── Title row ────────────────────────────────────────────────────────────
    ws.merge_cells("A1:N1")
    title_cell = ws["A1"]
    title_cell.value = "QuPath GeoJSON — Xenium Import QC Report"
    title_cell.font      = Font(name="Arial", bold=True, size=14, color="FFFFFF")
    title_cell.fill      = PatternFill("solid", fgColor="1F4E79")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # ── Header row ───────────────────────────────────────────────────────────
    for col_idx, (label, width) in enumerate(HEADERS, start=1):
        cell = ws.cell(row=2, column=col_idx, value=label)
        cell.font      = Font(name="Arial", bold=True, size=10, color="FFFFFF")
        cell.fill      = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
        cell.border    = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[2].height = 32

    # ── Data rows ────────────────────────────────────────────────────────────
    for row_idx, rec in enumerate(results, start=3):
        fill = ALT_FILL if row_idx % 2 == 0 else WHITE_FILL

        for col_idx, key in enumerate(FIELD_KEYS, start=1):
            value = rec[key]
            cell  = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font      = Font(name="Arial", size=10)
            cell.border    = THIN_BORDER
            cell.alignment = Alignment(horizontal="center", vertical="center",
                                       wrap_text=True)

            # Status column coloring
            if key == "status":
                if value == "PASS":
                    cell.fill = PASS_FILL
                    cell.font = Font(name="Arial", size=10, bold=True,
                                     color="375623")
                else:
                    cell.fill = FAIL_FILL
                    cell.font = Font(name="Arial", size=10, bold=True,
                                     color="9C0006")
            elif key in ("subfolder", "geojson_files", "fail_reason", "exported_file"):
                cell.alignment = Alignment(horizontal="left",
                                           vertical="center", wrap_text=True)
                cell.fill = fill
            else:
                cell.fill = fill

        ws.row_dimensions[row_idx].height = 18

    # ── Summary row ──────────────────────────────────────────────────────────
    summary_row = len(results) + 3
    ws.cell(row=summary_row, column=1, value="TOTAL / SUMMARY").font = \
        Font(name="Arial", bold=True, size=10)
    ws.cell(row=summary_row, column=1).fill = \
        PatternFill("solid", fgColor="D9E1F2")

    num_rows = len(results)
    # Sum numeric columns (cols 3-11)
    for col_idx in range(3, 12):
        col_letter = get_column_letter(col_idx)
        ws.cell(
            row=summary_row, column=col_idx,
            value=f"=SUM({col_letter}3:{col_letter}{2 + num_rows})"
        ).font = Font(name="Arial", bold=True, size=10)
        ws.cell(row=summary_row, column=col_idx).fill = \
            PatternFill("solid", fgColor="D9E1F2")
        ws.cell(row=summary_row, column=col_idx).border = THIN_BORDER
        ws.cell(row=summary_row, column=col_idx).alignment = \
            Alignment(horizontal="center")

    # Pass / Fail tally
    pass_col = get_column_letter(12)
    ws.cell(
        row=summary_row, column=12,
        value=f'=COUNTIF({pass_col}3:{pass_col}{2 + num_rows},"PASS")'
             f'&" PASS / "'
             f'&COUNTIF({pass_col}3:{pass_col}{2 + num_rows},"FAIL")'
             f'&" FAIL"'
    ).font = Font(name="Arial", bold=True, size=10)
    ws.cell(row=summary_row, column=12).fill = \
        PatternFill("solid", fgColor="D9E1F2")
    ws.cell(row=summary_row, column=12).border = THIN_BORDER
    ws.cell(row=summary_row, column=12).alignment = \
        Alignment(horizontal="center")

    # Freeze panes below header
    ws.freeze_panes = "A3"

    wb.save(output_path)
    print(f"✅  Excel log saved → {output_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="QuPath GeoJSON QC checker for 10x Xenium bundles"
    )
    parser.add_argument(
        "--root", default=ROOT_DIR,
        help="Root folder whose immediate subfolders are scanned for .geojson files"
    )
    parser.add_argument(
        "--output", default=OUTPUT_FILE,
        help="Output Excel file path (default: geojson_qc_log.xlsx)"
    )
    args = parser.parse_args()

    root = args.root
    if not os.path.isdir(root):
        print(f"❌  Root directory not found: {root}")
        return

    print(f"🔍  Scanning: {root}")
    results = scan_root(root)

    if not results:
        print("⚠️   No GeoJSON files found. Check your root directory.")
        return

    print(f"📋  Found {len(results)} GeoJSON file(s) to process.")
    write_excel(results, args.output)


if __name__ == "__main__":
    main()