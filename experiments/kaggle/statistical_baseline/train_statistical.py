#!/usr/bin/env python3
"""Statistical baseline training and schema audit runner for Kaggle CPU environment.

Scope:
    Evaluates tabular/statistical baseline classifiers (Random Forest, Decision Tree,
    Gaussian Naive Bayes, Linear SVM) on summary flow features from CIRA-CIC-DoHBrw-2020.
    This script strictly does NOT replicate packet-clump time-series sequence models (LSTM),
    which require packet order, direction, and inter-arrival timestamps from raw PCAP traces.

Artifacts emitted to --output-dir:
    - schema_audit.json
    - metrics.json
    - experiment_manifest.json
    - confusion_matrix_<model>.csv

Security and Boundaries:
    - Never logs credentials, API keys, or personal filesystem paths.
    - Never saves binary model checkpoints (.pkl, .pt, .h5).
    - Requires explicit --task (l1 or l2) and validated labels before training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd
try:
    import scipy
    SCIPY_VERSION: str = getattr(scipy, "__version__", "unknown")
except ImportError:
    SCIPY_VERSION = "not_installed"

try:
    import sklearn
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split
    from sklearn.naive_bayes import GaussianNB
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import LinearSVC
    from sklearn.tree import DecisionTreeClassifier
    SKLEARN_AVAILABLE = True
    SKLEARN_VERSION: str = getattr(sklearn, "__version__", "unknown")
except ImportError:
    SKLEARN_AVAILABLE = False
    SKLEARN_VERSION = "not_installed"

try:
    import pyarrow
    PYARROW_VERSION: str = getattr(pyarrow, "__version__", "unknown")
    try:
        import pyarrow.parquet as pq
    except ImportError:
        pq = None
except ImportError:
    pyarrow = None
    pq = None
    PYARROW_VERSION = "not_installed"

# Explicit script constant for runner wrapper injection of reviewed JSON configuration.
# When running on remote Kaggle without an uploaded run_config.json file,
# push wrappers may inject a JSON string or dict here.
EMBEDDED_CONFIG_JSON = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("kaggle_statistical_baseline")

# Identifier columns to strip from feature matrix to prevent identity leakage
# (Per Section 5 of data contract: IP, port, timestamp, flow ID must never enter features)
IDENTIFIER_COLUMNS: Set[str] = {
    "flow id",
    "flow_id",
    "flowid",
    "source ip",
    "source_ip",
    "src ip",
    "src_ip",
    "srcip",
    "sourceip",
    "destination ip",
    "destination_ip",
    "dst ip",
    "dst_ip",
    "dstip",
    "destinationip",
    "source port",
    "source_port",
    "src port",
    "src_port",
    "srcport",
    "sourceport",
    "destination port",
    "destination_port",
    "dst port",
    "dst_port",
    "dstport",
    "destinationport",
    "protocol",
    "timestamp",
    "time_stamp",
    "time stamp",
    "date",
    "mac",
    "src mac",
    "dst mac",
    "source mac",
    "destination mac",
}

# Documented accepted source label strings for Layer 1 (DoH vs Non-DoH)
# Canonical targets: "non_doh" (0), "doh" (1)
L1_LABEL_MAP: Dict[str, str] = {
    # Non-DoH sources
    "non-doh": "non_doh",
    "nondoh": "non_doh",
    "non_doh": "non_doh",
    "non doh": "non_doh",
    "non-doh-browsing": "non_doh",
    "nondoh-browsing": "non_doh",
    # DoH sources
    "doh": "doh",
    "doh-browsing": "doh",
    "doh-tunnel": "doh",
    "benign-doh": "doh",
    "benigndoh": "doh",
    "benign_doh": "doh",
    "benign doh": "doh",
    "malicious-doh": "doh",
    "maliciousdoh": "doh",
    "malicious_doh": "doh",
    "malicious doh": "doh",
    "benign": "doh",
    "malicious": "doh",
    "chrome": "doh",
    "firefox": "doh",
    "dns2tcp": "doh",
    "dnscat2": "doh",
    "iodine": "doh",
}

# Documented accepted source label strings for Layer 2 (Benign DoH vs Malicious DoH)
# Canonical targets: "benign_doh" (0), "malicious_doh" (1)
L2_LABEL_MAP: Dict[str, str] = {
    # Benign DoH sources
    "benign": "benign_doh",
    "benign-doh": "benign_doh",
    "benigndoh": "benign_doh",
    "benign_doh": "benign_doh",
    "benign doh": "benign_doh",
    "browsing": "benign_doh",
    "chrome": "benign_doh",
    "firefox": "benign_doh",
    "doh-browsing": "benign_doh",
    # Malicious DoH sources (Tunnels)
    "malicious": "malicious_doh",
    "malicious-doh": "malicious_doh",
    "maliciousdoh": "malicious_doh",
    "malicious_doh": "malicious_doh",
    "malicious doh": "malicious_doh",
    "tunneling": "malicious_doh",
    "tunnel": "malicious_doh",
    "doh-tunnel": "malicious_doh",
    "dns2tcp": "malicious_doh",
    "dnscat2": "malicious_doh",
    "iodine": "malicious_doh",
}

NON_DOH_LABELS: Set[str] = {
    "non-doh",
    "nondoh",
    "non_doh",
    "non doh",
    "non-doh-browsing",
    "nondoh-browsing",
}


def compute_file_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash by streaming binary chunks to prevent OOM."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def count_file_lines(filepath: Path) -> int:
    """Count lines in file efficiently using binary chunking."""
    lines = 0
    with open(filepath, "rb") as f:
        while chunk := f.read(1048576):
            lines += chunk.count(b"\n")
    return lines


def sanitize_path_for_report(path: Path, base_dir: Path) -> str:
    """Return relative path or sanitized path name, avoiding local machine roots."""
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return path.name


def get_file_format(filepath: Path) -> str:
    """Determine tabular file format from extension."""
    suffix = filepath.suffix.lower()
    if suffix == ".csv":
        return "csv"
    elif suffix in (".parquet", ".pq"):
        return "parquet"
    return "unknown"


def load_tabular_data(
    filepath: Path, nrows: Optional[int] = None
) -> Tuple[pd.DataFrame, str]:
    """Load tabular dataset from CSV or Parquet using pandas.

    Returns:
        (DataFrame, file_format)
    """
    fmt = get_file_format(filepath)
    if fmt == "csv":
        df = pd.read_csv(filepath, nrows=nrows)
        return df, fmt
    elif fmt == "parquet":
        try:
            df = pd.read_parquet(filepath)
            if nrows is not None:
                df = df.iloc[:nrows]
            return df, fmt
        except ImportError as err:
            raise RuntimeError(
                f"Parquet engine is unavailable in pandas while loading '{filepath.name}'. "
                "pandas requires 'pyarrow' (recommended) or 'fastparquet' to load Parquet files. "
                "Please ensure 'pyarrow' is installed."
            ) from err
        except Exception as err:
            raise RuntimeError(
                f"Failed to load Parquet file '{filepath.name}' using pandas: {err}"
            ) from err
    else:
        raise ValueError(
            f"Unsupported file format for '{filepath.name}'. Supported formats are CSV and Parquet."
        )


CANDIDATE_LABEL_KEYWORDS: Tuple[str, ...] = (
    "label",
    "class",
    "target",
    "scenario",
    "category",
    "tunnel",
    "traffic",
    "doh",
    "activity",
    "type",
)


def audit_candidate_label_column(
    tabular_path: Path,
    file_format: str,
    raw_col: str,
    clean_col: str,
    pq_file: Optional[Any] = None,
) -> Dict[str, Any]:
    """Calculate the complete value-count distribution for a candidate label column.

    Uses format-specific column projection for Parquet and safe chunking for CSV
    to avoid loading numeric features into memory. Fails clearly if full audit cannot run.
    """
    logger.info(
        f"Auditing complete candidate label distribution for column '{clean_col}' "
        f"in {file_format.upper()} '{tabular_path.name}'..."
    )
    if file_format == "csv":
        chunk_size = 100_000
        total_rows = 0
        null_count = 0
        counts_acc: Dict[str, int] = {}
        try:
            for chunk in pd.read_csv(tabular_path, usecols=[raw_col], chunksize=chunk_size):
                total_rows += len(chunk)
                col_s = chunk[raw_col]
                null_count += int(col_s.isna().sum())
                non_null_clean = col_s.dropna().astype(str).str.strip()
                for val, count in non_null_clean.value_counts().items():
                    val_str = str(val)
                    counts_acc[val_str] = counts_acc.get(val_str, 0) + int(count)
        except Exception as err:
            raise RuntimeError(
                f"Failed to perform complete label audit for candidate column '{clean_col}' "
                f"in CSV file '{tabular_path.name}': {err}"
            ) from err

        sorted_counts = dict(sorted(counts_acc.items(), key=lambda item: (-item[1], item[0])))

    elif file_format == "parquet":
        try:
            if pq_file is not None:
                col_table = pq_file.read(columns=[raw_col])
                series = col_table[raw_col].to_pandas()
            else:
                label_df = pd.read_parquet(tabular_path, columns=[raw_col])
                series = label_df[raw_col]
        except Exception as err:
            raise RuntimeError(
                f"Failed to perform complete label audit for candidate column '{clean_col}' "
                f"in Parquet file '{tabular_path.name}' using column projection: {err}"
            ) from err

        total_rows = len(series)
        null_count = int(series.isna().sum())
        non_null_clean = series.dropna().astype(str).str.strip()
        val_counts = non_null_clean.value_counts()
        sorted_counts = {str(k): int(v) for k, v in val_counts.items()}

    else:
        raise ValueError(f"Unsupported tabular format for label audit: '{file_format}'")

    unique_vals = list(sorted_counts.keys())
    return {
        "complete_column_audit": True,
        "is_complete_audit": True,
        "total_rows": total_rows,
        "null_count": null_count,
        "unique_count": len(sorted_counts),
        "value_counts": sorted_counts,
        "sample_unique_values": unique_vals[:20],
        "sample_unique_count": len(unique_vals[:20]),
    }


def discover_and_audit_tabular_files(
    input_dir: Path, output_dir: Path, config_source: str = "defaults"
) -> Tuple[Dict[str, Any], List[Path]]:
    """Recursively discover tabular data files (CSV, Parquet) under input_dir and generate schema_audit.json."""
    logger.info(f"Scanning for tabular data files in input directory: {input_dir}")
    discovered_paths: List[Path] = []
    if input_dir.exists():
        for root, _, files in os.walk(input_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in (".csv", ".parquet", ".pq"):
                    discovered_paths.append(Path(root) / file)

    discovered_paths.sort()
    logger.info(f"Discovered {len(discovered_paths)} tabular file(s).")

    audit_records: List[Dict[str, Any]] = []
    for tabular_path in discovered_paths:
        file_format = get_file_format(tabular_path)
        file_size = tabular_path.stat().st_size
        sha256 = compute_file_sha256(tabular_path)

        if file_format == "csv":
            raw_lines = count_file_lines(tabular_path)
            est_rows = max(0, raw_lines - 1) if raw_lines > 0 else 0
            sample_df = pd.read_csv(tabular_path, nrows=50)
            raw_cols = list(sample_df.columns)
            clean_cols = [str(c).strip() for c in raw_cols]
            clean_to_raw = {clean: raw for clean, raw in zip(clean_cols, raw_cols)}
            dtypes_dict = {col: str(sample_df.dtypes.iloc[i]) for i, col in enumerate(clean_cols)}

            candidate_labels: Dict[str, Any] = {}
            for col in clean_cols:
                col_lower = col.lower()
                if any(k in col_lower for k in CANDIDATE_LABEL_KEYWORDS):
                    audit_res = audit_candidate_label_column(
                        tabular_path=tabular_path,
                        file_format=file_format,
                        raw_col=clean_to_raw[col],
                        clean_col=col,
                    )
                    candidate_labels[col] = audit_res
                    if est_rows == 0 or est_rows != audit_res["total_rows"]:
                        est_rows = audit_res["total_rows"]
        elif file_format == "parquet":
            pq_file = None
            if pq is not None:
                try:
                    pq_file = pq.ParquetFile(tabular_path)
                    est_rows = int(pq_file.metadata.num_rows)
                    arrow_schema = pq_file.schema_arrow
                    raw_cols = list(arrow_schema.names)
                    clean_cols = [str(c).strip() for c in raw_cols]
                    clean_to_raw = {clean: raw for clean, raw in zip(clean_cols, raw_cols)}
                    try:
                        empty_df = arrow_schema.empty_table().to_pandas()
                        dtypes_dict = {
                            col: str(empty_df.dtypes.iloc[i]) for i, col in enumerate(clean_cols)
                        }
                    except Exception:
                        dtypes_dict = {
                            col: str(arrow_schema.field(i).type)
                            for i, col in enumerate(clean_cols)
                        }
                except Exception as err:
                    raise RuntimeError(
                        f"Failed to inspect Parquet metadata for '{tabular_path.name}' using PyArrow: {err}"
                    ) from err
            else:
                try:
                    sample_df = pd.read_parquet(tabular_path)
                    est_rows = len(sample_df)
                    raw_cols = list(sample_df.columns)
                    clean_cols = [str(c).strip() for c in raw_cols]
                    clean_to_raw = {clean: raw for clean, raw in zip(clean_cols, raw_cols)}
                    dtypes_dict = {
                        col: str(sample_df.dtypes.iloc[i]) for i, col in enumerate(clean_cols)
                    }
                except ImportError as err:
                    raise RuntimeError(
                        f"Parquet engine is unavailable in pandas while inspecting '{tabular_path.name}'. "
                        "pandas requires 'pyarrow' (recommended) or 'fastparquet' to read Parquet files. "
                        "Please ensure 'pyarrow' is installed."
                    ) from err
                except Exception as err:
                    raise RuntimeError(
                        f"Failed to inspect Parquet schema for '{tabular_path.name}': {err}"
                    ) from err

            candidate_labels = {}
            for col in clean_cols:
                col_lower = col.lower()
                if any(k in col_lower for k in CANDIDATE_LABEL_KEYWORDS):
                    audit_res = audit_candidate_label_column(
                        tabular_path=tabular_path,
                        file_format=file_format,
                        raw_col=clean_to_raw[col],
                        clean_col=col,
                        pq_file=pq_file,
                    )
                    candidate_labels[col] = audit_res
        else:
            logger.warning(f"Skipping unsupported tabular format for: {tabular_path}")
            continue

        audit_records.append(
            {
                "filename": tabular_path.name,
                "relative_path": sanitize_path_for_report(tabular_path, input_dir),
                "format": file_format,
                "size_bytes": file_size,
                "sha256": sha256,
                "row_count": est_rows,
                "column_count": len(clean_cols),
                "columns": clean_cols,
                "dtypes": dtypes_dict,
                "candidate_label_columns": candidate_labels,
            }
        )

    git_sha = os.environ.get("KAGGLE_GIT_SHA", "unknown")
    source_snapshot_sha256 = os.environ.get("KAGGLE_SOURCE_SNAPSHOT_SHA256", "unknown")
    audit_payload: Dict[str, Any] = {
        "audit_version": "1.0.0",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": git_sha,
        "source_snapshot_sha256": source_snapshot_sha256,
        "config_source": config_source,
        "input_directory": str(input_dir),
        "total_tabular_files_found": len(audit_records),
        "total_csv_files_found": len([r for r in audit_records if r.get("format") == "csv"]),
        "total_parquet_files_found": len([r for r in audit_records if r.get("format") == "parquet"]),
        "discovered_tabular_files": audit_records,
        "discovered_csvs": audit_records,
        "status": "audit_complete",
    }

    schema_audit_path = output_dir / "schema_audit.json"
    with open(schema_audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, indent=2)
    logger.info(f"Schema audit successfully written to {schema_audit_path.name}")

    return audit_payload, discovered_paths


# Backward-compatibility alias
discover_and_audit_csvs = discover_and_audit_tabular_files


def resolve_selected_data_file(
    data_arg: str, input_dir: Path, discovered_paths: List[Path]
) -> Optional[Path]:
    """Find the specific tabular data file (CSV or Parquet) requested by the caller."""
    candidate = Path(data_arg)
    if candidate.is_file():
        return candidate.resolve()

    candidate_under_input = input_dir / data_arg
    if candidate_under_input.is_file():
        return candidate_under_input.resolve()

    for p in discovered_paths:
        if p.name == data_arg or str(p).endswith(data_arg):
            return p.resolve()

    return None


# Backward-compatibility alias
resolve_selected_csv = resolve_selected_data_file


def resolve_label_column(
    columns: Sequence[str], user_label_col: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve and validate the label column name.

    Returns:
        (resolved_column_name, error_message)
    """
    col_map = {c.lower(): c for c in columns}
    if user_label_col is not None:
        user_lower = user_label_col.strip().lower()
        if user_lower in col_map:
            return col_map[user_lower], None
        return None, (
            f"Explicitly specified --label-column '{user_label_col}' was not found in dataset columns. "
            f"Available columns: {list(columns)}"
        )

    # Search for unambiguous label column
    exact_label_matches = [c for c in columns if c.strip().lower() in ("label", "class")]
    if len(exact_label_matches) == 1:
        return exact_label_matches[0], None

    fuzzy_matches = [
        c for c in columns if any(k in c.strip().lower() for k in ("label", "class", "target"))
    ]
    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0], None

    if len(fuzzy_matches) > 1:
        return None, (
            f"Multiple candidate label columns found: {fuzzy_matches}. "
            "Please specify --label-column explicitly to avoid ambiguous training."
        )

    return None, (
        "No unambiguous label column ('Label' or 'Class') found in dataset. "
        "Please specify --label-column explicitly."
    )


def map_and_validate_labels(
    series: pd.Series, task: str
) -> Tuple[pd.Series, Dict[str, int], List[str]]:
    """Map source label strings to canonical binary classes and validate.

    Returns:
        (mapped_series, class_mapping, target_names)
    """
    cleaned = series.dropna().astype(str).str.strip().str.lower()

    if task == "l1":
        target_names = ["non_doh", "doh"]
        mapping_dict = L1_LABEL_MAP
        target_int_map = {"non_doh": 0, "doh": 1}

        # Check for unmapped labels
        unknown_labels = set(cleaned.unique()) - set(mapping_dict.keys())
        if unknown_labels:
            raise ValueError(
                f"Refusing to train: Unrecognized label(s) for Task L1: {sorted(unknown_labels)}. "
                f"Accepted documented labels: {sorted(mapping_dict.keys())}"
            )

        canonical = cleaned.map(mapping_dict)
        numeric = canonical.map(target_int_map)
        return numeric, target_int_map, target_names

    elif task == "l2":
        target_names = ["benign_doh", "malicious_doh"]
        mapping_dict = L2_LABEL_MAP
        target_int_map = {"benign_doh": 0, "malicious_doh": 1}

        # If Non-DoH rows are present in an L2 run, drop them with explicit logging
        non_doh_mask = cleaned.isin(NON_DOH_LABELS)
        if non_doh_mask.any():
            dropped_count = int(non_doh_mask.sum())
            logger.info(
                f"Task L2 evaluates Benign DoH vs Malicious DoH tunnels. "
                f"Filtered out {dropped_count} Non-DoH rows."
            )
            cleaned = cleaned[~non_doh_mask]

        unknown_labels = set(cleaned.unique()) - set(mapping_dict.keys())
        if unknown_labels:
            raise ValueError(
                f"Refusing to train: Unrecognized label(s) for Task L2: {sorted(unknown_labels)}. "
                f"Accepted documented labels: {sorted(mapping_dict.keys())}"
            )

        canonical = cleaned.map(mapping_dict)
        numeric = canonical.map(target_int_map)
        return numeric, target_int_map, target_names

    else:
        raise ValueError(f"Unsupported task: '{task}'. Must be 'l1' or 'l2'.")


def prepare_features(
    df: pd.DataFrame, label_col: str
) -> Tuple[pd.DataFrame, List[str], List[str]]:
    """Strip identifier columns and coerce features to numeric float32."""
    df.columns = [str(c).strip() for c in df.columns]
    feature_cols: List[str] = []
    stripped_cols: List[str] = []

    for c in df.columns:
        if c == label_col or c == "__target__" or c.startswith("__"):
            continue
        c_clean = c.lower().replace("-", " ").replace("_", " ").strip()
        if c_clean in IDENTIFIER_COLUMNS or c.lower() in IDENTIFIER_COLUMNS:
            stripped_cols.append(c)
        else:
            feature_cols.append(c)

    logger.info(
        f"Retained {len(feature_cols)} feature column(s). "
        f"Stripped {len(stripped_cols)} identifier column(s) ({stripped_cols})."
    )

    X_df = df[feature_cols].copy()
    for col in feature_cols:
        X_df[col] = pd.to_numeric(X_df[col], errors="coerce")

    # Drop columns that became entirely NaN
    valid_cols = [c for c in feature_cols if not X_df[c].isna().all()]
    if len(valid_cols) < len(feature_cols):
        dropped_all_nan = set(feature_cols) - set(valid_cols)
        logger.warning(f"Dropped entirely NaN feature columns: {dropped_all_nan}")
        X_df = X_df[valid_cols]
        feature_cols = valid_cols

    # Replace infinities with NaN
    X_df = X_df.replace([np.inf, -np.inf], np.nan)
    return X_df, feature_cols, stripped_cols


def run_training_pipeline(
    data_path: Optional[Path] = None,
    task: str = "",
    label_col: str = "",
    models_to_run: Optional[List[str]] = None,
    seed: int = 42,
    max_samples_per_class: Optional[int] = None,
    output_dir: Optional[Path] = None,
    dataset_slug: str = "dhoogla/cicdohbrw2020",
    dataset_version: str = "3",
    audit_data: Optional[Dict[str, Any]] = None,
    run_config: Optional[Dict[str, Any]] = None,
    config_source: str = "defaults",
    csv_path: Optional[Path] = None,
) -> None:
    """Execute tabular baseline training and emit small reproducibility artifacts."""
    if data_path is None and csv_path is not None:
        data_path = csv_path
    if data_path is None:
        raise ValueError("data_path must be provided to run_training_pipeline")
    if models_to_run is None:
        models_to_run = ["random_forest", "decision_tree", "gaussian_nb", "linear_svm"]
    if output_dir is None:
        output_dir = Path("/kaggle/working")
    if audit_data is None:
        audit_data = {}

    logger.info(f"Loading dataset from: {data_path.name}")
    df, file_format = load_tabular_data(data_path)
    total_raw_rows = len(df)
    logger.info(f"Loaded {total_raw_rows} row(s) and {len(df.columns)} column(s) (format: {file_format}).")

    # Map labels
    mapped_labels, _, target_names = map_and_validate_labels(df[label_col], task=task)
    valid_row_indices = mapped_labels.index
    y_series = mapped_labels.astype(int)

    # Prepare features (pass only valid rows without modifying original df with target column)
    X_df, feature_cols, stripped_cols = prepare_features(df.loc[valid_row_indices], label_col)

    # Clean NaN rows (per paper: n < 50 NaN flows dropped in preprocessing)
    nan_mask = X_df.isna().any(axis=1)
    if nan_mask.any():
        nan_count = int(nan_mask.sum())
        logger.info(f"Dropping {nan_count} row(s) containing NaN / Inf values.")
        valid_idx = X_df.index[~nan_mask]
        X_df = X_df.loc[valid_idx]
        y_series = y_series.loc[valid_idx]

    X = X_df.to_numpy(dtype=np.float32)
    y = y_series.to_numpy(dtype=np.int64)

    # Verify binary classes present
    unique_classes, counts = np.unique(y, return_counts=True)
    class_count_dict = {target_names[int(c)]: int(cnt) for c, cnt in zip(unique_classes, counts)}
    logger.info(f"Class distribution before split/cap: {class_count_dict}")
    if len(unique_classes) < 2:
        raise ValueError(
            f"Dataset contains only {len(unique_classes)} class ({class_count_dict}). "
            "Binary classification requires both classes."
        )

    # Optional per-class sample cap
    if max_samples_per_class is not None and max_samples_per_class > 0:
        rng = np.random.default_rng(seed)
        selected_indices: List[int] = []
        for c in unique_classes:
            c_indices = np.where(y == c)[0]
            if len(c_indices) > max_samples_per_class:
                sampled = rng.choice(c_indices, size=max_samples_per_class, replace=False)
                selected_indices.extend(sampled.tolist())
            else:
                selected_indices.extend(c_indices.tolist())
        selected_indices.sort()
        X = X[selected_indices]
        y = y[selected_indices]
        logger.info(
            f"Applied per-class cap of {max_samples_per_class}. "
            f"Total samples after cap: {len(y)}"
        )

    if not SKLEARN_AVAILABLE:
        raise RuntimeError(
            "scikit-learn is not installed in the current Python environment. "
            "Please ensure scikit-learn is installed to execute model training."
        )

    # 80/20 Stratified Flow Split (Paper comparison protocol: paper_flow_random_80_20)
    split_protocol_name = "paper_flow_random_80_20"
    logger.info(f"Performing stratified 80/20 split (protocol: {split_protocol_name}, seed={seed})")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=seed, stratify=y, shuffle=True
    )

    train_dist = {target_names[int(c)]: int(np.sum(y_train == c)) for c in (0, 1)}
    test_dist = {target_names[int(c)]: int(np.sum(y_test == c)) for c in (0, 1)}
    logger.info(f"Train split samples: {len(y_train)} ({train_dist})")
    logger.info(f"Test split samples:  {len(y_test)} ({test_dist})")

    # Fit Imputer strictly on Train fold if any NaNs remain
    if np.isnan(X_train).any() or np.isnan(X_test).any():
        logger.info("Applying SimpleImputer (median) fit on Train fold only.")
        imputer = SimpleImputer(strategy="median")
        X_train = imputer.fit_transform(X_train)
        X_test = imputer.transform(X_test)

    # Fit StandardScaler strictly on Train fold for Linear SVM
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Baseline models dictionary
    # Siêu tham số theo Section 7.2 of replication_protocol.md
    model_factories = {
        "random_forest": lambda: (
            RandomForestClassifier(
                n_estimators=100,
                criterion="gini",
                min_samples_split=2,
                random_state=seed,
                n_jobs=-1,
            ),
            False,
        ),
        "decision_tree": lambda: (
            DecisionTreeClassifier(
                criterion="entropy",
                splitter="best",
                min_samples_split=2,
                random_state=seed,
            ),
            False,
        ),
        "gaussian_nb": lambda: (GaussianNB(var_smoothing=1e-9), False),
        "linear_svm": lambda: (
            LinearSVC(C=1.0, max_iter=2000, random_state=seed, dual=False),
            True,
        ),
    }

    all_metrics: Dict[str, Any] = {}
    model_params_record: Dict[str, Any] = {}
    generated_cm_files: List[str] = []

    for model_name in models_to_run:
        if model_name not in model_factories:
            logger.warning(f"Skipping unknown model: {model_name}")
            continue

        model, requires_scaling = model_factories[model_name]()
        model_params_record[model_name] = model.get_params()
        cur_X_train = X_train_scaled if requires_scaling else X_train
        cur_X_test = X_test_scaled if requires_scaling else X_test

        logger.info(f"Training model: {model_name}...")
        t0 = time.time()
        model.fit(cur_X_train, y_train)
        fit_time = time.time() - t0

        logger.info(f"Evaluating {model_name} on test set...")
        t1 = time.time()
        y_pred = model.predict(cur_X_test)
        inference_time = time.time() - t1

        # Calculate metrics
        acc = float(accuracy_score(y_test, y_pred))
        p_macro = float(precision_score(y_test, y_pred, average="macro", zero_division=0))
        r_macro = float(recall_score(y_test, y_pred, average="macro", zero_division=0))
        f1_macro_val = float(f1_score(y_test, y_pred, average="macro", zero_division=0))

        p_weighted = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
        r_weighted = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        f1_weighted_val = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))

        cm = confusion_matrix(y_test, y_pred, labels=[0, 1])
        tn, fp, fn, tp = [int(v) for v in cm.ravel()]

        p_pos = float(precision_score(y_test, y_pred, pos_label=1, zero_division=0))
        r_pos = float(recall_score(y_test, y_pred, pos_label=1, zero_division=0))
        f1_pos = float(f1_score(y_test, y_pred, pos_label=1, zero_division=0))
        fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0

        roc_auc_val: Optional[float] = None
        if hasattr(model, "predict_proba"):
            try:
                y_prob = model.predict_proba(cur_X_test)[:, 1]
                roc_auc_val = float(roc_auc_score(y_test, y_prob))
            except Exception:
                roc_auc_val = None
        elif hasattr(model, "decision_function"):
            try:
                y_score = model.decision_function(cur_X_test)
                roc_auc_val = float(roc_auc_score(y_test, y_score))
            except Exception:
                roc_auc_val = None

        all_metrics[model_name] = {
            "accuracy": acc,
            "precision_macro": p_macro,
            "recall_macro": r_macro,
            "f1_macro": f1_macro_val,
            "precision_weighted": p_weighted,
            "recall_weighted": r_weighted,
            "f1_weighted": f1_weighted_val,
            "precision_positive_class": p_pos,
            "recall_positive_class": r_pos,
            "f1_positive_class": f1_pos,
            "false_positive_rate": fpr,
            "roc_auc": roc_auc_val,
            "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
            "fit_time_seconds": round(fit_time, 4),
            "inference_time_seconds": round(inference_time, 4),
            "inference_latency_per_sample_ms": round((inference_time / len(y_test)) * 1000, 6),
        }

        # Write confusion matrix CSV
        cm_filename = f"confusion_matrix_{model_name}.csv"
        cm_path = output_dir / cm_filename
        cm_df = pd.DataFrame(
            [
                [f"true_{target_names[0]}", tn, fp],
                [f"true_{target_names[1]}", fn, tp],
            ],
            columns=["true_label", f"pred_{target_names[0]}", f"pred_{target_names[1]}"],
        )
        cm_df.to_csv(cm_path, index=False)
        generated_cm_files.append(cm_filename)
        logger.info(
            f"[{model_name}] Accuracy: {acc:.4f} | F1 (pos): {f1_pos:.4f} | FPR: {fpr:.4f}"
        )

    # Save metrics.json
    metrics_payload = {
        "manifest_version": "1.0.0",
        "status": "training_success",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "execution_mode": "train",
        "task": task,
        "target_names": target_names,
        "split_protocol": split_protocol_name,
        "seed": seed,
        "total_test_samples": len(y_test),
        "models": all_metrics,
    }
    metrics_path = output_dir / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)
    logger.info(f"Saved metrics to {metrics_path.name}")

    # Build experiment_manifest.json
    git_sha = os.environ.get("KAGGLE_GIT_SHA", "unknown")
    source_snapshot_sha256 = os.environ.get("KAGGLE_SOURCE_SNAPSHOT_SHA256", "unknown")
    selected_dataset_info = {
        "filename": data_path.name,
        "format": file_format,
        "size_bytes": data_path.stat().st_size,
        "sha256": compute_file_sha256(data_path),
        "total_rows_loaded": total_raw_rows,
        "features_used_count": len(feature_cols),
    }

    discovered_files = audit_data.get(
        "discovered_tabular_files", audit_data.get("discovered_csvs", [])
    )
    manifest_payload = {
        "manifest_version": "1.0.0",
        "status": "training_success",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": git_sha,
        "source_snapshot_sha256": source_snapshot_sha256,
        "config_source": config_source,
        "dataset_slug": dataset_slug,
        "dataset_version": str(dataset_version),
        "execution_mode": "train",
        "run_config": run_config or {},
        "random_seed": seed,
        "split_protocol": split_protocol_name,
        "task": task,
        "target_classes": target_names,
        "selected_file_format": file_format,
        "non_claim_scope": (
            "This experiment evaluates statistical/tabular baseline classifiers "
            "(Random Forest, Decision Tree, Gaussian Naive Bayes, Linear SVM) on summary "
            "flow features. It strictly does NOT represent a replication of the packet-clump "
            "time-series sequence LSTM model from MontazeriShatoori et al. (2020), which requires "
            "ordered packet sequences, direction, and inter-arrival timestamps from raw PCAPs."
        ),
        "input_files": [
            {
                "filename": r["filename"],
                "relative_path": r["relative_path"],
                "format": r.get("format", get_file_format(Path(r["filename"]))),
                "size_bytes": r["size_bytes"],
                "sha256": r["sha256"],
            }
            for r in discovered_files
        ],
        "total_tabular_files_found": len(discovered_files),
        "total_csv_files_found": len([r for r in discovered_files if r.get("format") == "csv"]),
        "total_parquet_files_found": len([r for r in discovered_files if r.get("format") == "parquet"]),
        "selected_dataset": selected_dataset_info,
        "data_split": {
            "train_samples": len(y_train),
            "test_samples": len(y_test),
            "train_class_distribution": train_dist,
            "test_class_distribution": test_dist,
        },
        "features": {
            "count": len(feature_cols),
            "feature_names": feature_cols,
            "stripped_identifier_columns": stripped_cols,
            "coercion": "float32",
        },
        "models_trained": list(all_metrics.keys()),
        "model_hyperparameters": model_params_record,
        "package_versions": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": SCIPY_VERSION,
            "scikit_learn": SKLEARN_VERSION,
            "pyarrow": PYARROW_VERSION,
        },
        "output_artifacts": [
            "schema_audit.json",
            "metrics.json",
            "experiment_manifest.json",
            *generated_cm_files,
        ],
    }

    manifest_path = output_dir / "experiment_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_payload, f, indent=2)
    logger.info(f"Saved experiment manifest to {manifest_path.name}")
    logger.info("Training pipeline finished successfully.")


ALLOWED_CONFIG_KEYS: Set[str] = {
    "$schema",
    "description",
    "mode",
    "data_file",
    "csv_file",
    "task",
    "label_column",
    "model",
    "seed",
    "max_samples_per_class",
    "dataset_slug",
    "dataset_version",
    "input_dir",
    "output_dir",
}

VALID_MODELS: Set[str] = {
    "all",
    "random_forest",
    "decision_tree",
    "gaussian_nb",
    "linear_svm",
}


def validate_raw_config(cfg: Dict[str, Any]) -> None:
    """Validate keys and types of the raw JSON configuration dict."""
    for key, val in cfg.items():
        if key not in ALLOWED_CONFIG_KEYS:
            raise ValueError(
                f"Unrecognized configuration key: '{key}'. Allowed keys are: {sorted(ALLOWED_CONFIG_KEYS)}"
            )

    if "mode" in cfg and cfg["mode"] is not None:
        if cfg["mode"] not in ("audit", "train"):
            raise ValueError(
                f"Invalid 'mode' in configuration: '{cfg['mode']}'. Must be 'audit' or 'train'."
            )

    if "task" in cfg and cfg["task"] is not None:
        if cfg["task"] not in ("l1", "l2"):
            raise ValueError(
                f"Invalid 'task' in configuration: '{cfg['task']}'. Must be 'l1', 'l2', or null."
            )

    if "data_file" in cfg and cfg["data_file"] is not None:
        if not isinstance(cfg["data_file"], str):
            raise ValueError(
                f"Invalid 'data_file' in configuration: must be string or null, got {type(cfg['data_file']).__name__}."
            )

    if "csv_file" in cfg and cfg["csv_file"] is not None:
        if not isinstance(cfg["csv_file"], str):
            raise ValueError(
                f"Invalid 'csv_file' in configuration: must be string or null, got {type(cfg['csv_file']).__name__}."
            )

    if "label_column" in cfg and cfg["label_column"] is not None:
        if not isinstance(cfg["label_column"], str):
            raise ValueError(
                f"Invalid 'label_column' in configuration: must be string or null, got {type(cfg['label_column']).__name__}."
            )

    if "model" in cfg and cfg["model"] is not None:
        if cfg["model"] not in VALID_MODELS:
            raise ValueError(
                f"Invalid 'model' in configuration: '{cfg['model']}'. Must be one of {sorted(VALID_MODELS)}."
            )

    if "seed" in cfg and cfg["seed"] is not None:
        if not isinstance(cfg["seed"], int) or isinstance(cfg["seed"], bool):
            raise ValueError(
                f"Invalid 'seed' in configuration: must be integer, got {cfg['seed']!r}."
            )

    if "max_samples_per_class" in cfg and cfg["max_samples_per_class"] is not None:
        if (
            not isinstance(cfg["max_samples_per_class"], int)
            or isinstance(cfg["max_samples_per_class"], bool)
            or cfg["max_samples_per_class"] <= 0
        ):
            raise ValueError(
                f"Invalid 'max_samples_per_class' in configuration: must be positive integer or null, got {cfg['max_samples_per_class']!r}."
            )

    if "dataset_slug" in cfg and cfg["dataset_slug"] is not None:
        if not isinstance(cfg["dataset_slug"], str) or not cfg["dataset_slug"].strip():
            raise ValueError("Invalid 'dataset_slug' in configuration: must be non-empty string.")

    if "dataset_version" in cfg and cfg["dataset_version"] is not None:
        if not isinstance(cfg["dataset_version"], (str, int)):
            raise ValueError(
                f"Invalid 'dataset_version' in configuration: must be string or integer, got {type(cfg['dataset_version']).__name__}."
            )

    if "input_dir" in cfg and cfg["input_dir"] is not None:
        if not isinstance(cfg["input_dir"], str):
            raise ValueError(
                f"Invalid 'input_dir' in configuration: must be string or null, got {type(cfg['input_dir']).__name__}."
            )

    if "output_dir" in cfg and cfg["output_dir"] is not None:
        if not isinstance(cfg["output_dir"], str):
            raise ValueError(
                f"Invalid 'output_dir' in configuration: must be string or null, got {type(cfg['output_dir']).__name__}."
            )


def validate_resolved_config(resolved: Dict[str, Any]) -> None:
    """Validate resolved configuration before execution."""
    mode = resolved.get("mode")
    if mode not in ("audit", "train"):
        raise ValueError(f"Invalid mode: '{mode}'. Must be 'audit' or 'train'.")

    model = resolved.get("model")
    if model not in VALID_MODELS:
        raise ValueError(f"Invalid model: '{model}'. Must be one of {sorted(VALID_MODELS)}.")

    seed = resolved.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"Invalid seed: '{seed}'. Must be integer.")

    max_samples = resolved.get("max_samples_per_class")
    if max_samples is not None:
        if not isinstance(max_samples, int) or isinstance(max_samples, bool) or max_samples <= 0:
            raise ValueError(
                f"Invalid max_samples_per_class: '{max_samples}'. Must be positive integer or None."
            )

    if mode == "train":
        data_file = resolved.get("data_file") or resolved.get("csv_file")
        if not data_file or not isinstance(data_file, str) or not data_file.strip():
            raise ValueError(
                "Configuration error: 'data_file' is required when mode is 'train'. "
                "Specify 'data_file' in run_config.json or via --data-file."
            )
        task = resolved.get("task")
        if not task or task not in ("l1", "l2"):
            raise ValueError(
                "Configuration error: 'task' ('l1' or 'l2') is required when mode is 'train'. "
                "Specify 'task' in run_config.json or via --task."
            )


def write_audit_artifacts(
    output_dir: Path,
    audit_data: Dict[str, Any],
    resolved_config: Dict[str, Any],
    config_source: str = "defaults",
) -> None:
    """Emit minimal manifest and metrics placeholder when running in audit-only mode."""
    git_sha = os.environ.get("KAGGLE_GIT_SHA", "unknown")
    source_snapshot_sha256 = os.environ.get("KAGGLE_SOURCE_SNAPSHOT_SHA256", "unknown")

    # 1. metrics.json with status not_trained (no fabricated metrics)
    metrics_payload = {
        "manifest_version": "1.0.0",
        "status": "not_trained",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "execution_mode": "audit",
        "config_source": config_source,
        "reason": "Audit mode completed successfully. Baseline models were not trained.",
        "models": {},
    }
    metrics_path = output_dir / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)
    logger.info(f"Saved audit metrics placeholder to {metrics_path.name}")

    # 2. minimal experiment_manifest.json with status audit_only and input hashes
    discovered_files = audit_data.get(
        "discovered_tabular_files", audit_data.get("discovered_csvs", [])
    )
    manifest_payload = {
        "manifest_version": "1.0.0",
        "status": "audit_only",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": git_sha,
        "source_snapshot_sha256": source_snapshot_sha256,
        "config_source": config_source,
        "dataset_slug": resolved_config.get("dataset_slug", "dhoogla/cicdohbrw2020"),
        "dataset_version": str(resolved_config.get("dataset_version", "3")),
        "execution_mode": "audit",
        "run_config": resolved_config,
        "non_claim_scope": (
            "This experiment evaluates statistical/tabular baseline classifiers "
            "(Random Forest, Decision Tree, Gaussian Naive Bayes, Linear SVM) on summary "
            "flow features. It strictly does NOT represent a replication of the packet-clump "
            "time-series sequence LSTM model from MontazeriShatoori et al. (2020), which requires "
            "ordered packet sequences, direction, and inter-arrival timestamps from raw PCAPs."
        ),
        "input_files": [
            {
                "filename": r["filename"],
                "relative_path": r["relative_path"],
                "format": r.get("format", get_file_format(Path(r["filename"]))),
                "size_bytes": r["size_bytes"],
                "sha256": r["sha256"],
            }
            for r in discovered_files
        ],
        "total_tabular_files_found": len(discovered_files),
        "total_csv_files_found": len([r for r in discovered_files if r.get("format") == "csv"]),
        "total_parquet_files_found": len([r for r in discovered_files if r.get("format") == "parquet"]),
        "package_versions": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": SCIPY_VERSION,
            "scikit_learn": SKLEARN_VERSION,
            "pyarrow": PYARROW_VERSION,
        },
        "output_artifacts": [
            "schema_audit.json",
            "experiment_manifest.json",
            "metrics.json",
        ],
    }
    manifest_path = output_dir / "experiment_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_payload, f, indent=2)
    logger.info(f"Saved audit experiment manifest to {manifest_path.name}")


def resolve_run_configuration(
    cli_args: argparse.Namespace,
) -> Tuple[Dict[str, Any], Optional[Path], str]:
    """Resolve and validate execution configuration from embedded constant, file, and CLI arguments.

    Returns:
        (resolved_config_dict, config_file_path, config_source)
        where config_source is 'embedded', 'file', or 'defaults'.
    """
    config_source: str = "defaults"
    config_path: Optional[Path] = None
    raw_config: Dict[str, Any] = {}

    # 1. Check explicit script constant EMBEDDED_CONFIG_JSON before filesystem config
    if EMBEDDED_CONFIG_JSON is not None:
        if isinstance(EMBEDDED_CONFIG_JSON, dict):
            raw_config = EMBEDDED_CONFIG_JSON
            config_source = "embedded"
            logger.info("Discovered and resolved embedded configuration object (EMBEDDED_CONFIG_JSON).")
        elif isinstance(EMBEDDED_CONFIG_JSON, str):
            trimmed = EMBEDDED_CONFIG_JSON.strip()
            if trimmed:
                try:
                    parsed = json.loads(trimmed)
                except Exception as exc:
                    raise ValueError(
                        f"Failed to parse embedded EMBEDDED_CONFIG_JSON as JSON: {exc}"
                    ) from exc
                if not isinstance(parsed, dict):
                    raise ValueError(
                        f"Embedded configuration must be a JSON object, got {type(parsed).__name__}"
                    )
                raw_config = parsed
                config_source = "embedded"
                logger.info("Discovered and resolved embedded configuration JSON string (EMBEDDED_CONFIG_JSON).")
        else:
            raise ValueError(
                f"Invalid EMBEDDED_CONFIG_JSON type: {type(EMBEDDED_CONFIG_JSON).__name__}. Expected str or dict."
            )

    # 2. If no embedded config, look for filesystem config
    if config_source == "defaults":
        if cli_args.config is not None:
            config_path = cli_args.config.resolve()
            if not config_path.is_file():
                raise FileNotFoundError(
                    f"Specified configuration file does not exist: {config_path}"
                )
        else:
            script_dir = Path(__file__).resolve().parent
            candidate_1 = script_dir / "run_config.json"
            candidate_2 = Path.cwd() / "run_config.json"
            if candidate_1.is_file():
                config_path = candidate_1
            elif candidate_2.is_file():
                config_path = candidate_2

        if config_path is not None:
            logger.info(f"Discovered configuration file at: {config_path}")
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            if not isinstance(file_config, dict):
                raise ValueError(
                    f"Configuration file {config_path} must be a JSON object, got {type(file_config).__name__}"
                )
            raw_config = file_config
            config_source = "file"

    if raw_config:
        validate_raw_config(raw_config)

    # Base defaults (audit-only by default)
    resolved: Dict[str, Any] = {
        "mode": "audit",
        "input_dir": "/kaggle/input",
        "output_dir": "/kaggle/working",
        "data_file": None,
        "csv_file": None,
        "task": None,
        "label_column": None,
        "model": "all",
        "seed": 42,
        "max_samples_per_class": None,
        "dataset_slug": "dhoogla/cicdohbrw2020",
        "dataset_version": "3",
    }

    # Apply raw_config to base defaults
    for key in resolved.keys():
        if key in raw_config and raw_config[key] is not None:
            resolved[key] = raw_config[key]

    # Handle data_file and compatibility alias csv_file
    if "data_file" in raw_config and raw_config["data_file"] is not None:
        resolved["data_file"] = raw_config["data_file"]
        resolved["csv_file"] = raw_config["data_file"]
    elif "csv_file" in raw_config and raw_config["csv_file"] is not None:
        resolved["data_file"] = raw_config["csv_file"]
        resolved["csv_file"] = raw_config["csv_file"]

    for key in ("data_file", "csv_file", "task", "label_column", "max_samples_per_class"):
        if key in raw_config and raw_config[key] is None:
            resolved[key] = None
            if key == "data_file":
                resolved["csv_file"] = None
            elif key == "csv_file":
                resolved["data_file"] = None

    # Apply CLI overrides (CLI flags override config values)
    if cli_args.input_dir is not None:
        resolved["input_dir"] = str(cli_args.input_dir)
    if cli_args.output_dir is not None:
        resolved["output_dir"] = str(cli_args.output_dir)
    if cli_args.data_file is not None:
        resolved["data_file"] = cli_args.data_file.strip() if cli_args.data_file else None
        resolved["csv_file"] = resolved["data_file"]
    elif cli_args.csv_file is not None:
        logger.warning("CLI argument '--csv-file' is deprecated; use '--data-file' instead.")
        resolved["data_file"] = cli_args.csv_file.strip() if cli_args.csv_file else None
        resolved["csv_file"] = resolved["data_file"]
    if cli_args.task is not None:
        resolved["task"] = cli_args.task.strip().lower() if cli_args.task else None
    if cli_args.label_column is not None:
        resolved["label_column"] = cli_args.label_column.strip() if cli_args.label_column else None
    if cli_args.model is not None:
        resolved["model"] = cli_args.model
    if cli_args.seed is not None:
        resolved["seed"] = cli_args.seed
    if cli_args.max_samples_per_class is not None:
        resolved["max_samples_per_class"] = cli_args.max_samples_per_class
    if cli_args.dataset_slug is not None:
        resolved["dataset_slug"] = cli_args.dataset_slug
    if cli_args.dataset_version is not None:
        resolved["dataset_version"] = str(cli_args.dataset_version)

    # Mode determination:
    if cli_args.audit_only:
        resolved["mode"] = "audit"
    elif cli_args.mode is not None:
        resolved["mode"] = cli_args.mode
    elif cli_args.data_file is not None or cli_args.csv_file is not None:
        resolved["mode"] = "train"

    validate_resolved_config(resolved)

    return resolved, config_path, config_source


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Run tabular baseline audit and training for CICDoHBrw2020 on Kaggle CPU."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to JSON run configuration file (default: auto-discover run_config.json).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["audit", "train"],
        default=None,
        help="Execution mode: 'audit' (schema discovery only) or 'train' (execute baseline training).",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Input directory containing Kaggle datasets (default: /kaggle/input).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for manifests and small artifacts (default: /kaggle/working).",
    )
    parser.add_argument(
        "--data-file",
        type=str,
        default=None,
        help="Filename or path of the tabular data file (CSV or Parquet) to use for training. Overrides configuration file.",
    )
    parser.add_argument(
        "--csv-file",
        type=str,
        default=None,
        help="Deprecated compatibility alias for --data-file.",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        default=False,
        help="If set, forces audit mode and exits successfully after audit.",
    )
    parser.add_argument(
        "--task",
        type=str,
        choices=["l1", "l2"],
        default=None,
        help="Target classification task: 'l1' (DoH vs Non-DoH) or 'l2' (Benign DoH vs Malicious DoH).",
    )
    parser.add_argument(
        "--label-column",
        type=str,
        default=None,
        help="Name of the label column. Required if dataset contains ambiguous or non-standard label column.",
    )
    parser.add_argument(
        "--model",
        type=str,
        choices=["all", "random_forest", "decision_tree", "gaussian_nb", "linear_svm"],
        default=None,
        help="Model baseline to train and evaluate (default: all).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for data split and classifiers (default: 42).",
    )
    parser.add_argument(
        "--max-samples-per-class",
        type=int,
        default=None,
        help="Optional maximum number of samples per class (for quick runs or memory management).",
    )
    parser.add_argument(
        "--dataset-slug",
        type=str,
        default=None,
        help="Kaggle dataset slug (default: dhoogla/cicdohbrw2020).",
    )
    parser.add_argument(
        "--dataset-version",
        type=str,
        default=None,
        help="Dataset version tag or number (default: 3).",
    )
    return parser.parse_args()


def main() -> int:
    """Main entrypoint."""
    args = parse_args()

    try:
        config, config_path, config_source = resolve_run_configuration(args)
    except Exception as exc:
        logger.error(f"Configuration resolution failed: {exc}")
        return 1

    input_dir: Path = Path(config["input_dir"]).resolve()
    output_dir: Path = Path(config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    mode = config["mode"]
    logger.info("=== Kaggle Statistical Baseline Runner ===")
    logger.info(f"Execution Mode:   {mode}")
    logger.info(f"Input Directory:  {input_dir}")
    logger.info(f"Output Directory: {output_dir}")
    logger.info(f"Config Source:    {config_source}")
    if config_source == "embedded":
        logger.info("Loaded Config:    Embedded constant (EMBEDDED_CONFIG_JSON)")
    elif config_source == "file" and config_path:
        logger.info(f"Loaded Config:    {config_path}")
    else:
        logger.info("Loaded Config:    None (using defaults/CLI overrides)")

    # Step 1: Discover and audit tabular files (always runs first to retain audit-first behavior)
    audit_data, discovered_files = discover_and_audit_tabular_files(
        input_dir, output_dir, config_source=config_source
    )

    # If audit mode, write minimal audit artifacts and exit 0
    if mode == "audit":
        write_audit_artifacts(output_dir, audit_data, config, config_source=config_source)
        logger.info("[AUDIT] Schema audit and audit artifacts completed successfully.")
        logger.info(
            "[AUDIT] To transition to baseline training, update run_config.json to 'mode': 'train' "
            "with selected 'data_file' and 'task', or execute via CLI flags."
        )
        if discovered_files:
            logger.info("[AUDIT] Discovered tabular files available for training:")
            for p in discovered_files:
                logger.info(f"  - {p.name} ({get_file_format(p)})")
        else:
            logger.warning("[AUDIT] No tabular files (CSV or Parquet) found under input directory.")
        return 0

    # Step 2: Training mode
    data_file = config.get("data_file") or config.get("csv_file")
    if not data_file:
        logger.error("Configuration error: 'data_file' is required in 'train' mode.")
        return 1

    task = config.get("task")
    if not task or task not in ("l1", "l2"):
        logger.error(
            f"Configuration error: 'task' must be 'l1' or 'l2' in 'train' mode (got '{task}')."
        )
        return 1

    # Locate selected tabular file
    selected_data_file = resolve_selected_data_file(data_file, input_dir, discovered_files)
    if selected_data_file is None:
        logger.error(
            f"Selected data file '{data_file}' was not found under input directory '{input_dir}'."
        )
        return 1

    # Check label column
    sample_df, selected_fmt = load_tabular_data(selected_data_file, nrows=10)
    clean_cols = [str(c).strip() for c in sample_df.columns]
    resolved_label_col, label_err = resolve_label_column(clean_cols, config.get("label_column"))
    if resolved_label_col is None:
        logger.error(
            f"Failed to resolve label column in selected data file '{selected_data_file.name}': {label_err}"
        )
        return 1

    logger.info(f"Using label column: '{resolved_label_col}' for task: '{task}' (format: {selected_fmt})")

    model_arg = config.get("model", "all")
    models_to_run = (
        ["random_forest", "decision_tree", "gaussian_nb", "linear_svm"]
        if model_arg == "all"
        else [model_arg]
    )

    try:
        run_training_pipeline(
            data_path=selected_data_file,
            task=task,
            label_col=resolved_label_col,
            models_to_run=models_to_run,
            seed=config.get("seed", 42),
            max_samples_per_class=config.get("max_samples_per_class"),
            output_dir=output_dir,
            dataset_slug=config.get("dataset_slug", "dhoogla/cicdohbrw2020"),
            dataset_version=str(config.get("dataset_version", "3")),
            audit_data=audit_data,
            run_config=config,
            config_source=config_source,
        )
    except Exception as exc:
        logger.error(f"Training pipeline halted: {exc}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
