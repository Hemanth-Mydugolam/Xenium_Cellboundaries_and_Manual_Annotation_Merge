# Xenium Cell Boundaries → Merged GeoJSON Pipeline

This pipeline processes 10x Genomics Xenium spatial transcriptomics data to:

1. **Stage 1** — Convert `cell_boundaries.csv.gz` (micron coordinates) into pixel-scaled GeoJSON files suitable for QuPath.
2. **Stage 2** — Merge the Xenium-derived cell boundaries with a manually annotated GeoJSON, replacing any Xenium cells that overlap the manual annotations.

---

## Input Files Required

| File | Description |
|------|-------------|
| `<xenium_bundle>/cell_boundaries.csv.gz` | Xenium output: per-cell polygon vertex coordinates in microns |
| `<xenium_bundle>/morphology_focus/ch0002_18s.ome.tif` | OME-TIFF used to extract pixel size (µm/px) from metadata |
| `<output_dir>/manual_annotated_geojson.geojson` | Manually drawn cell boundaries (e.g., exported from QuPath) |

---

## Output Files

| File | Description |
|------|-------------|
| `<output_dir>/cell_boundaries_pixel_scaled.geojson` | Standard GeoJSON (pixel coordinates) |
| `<output_dir>/cell_boundaries_qupath.geojson` | QuPath-compatible GeoJSON with classification metadata |
| `<output_dir>/merged.geojson` | Final merged GeoJSON (Xenium cells + manual annotations) |
| `<output_dir>/cell_boundary_conversion_and_merge_log.txt` | Full run log |

---

## Setup Instructions

### Prerequisites

- Python 3.9 or later
- pip

---

### Windows

**Step 1 — Install Python**

Download and install Python 3.9+ from [python.org](https://www.python.org/downloads/). During installation, check **"Add Python to PATH"**.

Verify the installation:
```
python --version
```

**Step 2 — Open a terminal**

Press `Win + R`, type `cmd`, and press Enter. Or open PowerShell from the Start menu.

**Step 3 — Navigate to the project folder**

```
cd "C:\path\to\Olivia_Farkas_McGill"
```

**Step 4 — (Optional but recommended) Create a virtual environment**

```
python -m venv venv
venv\Scripts\activate
```

You should see `(venv)` at the start of your prompt.

**Step 5 — Install dependencies**

```
pip install -r requirements.txt
```

**Step 6 — Configure paths in the script**

Open `Olivia_Farkas_Cell_boundaries_manual_merge_pipeline_HM.py` in a text editor and update the three paths near the bottom of the file inside the `main()` function:

```python
# Path to your Xenium bundle folder
main_path = Path("C:\\path\\to\\Xenium\\bundle")

# Path where output GeoJSON files will be saved
output_dir = Path("C:\\path\\to\\manual\\annotation\\folder")

# Full path to your manually annotated GeoJSON file
manual_annotations = output_dir / "manual_annotated_geojson.geojson"
```

- `main_path` must point to the root of the Xenium output bundle (the folder containing `cell_boundaries.csv.gz` and the `morphology_focus/` subfolder).
- `output_dir` is where all results will be written. It will be created automatically if it does not exist.
- `manual_annotations` must point to the QuPath-exported GeoJSON containing your manually drawn cell boundaries.

**Step 7 — Run the pipeline**

```
python Olivia_Farkas_Cell_boundaries_manual_merge_pipeline_HM.py
```

---

### macOS

**Step 1 — Install Python**

Option A — via the official installer: download Python 3.9+ from [python.org](https://www.python.org/downloads/).

Option B — via Homebrew (recommended if Homebrew is already installed):
```bash
brew install python
```

Verify:
```bash
python3 --version
```

**Step 2 — Open a terminal**

Press `Cmd + Space`, type `Terminal`, and press Enter.

**Step 3 — Navigate to the project folder**

```bash
cd "/path/to/Olivia_Farkas_McGill"
```

**Step 4 — (Optional but recommended) Create a virtual environment**

```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` at the start of your prompt.

**Step 5 — Install dependencies**

```bash
pip install -r requirements.txt
```

**Step 6 — Configure paths in the script**

Open `Olivia_Farkas_Cell_boundaries_manual_merge_pipeline_HM.py` in a text editor and update the three paths inside the `main()` function:

```python
# Path to your Xenium bundle folder
main_path = Path("/path/to/Xenium/bundle")

# Path where output GeoJSON files will be saved
output_dir = Path("/path/to/manual/annotation/folder")

# Full path to your manually annotated GeoJSON file
manual_annotations = output_dir / "manual_annotated_geojson.geojson"
```

Use forward slashes `/` for paths on macOS.

**Step 7 — Run the pipeline**

```bash
python3 Olivia_Farkas_Cell_boundaries_manual_merge_pipeline_HM.py
```

---

## How the Pipeline Works

### Stage 1 — Cell Boundaries to GeoJSON

1. Reads pixel size (µm/px) from the OME-TIFF metadata in the Xenium bundle.
2. Loads `cell_boundaries.csv.gz` and converts all vertex coordinates from microns to pixels.
3. Builds a Shapely `Polygon` per cell. Invalid polygons are auto-repaired with `buffer(0)`.
4. Writes two GeoJSON files:
   - **Standard** — geometry + `cell_id` property.
   - **QuPath** — geometry + QuPath classification metadata (`name`, `cell_id`, `classification`).

### Stage 2 — Merge with Manual Annotations

1. Loads the Stage 1 QuPath GeoJSON and the manually annotated GeoJSON.
2. Uses a spatial index (STRtree) to efficiently find every Xenium cell that touches or intersects any manually drawn polygon.
3. Removes those Xenium cells from the set.
4. Concatenates the remaining Xenium cells with all manual annotations.
5. Writes the merged result to `merged.geojson`.

---

## Design Note & Tradeoff

The pipeline gives manual annotations full priority: **any Xenium cell that overlaps — even partially — with a manually annotated region is dropped entirely** from the merged output.

**Why this is intentional:** Manual annotations represent curated, expert-reviewed cell boundaries. Keeping a conflicting Xenium cell alongside them would introduce duplicate or inconsistent segmentations for the same physical cell.

**The tradeoff to be aware of:** Because the removal criterion is overlap (not containment), a Xenium cell that only grazes the edge of a manually annotated region is still removed in full. This means:

- Cells at the boundary of a manually annotated region may be lost even if only a small portion of their area overlaps.
- The resulting merged file could have small coverage gaps at those boundaries — areas not covered by any cell polygon.
- The total cell count in `merged.geojson` will always be ≤ (Xenium cells + manual annotations), never additive.

**When this matters most:** If the manually annotated region has irregular or tightly packed boundaries, a larger number of Xenium cells at the periphery may be discarded. In such cases, visually inspecting the merged output in QuPath around the annotation boundaries is recommended to confirm coverage is acceptable.

---

## Troubleshooting

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `FileNotFoundError: Missing: .../cell_boundaries.csv.gz` | `main_path` is wrong | Double-check the Xenium bundle folder path |
| `FileNotFoundError: Missing: .../morphology_focus/ch0002_18s.ome.tif` | Wrong bundle or missing file | Verify the `morphology_focus/` subfolder exists with this file |
| `FileNotFoundError` for manual annotations | `manual_annotations` path is wrong | Ensure the GeoJSON file exists at the specified path |
| `ModuleNotFoundError` | Dependencies not installed | Re-run `pip install -r requirements.txt` with the virtual environment active |
| `venv\Scripts\activate` fails on Windows | Execution policy restriction | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` in PowerShell first |

---

## Contact

If you have any questions, please send an email to hemanth.mydugolam@utdallas.edu
