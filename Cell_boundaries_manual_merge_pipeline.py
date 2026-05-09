###################################################################
##--------  XENIUM CELL BOUNDARIES → GEOJSON (STAGE 1)  ---------##
###################################################################

import sys
import pandas as pd
import geojson
from shapely.geometry import Polygon, MultiPolygon
import tifffile
import xml.etree.ElementTree as ET
from pathlib import Path


class _Tee:
    """Mirrors writes to two streams simultaneously (e.g. stdout + log file)."""
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            s.write(data)

    def flush(self):
        for s in self._streams:
            s.flush()


class XeniumBoundaryConverter:
    def __init__(self, main_path, output_dir):
        self.main_path = Path(main_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)

        self.boundary_file = self.main_path / "cell_boundaries.csv.gz"
        self.morphology_tiff = (
            #self.main_path / "morphology_focus" /"ch0002_18s.ome.tif"
            self.main_path / "morphology_focus" / "morphology_focus_0001.ome.tif"
        )

        if not self.boundary_file.exists():
            raise FileNotFoundError(f"Missing: {self.boundary_file}")

        if not self.morphology_tiff.exists():
            raise FileNotFoundError(f"Missing: {self.morphology_tiff}")

        self.pixel_um_x, self.pixel_um_y = self._get_pixel_sizes()
        print(f"[INFO] Microns per pixel → X: {self.pixel_um_x}, Y: {self.pixel_um_y}")

    # -----------------------------------------------------
    # Extract pixel scaling
    # -----------------------------------------------------
    def _get_pixel_sizes(self):
        with tifffile.TiffFile(self.morphology_tiff) as tif:
            ome_xml = tif.ome_metadata

        root = ET.fromstring(ome_xml)
        ns = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}
        pixels = root.find(".//ome:Pixels", ns)

        return (
            float(pixels.get("PhysicalSizeX")),
            float(pixels.get("PhysicalSizeY")),
        )

    # -----------------------------------------------------
    # Convert cell_boundaries.csv.gz → GeoJSON
    # -----------------------------------------------------
    def convert_cell_boundaries(self):
        output_geojson = self.output_dir / "cell_boundaries_pixel_scaled.geojson"
        output_qupath_geojson = self.output_dir / "cell_boundaries_qupath.geojson"

        print(f"[INFO] Reading: {self.boundary_file}")
        df = pd.read_csv(self.boundary_file)

        num_cells = df["cell_id"].nunique()
        print(f"[INFO] Unique cells in CSV: {num_cells}")

        # Convert microns → pixels
        df["x_px"] = df["vertex_x"] / self.pixel_um_x
        df["y_px"] = df["vertex_y"] / self.pixel_um_y

        standard_features = []
        qupath_features = []

        for cell_id, group in df.groupby("cell_id"):
            coords = list(zip(group["x_px"], group["y_px"]))
            poly = Polygon(coords)

            if not poly.is_valid:
                poly = poly.buffer(0)

            if isinstance(poly, Polygon):
                geometry = geojson.Polygon([list(poly.exterior.coords)])
            elif isinstance(poly, MultiPolygon):
                geometry = geojson.MultiPolygon(
                    [[list(p.exterior.coords)] for p in poly.geoms]
                )
            else:
                continue

            standard_features.append(
                geojson.Feature(
                    geometry=geometry,
                    properties={"cell_id": cell_id},
                )
            )

            qupath_features.append(
                geojson.Feature(
                    geometry=geometry,
                    properties={
                        "name": f"Cell_{cell_id}",
                        "cell_id": cell_id,
                        "classification": {
                            "name": "Cell",
                            "color": [0, 255, 0],
                        },
                    },
                )
            )

        # Save outputs
        geojson.dump(
            geojson.FeatureCollection(standard_features),
            open(output_geojson, "w"),
        )
        geojson.dump(
            geojson.FeatureCollection(qupath_features),
            open(output_qupath_geojson, "w"),
        )

        print("\n==== CELL BOUNDARY CONVERSION SUMMARY ====")
        print(f"Cells in CSV              : {num_cells}")
        print(f"Standard GeoJSON features : {len(standard_features)}")
        print(f"QuPath GeoJSON features   : {len(qupath_features)}")
        print(f"Standard output           : {output_geojson}")
        print(f"QuPath output             : {output_qupath_geojson}")

        return output_geojson, output_qupath_geojson


##########################################################################################################
##--------  Merge two geoJSONS (exclude overlapping from one file) → Merged GEOJSON (STAGE 2)  ---------##
##########################################################################################################
import json
from shapely.geometry import shape
from shapely.strtree import STRtree


def merge_geojsons(geojson_A, geojson_B):
    # -----------------------------
    # File paths
    # -----------------------------
    GEOJSON_A = geojson_A   # many polygons (Stage 1 output)
    GEOJSON_B = geojson_B   # fewer polygons (manually annotated)
    OUTPUT_GEOJSON = Path(geojson_B).parent / "merged.geojson"

    # -----------------------------
    # Load GeoJSON files
    # -----------------------------
    with open(GEOJSON_A) as f:
        geojson_a = json.load(f)

    with open(GEOJSON_B) as f:
        geojson_b = json.load(f)

    features_a = geojson_a["features"]
    features_b = geojson_b["features"]

    # -----------------------------
    # Print initial counts
    # -----------------------------
    print("==== BEFORE MERGE ====")
    print(f"Annotations in first GeoJSON (Xenium Bundle Cells): {len(features_a)}")
    print(f"Annotations in second GeoJSON (Manual Annotations): {len(features_b)}")

    # -----------------------------
    # Convert A features to Shapely geometries
    # -----------------------------
    a_geoms = [shape(feat["geometry"]) for feat in features_a]

    # Spatial index
    tree = STRtree(a_geoms)

    # Track indices of A features to remove
    remove_indices = set()

    # -----------------------------
    # Find touching/intersecting A features
    # -----------------------------
    for feat_b in features_b:
        geom_b = shape(feat_b["geometry"])

        candidate_idxs = tree.query(geom_b)
        for idx in candidate_idxs:
            geom_a = a_geoms[idx]

            if geom_b.touches(geom_a) or geom_b.intersects(geom_a):
                remove_indices.add(idx)


    # -----------------------------
    # Filter A features
    # -----------------------------
    filtered_a_features = [
        feat for i, feat in enumerate(features_a) if i not in remove_indices
    ]

    # -----------------------------
    # Merge results
    # -----------------------------
    #merged_features = filtered_a_features + features_b

    merged_features = [
        {
            "type": "Feature",
            "id": str(
                f.get("id")
                or f.get("properties", {}).get("cell_id")
            ),
            "geometry": f["geometry"],
            "properties": {}
        }
        for f in (filtered_a_features + features_b)
    ]


    # -----------------------------
    # Print final counts
    # -----------------------------
    print("\n==== AFTER MERGE ====")
    print(f"Excluded from first GeoJSON (Xenium Bundle Cells): {len(remove_indices)}")
    print(f"Remaining from first GeoJSON (Xenium Bundle Cells): {len(filtered_a_features)}")
    print(f"Included from second GeoJSON (Manual Annotations): {len(features_b)}")
    print(f"Final merged annotation count (Xenium Cells + Manual): {len(merged_features)}")

    # -----------------------------
    # Write output
    # -----------------------------
    merged_geojson = {
        "type": "FeatureCollection",
        "features": merged_features
    }

    with open(OUTPUT_GEOJSON, "w") as f:
        json.dump(merged_geojson, f, indent=2)

    print(f"\nMerged GeoJSON written to: {OUTPUT_GEOJSON}")
    print("\n✅ Stage 2 complete")

    return {
        "features_a_total": len(features_a),
        "features_b_total": len(features_b),
        "excluded_from_a": len(remove_indices),
        "remaining_from_a": len(filtered_a_features),
        "merged_total": len(merged_features),
        "output": OUTPUT_GEOJSON,
    }


# -----------------------------------------------------
# Main
# -----------------------------------------------------
def main():
    # Xenium Bundle path (update below depending on your actual bundle path)
    main_path = Path("C:\\path\\to\\Xenium\\bundle")
    # Path to store the result geojsons (update below depending on where you want to store results)
    output_dir = Path("C:\\path\\to\\manual\\annotation\\folder")
    # Path to the manual annotated geojson (update below path to corresponding manual annotated geojson location)
    manual_annotations = output_dir / "manual_annotated_geojson.geojson"

    output_dir.mkdir(exist_ok=True, parents=True)
    log_path = output_dir / "cell_boundary_conversion_and_merge_log.txt"

    with open(log_path, "w", encoding="utf-8") as log_file:
        sys.stdout = _Tee(sys.__stdout__, log_file)
        try:
            print("\n=== XENIUM CELL BOUNDARY CONVERSION ===\n")

            # ── Stage 1 ──────────────────────────────────────
            print("--- Stage 1: Cell Boundaries → GeoJSON ---\n")
            converter = XeniumBoundaryConverter(main_path, output_dir)
            _, geojson_qupath = converter.convert_cell_boundaries()
            print("\n✅ Stage 1 complete")

            # ── Stage 2 ──────────────────────────────────────
            print("\n--- Stage 2: Merge GeoJSONs ---\n")
            merge_geojsons(geojson_qupath, manual_annotations)

            print(f"\nLog saved → {log_path}")
        finally:
            sys.stdout = sys.__stdout__


if __name__ == "__main__":
    main()
