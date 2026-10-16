#!/usr/bin/env python3
"""Deterministic report-generation CLI for CIRA-CIC-DoHBrw-2020 reproduction.

This CLI reads audited experimental evidence and produces comprehensive,
deterministic comparison artifacts:
1. One unified GitHub-flavored Markdown report connecting paper baselines,
   Phase 1 statistical flow baselines, and Phase 2 packet-clump time-series models.
2. Six RFC 4180 CSV tables corresponding to each evaluation perspective:
   - statistical_comparison.csv
   - timeseries_window_sweeps.csv
   - paper_vs_project.csv
   - corrected_vs_random_splits.csv
   - latency_tradeoffs.csv
   - improvements.csv

Guarantees:
- Validates all input manifests through canonical schema validators.
- Enforces strict provenance tracking for every metric row.
- Renders missing Phase 2 time-series evidence as 'unavailable' (never 0.0 or fabricated).
- Produces deterministic, byte-identical outputs across repeated runs.
- Guards against accidental overwriting of non-empty output directories unless --force.
- Performs atomic staging to prevent partial/corrupted output artifacts.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Path setup: ensure doh_reproduction package is discoverable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"

for _candidate in [_SCRIPT_DIR, _SRC_DIR, _PROJECT_ROOT]:
    _cand_str = str(_candidate)
    if _cand_str not in sys.path and _candidate.exists():
        sys.path.insert(0, _cand_str)

from doh_reproduction.comparison import (  # noqa: E402
    IncompatibleMetricSchemaError,
    export_all_tables_to_csv,
    export_all_tables_to_markdown,
    generate_full_comparison_report,
    load_evidence_json,
    load_timeseries_metrics,
)


def write_artifacts_atomically(
    output_dir: Path,
    markdown_content: str,
    csv_contents: Mapping[str, str],
    *,
    force: bool = False,
    markdown_filename: str = "comparison_report.md",
) -> dict[str, Path]:
    """Atomically write Markdown report and CSV tables into target directory.

    Args:
        output_dir: Target directory path.
        markdown_content: Rendered Markdown document string.
        csv_contents: Dict mapping table_id to CSV text string.
        force: If True, allow writing into an existing non-empty directory.
        markdown_filename: Name of the output Markdown file.

    Returns:
        Dict mapping artifact identifier to destination Path.

    Raises:
        NotADirectoryError: If output_dir exists and is not a directory.
        FileExistsError: If output_dir exists and is non-empty without force=True.
    """
    output_dir = output_dir.resolve()

    if output_dir.exists():
        if not output_dir.is_dir():
            raise NotADirectoryError(f"Output path exists and is not a directory: {output_dir}")
        existing_items = [p for p in output_dir.iterdir() if not p.name.startswith(".tmp_")]
        if existing_items and not force:
            raise FileExistsError(
                f"Output directory '{output_dir}' is not empty ({len(existing_items)} items found). "
                "Specify --force to overwrite."
            )
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Stage files in a temporary sibling directory to ensure atomic cross-file integrity
    stage_dir = Path(tempfile.mkdtemp(prefix=f".tmp_report_{output_dir.name}_", dir=output_dir.parent))
    written: dict[str, Path] = {}

    try:
        # 1. Write Markdown report in staging directory
        stage_md = stage_dir / markdown_filename
        with open(stage_md, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        written["markdown"] = output_dir / markdown_filename

        # 2. Write CSV tables in staging directory
        for table_id, csv_text in csv_contents.items():
            csv_name = f"{table_id}.csv"
            stage_csv = stage_dir / csv_name
            with open(stage_csv, "w", encoding="utf-8") as f:
                f.write(csv_text)
            written[table_id] = output_dir / csv_name

        # 3. Atomically move staged files into final destination
        for stage_file in stage_dir.iterdir():
            dest_file = output_dir / stage_file.name
            os.replace(stage_file, dest_file)

    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)

    return written


def generate_report(
    phase1_l1_path: Union[str, Path],
    phase1_l2_path: Union[str, Path],
    output_dir: Union[str, Path],
    *,
    phase2_metrics_path: Optional[Union[str, Path]] = None,
    force: bool = False,
    markdown_filename: str = "comparison_report.md",
) -> dict[str, Path]:
    """Validate manifests, generate all 6 comparison tables, and write report artifacts.

    Args:
        phase1_l1_path: Path to Phase 1 Layer 1 evidence JSON.
        phase1_l2_path: Path to Phase 1 Layer 2 evidence JSON.
        output_dir: Directory where artifacts are saved.
        phase2_metrics_path: Optional path to Phase 2 metrics.json artifact.
        force: If True, allow overwriting a non-empty directory.
        markdown_filename: Name of the generated unified Markdown file.

    Returns:
        Mapping from artifact identifier to written Path.

    Raises:
        FileNotFoundError: If any specified evidence file does not exist.
        IncompatibleMetricSchemaError: If an evidence payload violates schema.
        FileExistsError: If output_dir is non-empty without force=True.
    """
    out_path = Path(output_dir).resolve()

    # Pre-check overwrite guard before parsing manifests
    if out_path.exists():
        if not out_path.is_dir():
            raise NotADirectoryError(f"Output path exists and is not a directory: {out_path}")
        existing = [p for p in out_path.iterdir() if not p.name.startswith(".tmp_")]
        if existing and not force:
            raise FileExistsError(
                f"Output directory '{out_path}' is not empty ({len(existing)} items found). "
                "Specify --force to overwrite."
            )

    # 1. Load and validate Phase 1 evidence manifests
    evidence_l1 = load_evidence_json(phase1_l1_path)
    if evidence_l1.get("task") != "l1":
        raise IncompatibleMetricSchemaError(
            f"Phase 1 L1 evidence at '{phase1_l1_path}' has task='{evidence_l1.get('task')}', expected 'l1'."
        )

    evidence_l2 = load_evidence_json(phase1_l2_path)
    if evidence_l2.get("task") != "l2":
        raise IncompatibleMetricSchemaError(
            f"Phase 1 L2 evidence at '{phase1_l2_path}' has task='{evidence_l2.get('task')}', expected 'l2'."
        )

    # 2. Load and validate Phase 2 time-series metrics if provided
    timeseries_l1 = None
    timeseries_l2 = None
    flow_random_metrics = None
    group_disjoint_metrics = None

    if phase2_metrics_path is not None:
        ts_metrics = load_timeseries_metrics(phase2_metrics_path)
        task_or_layer = ts_metrics.get("task") or ts_metrics.get("layer")

        if task_or_layer in ("both", None):
            timeseries_l1 = ts_metrics
            timeseries_l2 = ts_metrics
        elif task_or_layer in ("l1", "layer1_doh_vs_nondoh"):
            timeseries_l1 = ts_metrics
            timeseries_l2 = None
        elif task_or_layer in ("l2", "layer2_benign_vs_malicious"):
            timeseries_l1 = None
            timeseries_l2 = ts_metrics
        else:
            timeseries_l1 = ts_metrics
            timeseries_l2 = ts_metrics

        flow_random_metrics = ts_metrics
        group_disjoint_metrics = ts_metrics

    # 3. Generate all 6 deterministic comparison tables
    tables = generate_full_comparison_report(
        evidence_l1=evidence_l1,
        evidence_l2=evidence_l2,
        timeseries_l1=timeseries_l1,
        timeseries_l2=timeseries_l2,
        flow_random_metrics=flow_random_metrics,
        group_disjoint_metrics=group_disjoint_metrics,
    )

    # 4. Export Markdown and CSV content
    md_content = export_all_tables_to_markdown(tables)
    csv_contents = export_all_tables_to_csv(tables)

    # 5. Atomically commit artifacts to disk
    written = write_artifacts_atomically(
        output_dir=out_path,
        markdown_content=md_content,
        csv_contents=csv_contents,
        force=force,
        markdown_filename=markdown_filename,
    )

    return written


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser with full parameter documentation."""
    parser = argparse.ArgumentParser(
        prog="generate_report.py",
        description=(
            "Generate deterministic CIRA-CIC-DoHBrw-2020 experimental comparison reports. "
            "Synthesizes immutable paper values (Tables III–VI), verified Phase 1 tabular "
            "baselines, and Phase 2 time-series packet-clump evaluations into 1 Markdown "
            "document and 6 CSV tables."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--phase1-l1",
        "--l1-evidence",
        "--evidence-l1",
        dest="phase1_l1",
        required=True,
        type=Path,
        help="Path to Phase 1 Layer 1 evidence JSON (e.g., data/manifests/kaggle_phase1_l1_evidence.json)",
    )
    parser.add_argument(
        "--phase1-l2",
        "--l2-evidence",
        "--evidence-l2",
        dest="phase1_l2",
        required=True,
        type=Path,
        help="Path to Phase 1 Layer 2 evidence JSON (e.g., data/manifests/kaggle_phase1_l2_evidence.json)",
    )
    parser.add_argument(
        "--phase2-metrics",
        "--timeseries-metrics",
        "--metrics-json",
        dest="phase2_metrics",
        default=None,
        type=Path,
        help="Optional path to Phase 2 time-series metrics.json artifact (from train_timeseries.py)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        dest="output_dir",
        required=True,
        type=Path,
        help="Directory where Markdown report and CSV tables will be written",
    )
    parser.add_argument(
        "--force",
        "-f",
        dest="force",
        action="store_true",
        default=False,
        help="Allow overwriting output files if output directory already exists and is non-empty",
    )
    parser.add_argument(
        "--markdown-filename",
        dest="markdown_filename",
        default="comparison_report.md",
        type=str,
        help="Filename for the generated unified Markdown comparison report",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        dest="quiet",
        action="store_true",
        default=False,
        help="Suppress console summary output",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI execution entrypoint returning standard process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        written = generate_report(
            phase1_l1_path=args.phase1_l1,
            phase1_l2_path=args.phase1_l2,
            output_dir=args.output_dir,
            phase2_metrics_path=args.phase2_metrics,
            force=args.force,
            markdown_filename=args.markdown_filename,
        )
    except FileNotFoundError as err:
        sys.stderr.write(f"File Error: {err}\n")
        return 1
    except IncompatibleMetricSchemaError as err:
        sys.stderr.write(f"Schema Error: {err}\n")
        return 2
    except FileExistsError as err:
        sys.stderr.write(f"Overwrite Error: {err}\n")
        return 1
    except Exception as err:
        sys.stderr.write(f"Execution Error: {err}\n")
        return 1

    if not args.quiet:
        sys.stdout.write(f"Report generation complete. Artifacts written to: {args.output_dir}\n")
        sys.stdout.write(f"  Markdown: {written['markdown'].name}\n")
        csv_keys = [k for k in written if k != "markdown"]
        sys.stdout.write(f"  CSVs ({len(csv_keys)} tables):\n")
        for k in sorted(csv_keys):
            sys.stdout.write(f"    - {written[k].name}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
