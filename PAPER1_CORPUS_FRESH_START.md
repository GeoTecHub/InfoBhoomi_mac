# Paper 1 — fresh start on the corpus

Written 2026-09-07. Every model listed here was downloaded, hashed and scanned with your own
`scripts/ifc_fitness_scan.py` on that date. The numbers below are measured, not quoted.

Companions: `PAPER1_CORPUS_PLAN.md` (why), `PAPER1_DATA_AND_VERIFICATION.md` (what is recorded),
`Paper1_RawData_Template.xlsx` (where it goes).

---

## Why start again

The nine files you scanned before are really six models, all authored in the same family, and
**none of them contains a single `IfcRelSpaceBoundary`**. That one absence disables the semantic
axis of the taxonomy — with no space boundaries there is no party wall to identify, so there is
nothing to measure losing.

The six models below fix that. Five of the six carry space boundaries, 4 710 of them in total.
This is the single biggest reason to restart rather than extend.

| | Old corpus | New Route A corpus |
|---|---|---|
| Distinct models | 6 (9 files, 3 duplicated) | 6 |
| Legal volumes (`IfcSpace`) | 136 | **354** |
| Space boundaries | **0** | **4 710** |
| Buildings (unit of independence) | 1 family | 6 independent authors |
| Carries `IfcMapConversion` | 3 — all your own tooling | **0** |
| Non-metre units | none | 1 (Schependomlaan, mm) |

That last row is a result in itself: **no externally authored model in either corpus carries an
`IfcMapConversion`.** Twelve models, zero. That is now a defensible sentence in §1.1 instead of a
hedge.

---

## The corpus

All six verified live on 2026-09-07. SHA-256 for each is recorded in `scripts/fetch_corpus.py`,
so the corpus is reproducible by a reader.

| Model | Schema | Unit | Spaces | Boundaries | Storeys | MB | Licence |
|---|---|---|---|---|---|---|---|
| AC-20-Smiley-West-10-Bldg | IFC4 | m | 140 | 1 689 | 5 | 5.8 | KIT/IAI, credit requested |
| Schependomlaan | IFC2X3 | **mm** | 100 | 1 675 | 6 | 47.0 | CC BY 4.0 |
| AC20-Institute-Var-2 | IFC4 | m | 82 | 1 000 | 5 | 10.4 | KIT/IAI, credit requested |
| Duplex Architecture | IFC2X3 | m | 21 | 265 | 4 | 2.3 | not stated — see below |
| AC20-FZK-Haus | IFC4 | m | 7 | 81 | 2 | 2.5 | KIT/IAI, credit requested |
| SampleHouse IFC4 | IFC4 | m | 4 | **0** | 2 | 2.2 | not stated — see below |

**Rejected, on the record:** `Ifc4_Revit_ARC.ifc` — 0 `IfcSpace`. It imports without error and
produces zero legal volumes. That is the silent failure your scanner exists to catch, and it is
worth one sentence in the paper.

**What each one is for**

- **Smiley West** — a residential block, the closest open model to a strata building. Your main
  multi-unit case.
- **Schependomlaan** — heavily cited in GeoBIM research, so reviewers recognise it. Also the only
  model in millimetres, which exercises the unit-scale path deliberately.
- **Institute-Var-2** — a five-storey office. Vertical adjacency and shared horizontal faces.
- **Duplex** — two units, one building. The smallest genuine strata case.
- **FZK-Haus** — small and fast. Use it while debugging; never quote results from it alone.
- **SampleHouse** — has spaces but **no** boundaries. Keep it as the negative control for the
  semantic axis: it should score zero there, and if it does not, the metric is wrong.

**Licence notes.** The three KIT models ask to be credited to the *Institute for Automation and
Applied Informatics (IAI) / Karlsruhe Institute of Technology* — put that line in the
acknowledgements. Schependomlaan is CC BY 4.0, so attribution is enough. The two files from the
`youshengCode/IfcSampleFiles` repository carry **no licence statement**; the Duplex model itself
originates as a Common BIM File and circulates freely, but before you publish derived geometry
from those two, either find a licensed mirror or drop them. Measuring them is not the problem —
redistribution is.

---

## Step by step

Commands assume you are in the `InfoBhoomi_mac` folder.

### 1. Make a clean tree

```
mkdir -p corpus/routeA corpus/synthetic results/C0 results/logs
```

Leave the old `3D-Cadastre/IFC/` folder alone. It is not deleted, it is simply no longer the
corpus. Say so once in the paper and the reader knows where the earlier numbers came from.

### 2. Fetch the models

```
python3 scripts/fetch_corpus.py
```

Downloads all six into `corpus/routeA/`, unzips the one that needs it, and checks every file
against its recorded SHA-256. Re-run any time with `--verify` to prove nothing has changed.

If a hash ever mismatches, the upstream file was replaced. Do not silently accept it — record the
new hash and note the date, because your corpus is then not the one the earlier results came from.

### 3. Screen them yourself

```
python3 scripts/ifc_fitness_scan.py corpus/routeA --csv corpus/scan_routeA.csv
```

Expect `6 file(s): 6 usable, 0 unusable. 0/6 carry an IfcMapConversion.` If you get anything else,
stop and find out why before measuring anything.

### 4. Register them in the workbook

Open `Paper1_RawData_Template.xlsx` → **Models** sheet. One row per model. Most columns come
straight out of `scan_routeA.csv`; you add:

- `model_id` — use `RA-01` … `RA-06`, and keep that spelling everywhere.
- `building_id` — one per model. These are six independent buildings, which is your n for any
  statistical claim on the real arm.
- `arm` = Real, `route` = A - Open IFC, `member_type` = Production model.
- `latitude_deg` / `longitude_deg` — the anchor you will place each model at. Vary them
  deliberately; the 1 × 10⁻⁷ ° grid means a different physical distance at every latitude, and if
  every model sits at the same anchor you cannot separate the CRS factor from the tolerance factor.
- `licence` — copy from the table above. Do this now, not at submission.

### 5. Run the baseline

One run per model, condition C0:

```
python3 scripts/roundtrip_metrics.py corpus/routeA/AC20-FZK-Haus.ifc \
        --csv results/C0/RA-05.csv --json results/C0/RA-05.json
```

Start with FZK-Haus (7 spaces, seconds). Then Duplex, Institute, Smiley West, Schependomlaan.
Schependomlaan is 47 MB and in millimetres — run it last, and check the unit scaling before you
believe any number from it.

### 6. Load the results into the workbook

The harness writes 19 columns with the same names as the **Volumes** sheet, so this is a paste,
not a retype. Add `model_id`, `condition` = C0, and `run_id` for each block of rows. The
calculated columns fill themselves; **Survival_Summary** updates on its own.

Sanity check before going further: `dv_pct` must be zero to floating point for every row — it
inverts the converter's own formula and measures nothing. If it is non-zero, the harness or the
encoder has a fault, and every other number is suspect.

### 7. Then, in this order

1. **Synthetic arm.** Extend `create_three_storey_land_parcel_ifc.py` to the seven member types,
   varied in dimension, orientation and placement. This is the only arm with a known true volume,
   and it carries the statistics. 50–80 volumes.
2. **Conditions C1–C5.** Today only C0 exists. Each condition is a converter variant — CRS,
   geometry type, semantics carrier, tolerance. Nothing else fills five sixths of the Volumes
   sheet, and without them there is no ablation and no profile.
3. **The database hop.** S2→S3 has never been run. It needs a PostGIS instance and the isolated
   reconstruction process. Until then, no sentence about the database is supportable — say
   "encoder measurements" and mean it.
4. **Route C.** The Sri Lankan condominium request. Start the paperwork now; approval time
   dominates everything else, and it is the only route that fills **Legal_Reference** and licenses
   the materiality claim.

---

## Four things to watch

**Schependomlaan is in millimetres.** Everything else is in metres. If the unit scale is applied
in the wrong place you get a factor of 1 000 in the volume, which is obvious, or a factor of 1 000
in the *tolerance*, which is not. Check it against the model's own `Qto_SpaceBaseQuantities` first.

**"10-Bldg" is one `IfcBuilding`.** Smiley West is named for ten blocks but the file declares a
single building. Treat it as one unit of independence, not ten, or you overstate n.

**Space boundaries do not mean party walls are labelled.** You now have 4 710 boundaries, which is
the raw material. Whether each identifies the neighbour a face is shared with is a separate check
— run it before promising the semantic metric in the paper.

**Six buildings is a real n, but a small one.** Enough for materiality argument and description;
the statistical claims still belong to the synthetic arm, exactly as §3.4 says.

---

## Sources

- KIT IFC Examples (FZK-Haus, Institute-Var-2, Smiley West) — <https://www.ifcwiki.org/index.php?title=KIT_IFC_Examples>
- Schependomlaan dataset — <https://github.com/openBIMstandards/Archive-DataSetSchependomlaan> (CC BY 4.0)
- IfcSampleFiles (Duplex, SampleHouse) — <https://github.com/youshengCode/IfcSampleFiles>
- Open IFC Model Repository, University of Auckland — <https://openifcmodel.cs.auckland.ac.nz/> (further models if six is not enough)
- buildingSMART sample and test files — <https://github.com/buildingSMART/Sample-Test-Files>
- STEP Tools sample IFC files — <https://www.steptools.com/docs/stpfiles/ifc/>
