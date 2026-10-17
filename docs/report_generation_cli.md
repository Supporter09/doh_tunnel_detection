# Comparison Report Generation CLI Specification

**Tool:** `scripts/generate_report.py`  
**Purpose:** Generate deterministic comparison reports and CSV tables connecting published paper baselines, Phase 1 tabular statistical benchmarks, and Phase 2 time-series packet-clump evaluations.  
**Audience:** Academic report generation, thesis evaluation, slide deck artifact generation.

---

## 1. Overview

The `generate_report.py` CLI provides a single, reproducible entrypoint to generate all comparison tables for the CIRA-CIC-DoHBrw-2020 reproduction study.

### Guarantees
- **Strict Provenance**: Every row carries an explicit provenance status badge (`[Paper-Reported]`, `[Project-Observed]`, `[Project-Calibrated]`, `[Project-Replication]`, `[Project-Corrected]`, `[Project-Improved]`, or `[Unavailable]`).
- **No Fabricated Numbers**: When Phase 2 time-series evaluations are absent or incomplete, metrics render explicitly as `unavailable`, never as `0.0` or speculative numbers.
- **Deterministic Reproduction**: Generates byte-identical Markdown and RFC 4180 CSV tables across repeated invocations.
- **Strict Schema Validation**: Incompatible, corrupted, or out-of-range metric payloads are rejected via `IncompatibleMetricSchemaError` (exit code 2).
- **Directory Protection**: Refuses to overwrite non-empty output directories unless `--force` is specified.
- **Atomic Staging**: Artifacts are staged in a temporary sibling directory and atomically committed to prevent partial outputs.

---

## 2. CLI Invocation Syntax

```bash
python3 scripts/generate_report.py \
  --phase1-l1 PATH \
  --phase1-l2 PATH \
  [--phase2-metrics PATH] \
  [--phase2-latency PATH] \
  --output-dir PATH \
  [--force] \
  [--markdown-filename FILENAME] \
  [--quiet]
```

### Parameter Reference

| Parameter | Type | Required | Description |
|---|:---:|:---:|---|
| `--phase1-l1`, `--l1-evidence` | Path | **Yes** | Path to Phase 1 Layer 1 evidence JSON (`task: "l1"`). |
| `--phase1-l2`, `--l2-evidence` | Path | **Yes** | Path to Phase 1 Layer 2 evidence JSON (`task: "l2"`). |
| `--phase2-metrics`, `--timeseries-metrics` | Path | No | Optional path to Phase 2 `metrics.json` artifact (from `train_timeseries.py`). |
| `--phase2-latency`, `--latency-benchmarks` | Path | No | Optional path to Phase A operational `latency_benchmarks.json` artifact (from `operational_latency.py`). |
| `--output-dir`, `-o` | Path | **Yes** | Destination directory for generated Markdown and CSV tables. |
| `--force`, `-f` | Flag | No | Allow overwriting an existing non-empty output directory. Default: `False`. |
| `--markdown-filename` | String | No | Custom name for the unified Markdown report. Default: `comparison_report.md`. |
| `--quiet`, `-q` | Flag | No | Suppress console summary output. Default: `False`. |

### Process Exit Codes
- `0`: Success. All artifacts staged and committed.
- `1`: File not found, directory overwrite conflict (without `--force`), or execution error.
- `2`: Schema validation error (`IncompatibleMetricSchemaError`).

---

## 3. Emitted Artifacts

The CLI generates 1 unified GitHub-flavored Markdown report and 6 CSV tables inside `--output-dir`:

| Artifact | Format | Primary Contents |
|---|:---:|---|
| `comparison_report.md` | Markdown | Master report with provenance taxonomy and all 6 formatted tables. |
| `statistical_comparison.csv` | CSV | Paper Tables III & IV vs Project 29-feature tabular baselines (RF, HGB). |
| `timeseries_window_sweeps.csv` | CSV | Paper Tables V & VI vs Project packet-clump LSTM ($l \in [1, 10]$). |
| `paper_vs_project.csv` | CSV | Head-to-head comparison at optimal operating points ($l=6$ for L1, $l=3$ for L2). |
| `corrected_vs_random_splits.csv` | CSV | Cross-session leakage assessment (80/20 flow-random vs 70/15/15 group-disjoint). |
| `latency_tradeoffs.csv` | CSV | Early detection delay analysis (0.50s–0.57s clump sequence vs 20s–54s full flow). |
| `improvements.csv` | CSV | Synthesis of algorithmic fixes, low-FPR calibration, group ablation, and BiGRU. |

---

## 4. Usage Examples

### Example A: Phase 1 Tabular Evidence Only (Phase 2 Time-Series Pending)
When raw PCAP time-series runs are not yet executed, Phase 2 rows automatically render as `unavailable` without fabricating numbers:

```bash
python3 scripts/generate_report.py \
  --phase1-l1 data/manifests/kaggle_phase1_l1_evidence.json \
  --phase1-l2 data/manifests/kaggle_phase1_l2_evidence.json \
  --output-dir reports/baseline_comparison/
```

### Example B: Complete Comparison with Phase 2 Multi-Task Metrics
When `train_timeseries.py` finishes and emits `metrics.json`:

```bash
python3 scripts/generate_report.py \
  --phase1-l1 data/manifests/kaggle_phase1_l1_evidence.json \
  --phase1-l2 data/manifests/kaggle_phase1_l2_evidence.json \
  --phase2-metrics artifacts/kaggle/metrics.json \
  --output-dir reports/full_comparison/ \
  --force
```

### Example C: Full Comparison with Operational Latency Evidence
When `train_timeseries.py` completes with `--enable-latency-benchmark` emitting `latency_benchmarks.json`:

```bash
python3 scripts/generate_report.py \
  --phase1-l1 data/manifests/kaggle_phase1_l1_evidence.json \
  --phase1-l2 data/manifests/kaggle_phase1_l2_evidence.json \
  --phase2-metrics artifacts/kaggle/metrics.json \
  --phase2-latency artifacts/kaggle/latency_benchmarks.json \
  --output-dir reports/full_comparison_with_latency/ \
  --force
```

### Example D: Programmatic Python API
The CLI logic is also directly importable for unit testing or automated pipelines:

```python
from pathlib import Path
from scripts.generate_report import generate_report

written_files = generate_report(
    phase1_l1_path=Path("data/manifests/kaggle_phase1_l1_evidence.json"),
    phase1_l2_path=Path("data/manifests/kaggle_phase1_l2_evidence.json"),
    output_dir=Path("reports/comparison/"),
    phase2_metrics_path=Path("artifacts/kaggle/metrics.json"),
    phase2_latency_path=Path("artifacts/kaggle/latency_benchmarks.json"),
    force=True,
)

print(f"Generated {len(written_files)} artifacts:")
for artifact_id, file_path in written_files.items():
    print(f"  {artifact_id}: {file_path}")
```
