# CICDoHBrw-2020 Tabular Statistical Baseline (Kaggle CPU Runner)

This directory contains the Kaggle Script kernel runner for reproducing and evaluating classical tabular machine learning baselines on the `dhoogla/cicdohbrw2020` dataset (version 3).

---

## 1. Scope & Strict Non-Claim Boundary

* **Evaluated Scope (Statistical Baseline Only):**
  This runner trains and evaluates classical tabular classifiers (**Random Forest**, **Decision Tree**, **Gaussian Naive Bayes**, and **Linear SVM**) on flow-level statistical summary features. This provides a baseline comparison against Tables III and IV of the paper:
  > MontazeriShatoori et al. (2020), *Detection of DoH Tunnels using Time-series Classification of Encrypted Traffic*, IEEE DASC/PiCom/CBDCom/CyberSciTech 2020.
* **Strict Non-Claim Scope:**
  **This experiment strictly does NOT represent a replication of the packet-clump time-series sequence model (LSTM)** from Section VI and Tables V–VI of the paper.
  Packet-clump sequence classification requires raw PCAP packet traces with deterministic arrival order, packet directions, and sub-millisecond inter-arrival timestamps extracted via the DoHLyzer clumping algorithm ($\tau_{\text{timeout}} = 1\text{ ms}$). Static tabular summary files (CSV/Parquet) cannot substitute for packet-clump sequences.

---

## 2. Security, Privacy & Provenance Boundaries

1. **Git Repository as Source of Truth:**
   All configuration and execution logic reside in Git. Kaggle acts strictly as an ephemeral, private runner executing immutable code snapshots and producing small audit/manifest artifacts.
2. **Private Kernel Execution:**
   The kernel metadata specifies `"is_private": true`, `"enable_internet": false`, `"enable_gpu": false`, and `"enable_tpu": false`.
3. **Zero Credential & Secret Leakage:**
   * Never commit Kaggle usernames, API tokens, `kaggle.json`, or personal host filesystem paths into tracked files or stdout.
   * `kernel-metadata.json` uses a placeholder kernel ID (`INSERT_KAGGLE_USERNAME/cicdohbrw2020-statistical-baseline`). The push workflow injects `KAGGLE_KERNEL_ID` at runtime.
4. **No Heavy or Binary Artifacts:**
   * Do not commit raw tabular files (CSV/Parquet), PCAPs, or binary model weights (`.pkl`, `.pt`, `.h5`, `.joblib`) to Git or Kaggle output.
   * Only lightweight structured JSON and CSV artifacts (`schema_audit.json`, `metrics.json`, `experiment_manifest.json`, confusion matrices) are returned.
5. **Defensive Boundary:**
   This runner performs passive classification only. Never operate live DNS tunnels (`iodine`, `dns2tcp`, `dnscat2`) or replay network traffic.

---

## 3. Two-Stage Execution Protocol & Tracked Configuration

Because Kaggle launches Script kernels without command-line arguments and uploads only the declared code file (`train_statistical.py`), a separate `run_config.json` is not automatically present inside the Kaggle execution container. To ensure reproducible, reviewed execution, the push wrapper (`push_statistical_baseline.sh`) reads and validates the local tracked `run_config.json` and embeds it directly into the uploaded script. The runner resolves the embedded configuration first (falling back to filesystem config or defaults), emits the exact resolved config in manifests, and records the config source (`embedded`, `file`, or `defaults`).

Furthermore, the remote Kaggle dataset `dhoogla/cicdohbrw2020` (version 3) contains exactly two Parquet tabular inputs:
1. `L1-DoH-NonDoH.parquet` (107,043,097 bytes)
2. `L2-BenignDoH-MaliciousDoH.parquet` (34,164,502 bytes)

The runner discovers and audits tabular inputs in both CSV and Parquet formats. The initial Parquet audit successfully established these files, their column schemas, and confirmed the target `Label` column. However, its candidate label preview sampled only the first rows, which reported only `DoH` for L1 and `Benign` for L2. This first-row sample is strictly insufficient to choose or verify a training label mapping. Parquet records are often ordered or grouped by traffic class; under no circumstances should the sampled `DoH` or `Benign` values be treated as the complete class distribution. The next remote audit computes exact full-label counts from the label column alone before any train configuration is approved. `run_config.json` strictly remains in audit mode (`"mode": "audit"`) until those full counts are reviewed.
```
                           +------------------------+
                           |   run_config.json      |
                           +------------------------+
                                       |
                                       v
                           +------------------------+
                           | Input Tabular Discovery |
                           |   (CSV / Parquet)      |
                           +------------------------+
                                       |
                                       v
                           +------------------------+
                           |   schema_audit.json    |  <-- Always emitted first
                           +------------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
           mode: "audit"                           mode: "train"
        (Default run_config)                    (Configured & Verified)
                   |                                       |
                   v                                       v
         +-------------------+                   +-------------------+
         | Exit 0 with:      |                   | Train Baselines   |
         | - manifest.json   |                   | (RF, DT, NB, SVM) |
         |   (audit_only)    |                   +-------------------+
         | - metrics.json    |                             |
         |   (not_trained)   |                             v
         +-------------------+                   +-------------------+
                                                 | Exit 0 with:      |
                                                 | - manifest.json   |
                                                 |   (training_ok)   |
                                                 | - metrics.json    |
                                                 |   (training_ok)   |
                                                 | - CM CSVs         |
                                                 +-------------------+
```

### Tracked Configuration (`run_config.json`)

The runner automatically discovers and reads `run_config.json` located next to `train_statistical.py` (or the current working directory). The repository ships with `run_config.json` defaulted to audit mode:

```json
{
  "mode": "audit",
  "data_file": null,
  "task": null,
  "label_column": null,
  "model": "all",
  "seed": 42,
  "max_samples_per_class": null,
  "dataset_slug": "dhoogla/cicdohbrw2020",
  "dataset_version": "3",
  "description": "Reviewed execution configuration for Kaggle CPU runner. Default mode is audit; remains in audit mode until full-label counts from schema audit are reviewed and approved."
}
```

> **Audit Mode Policy:** `run_config.json` strictly remains in audit mode (`"mode": "audit"`) until the full-column label counts from the next audit are reviewed and approved. Transition to train mode is blocked until full-file class counts verify both classes for the selected task.

#### Supported Configuration Keys

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `mode` | String | `"audit"` | Execution mode: `"audit"` (schema discovery only) or `"train"` (train baselines). |
| `data_file` | String \| null | `null` | Filename of the target tabular data file (`.parquet` or `.csv`). **Required when `mode` is `"train"`**. (`csv_file` is accepted as a deprecated compatibility alias). |
| `task` | String \| null | `null` | Classification task: `"l1"` (DoH vs Non-DoH) or `"l2"` (Benign vs Malicious). **Required when `mode` is `"train"`**. |
| `label_column` | String \| null | `null` | Target label column name. If `null`, auto-resolved if an unambiguous column exists. |
| `model` | String | `"all"` | Model to train: `"all"`, `"random_forest"`, `"decision_tree"`, `"gaussian_nb"`, `"linear_svm"`. |
| `seed` | Int | `42` | Random seed for data split and classifiers. |
| `max_samples_per_class` | Int \| null | `null` | Optional sample cap per class for quick testing or memory management. |
| `dataset_slug` | String | `"dhoogla/cicdohbrw2020"` | Kaggle dataset identifier recorded in manifests. |
| `dataset_version` | String \| Int | `"3"` | Dataset version tag recorded in manifests. |
| `input_dir` | String \| null | `null` | Optional input directory override (defaults to `/kaggle/input`). |
| `output_dir` | String \| null | `null` | Optional output directory override (defaults to `/kaggle/working`). |
| `description` | String \| null | `null` | Human-readable description/note for the experiment run. |

*Strict Validation:* The script validates all configuration keys and types. Any unrecognized key or invalid type causes immediate refusal.

---

### Stage 1: Discovery & Schema Audit (Default)

When executed with `mode: "audit"` (the default in `run_config.json`):
1. Recursively discovers all tabular data files (`.parquet` and `.csv`) under `--input-dir` (default: `/kaggle/input`).
2. Computes file sizes and SHA-256 checksums via streaming chunks (no memory exhaustion).
3. Inspects columns, dtypes, and row counts, and performs a complete-column audit for candidate label columns by reading only the label column (using column projection for Parquet and safe chunking for CSV, avoiding memory exhaustion from loading numeric features). The audit calculates exact full-file class frequencies (`value_counts`), `null_count`, total/unique counts, and sets `complete_column_audit: true` (`is_complete_audit: true`), retaining bounded previews (`sample_unique_values`) strictly as supplementary metadata. First-row samples are insufficient to determine label mappings; the runner refuses to present partial samples as complete distributions.
4. Writes `schema_audit.json` with status `"audit_complete"`.
5. Writes minimal `experiment_manifest.json` with status `"audit_only"`, recording input file checksums, package versions, and scope boundary.
6. Writes `metrics.json` with status `"not_trained"` (cleanly indicating models were not trained; never fabricates dummy metrics).
7. Exits successfully (`exit code 0`).

---

### Exact Config Transition After Schema Audit

**Status of Remote Audits & Sample Insufficiency:**
The initial Parquet audit established the presence of two v3 Parquet tables (`L1-DoH-NonDoH.parquet` and `L2-BenignDoH-MaliciousDoH.parquet`), their column schemas, and the target `Label` column. However, because its first-rows sample observed only `DoH` for L1 and `Benign` for L2, it is strictly insufficient to approve a training configuration.
* **Prohibition:** No documentation or workflow may treat these sampled `DoH` or `Benign` values as the complete class distribution.
* **Audit Requirement:** The next remote audit computes exact full-label counts across the entire column from the label column alone before any train configuration is approved.
* **Config Gate:** `run_config.json` remains in audit mode (`"mode": "audit"`) until those full-file counts are reviewed and approved.

Only after the full-label audit confirms both classes for the respective task:
1. **Inspect Full Label Counts in `schema_audit.json`:**
   * Confirm `complete_column_audit: true` (or `is_complete_audit: true`) for `candidate_label_columns["Label"]`.
   * Review exact full-file class frequencies in `value_counts` (verifying that both DoH and Non-DoH flows exist in `L1-DoH-NonDoH.parquet`, and both Benign DoH and Malicious Tunnel flows exist in `L2-BenignDoH-MaliciousDoH.parquet`).
   * Confirm that all observed label strings match the documented accepted strings dictionary in Section 4.
2. **Update `run_config.json` in Git:**
   Switch `mode` to `"train"`, provide the audited `data_file`, and specify the desired `task`:

   *For Layer 1 Baseline (DoH vs Non-DoH):*
   ```json
   {
     "mode": "train",
     "data_file": "L1-DoH-NonDoH.parquet",
     "task": "l1",
     "label_column": "Label",
     "model": "all",
     "seed": 42,
     "max_samples_per_class": null,
     "dataset_slug": "dhoogla/cicdohbrw2020",
     "dataset_version": "3",
     "description": "Audited Layer 1 tabular baseline training on L1-DoH-NonDoH.parquet."
   }
   ```

   *For Layer 2 Baseline (Benign DoH vs Malicious DoH):*
   ```json
   {
     "mode": "train",
     "data_file": "L2-BenignDoH-MaliciousDoH.parquet",
     "task": "l2",
     "label_column": "Label",
     "model": "all",
     "seed": 42,
     "max_samples_per_class": null,
     "dataset_slug": "dhoogla/cicdohbrw2020",
     "dataset_version": "3",
     "description": "Audited Layer 2 tabular baseline training on L2-BenignDoH-MaliciousDoH.parquet."
   }
   ```
3. **Commit `run_config.json`:**
   Commit the updated config to Git so the run configuration is tracked and auditable.
4. **Push Kernel:**
   The push wrapper (`push_statistical_baseline.sh`) validates and injects `run_config.json` into the script kernel, which executes on Kaggle, consumes the reviewed embedded configuration, and proceeds directly to Stage 2 training.

---

### Stage 2: Supervised Baseline Training

Training proceeds **only** when:
1. `mode` is set to `"train"`.
2. Required fields `data_file` (or legacy `csv_file`) and `task` are present and valid. If missing, the runner refuses to train and halts with an error.
3. Schema audit always runs first to ensure input hashes are fresh in `schema_audit.json`.
4. The selected tabular file (`data_file`) is confirmed to exist in the input directory.
5. An unambiguous label column is confirmed.
6. All labels in the dataset match the documented accepted strings dictionary. **Any unknown label halts execution immediately with an error.**
7. Baseline classifiers are trained, evaluated, and full artifacts (`metrics.json`, `experiment_manifest.json`, confusion matrices) are emitted with status `"training_success"`.
---

## 4. Documented Accepted Source Labels & Validation
> **CRITICAL SAMPLING NOTICE:**  
> The initial row sample of `L1-DoH-NonDoH.parquet` observed only `DoH`, and `L2-BenignDoH-MaliciousDoH.parquet` observed only `Benign`. These samples **MUST NOT** be mistaken for the complete class distribution. Tabular Parquet files are frequently sorted or grouped by traffic type. Training cannot be configured or approved based on row samples; full-column value counts must be verified via the complete-column schema audit first.


The runner coerces source strings case-insensitively and strips whitespace. Only the following documented labels are accepted:

### Task L1: DoH Traffic Classification (`--task l1`)
* **Objective:** Distinguish between encrypted DoH traffic and regular HTTPS web traffic (Paper Table III).
* **Canonical Classes:**
  * `0`: `non_doh`
  * `1`: `doh`
* **Accepted Source Strings:**
  * **Non-DoH:** `"non-doh"`, `"nondoh"`, `"non_doh"`, `"non doh"`, `"non-doh-browsing"`, `"nondoh-browsing"`
  * **DoH:** `"doh"`, `"doh-browsing"`, `"doh-tunnel"`, `"benign-doh"`, `"benigndoh"`, `"benign_doh"`, `"benign doh"`, `"malicious-doh"`, `"maliciousdoh"`, `"malicious_doh"`, `"malicious doh"`, `"benign"`, `"malicious"`, `"chrome"`, `"firefox"`, `"dns2tcp"`, `"dnscat2"`, `"iodine"`

### Task L2: Malicious DoH Tunnel Characterization (`--task l2`)
* **Objective:** Distinguish between benign DoH browsing and malicious DNS tunnels encapsulated in DoH (Paper Table IV).
* **Canonical Classes:**
  * `0`: `benign_doh`
  * `1`: `malicious_doh`
* **Accepted Source Strings:**
  * **Benign DoH:** `"benign"`, `"benign-doh"`, `"benigndoh"`, `"benign_doh"`, `"benign doh"`, `"browsing"`, `"chrome"`, `"firefox"`, `"doh-browsing"`
  * **Malicious DoH:** `"malicious"`, `"malicious-doh"`, `"maliciousdoh"`, `"malicious_doh"`, `"malicious doh"`, `"tunneling"`, `"tunnel"`, `"doh-tunnel"`, `"dns2tcp"`, `"dnscat2"`, `"iodine"`
* **Non-DoH Filtering:** If Non-DoH rows are present in an L2 input file, they are filtered out with explicit logging because Layer 2 by definition operates strictly on DoH traffic.

**Refusal Policy:** If any label is unrecognized or cannot be unambiguously mapped, the script raises `ValueError` and refuses to train. It will never guess label semantics.

---

## 5. Machine Learning & Preprocessing Specifications

1. **Split Protocol (`paper_flow_random_80_20`):**
   * Stratified 80% train / 20% test random flow-level split (`test_size=0.20`, `stratify=y`, `random_state=seed`).
   * Group/session split is deferred until audit confirms the existence of capture session or timestamp provenance columns.
2. **Identifier Stripping (Prevent Data Leakage):**
   * Strips all host identifiers: `Flow ID`, `Source IP`, `Destination IP`, `Source Port`, `Destination Port`, `Protocol`, `Timestamp`, and MAC addresses.
3. **Train-Only Preprocessing:**
   * Median imputer: `SimpleImputer(strategy='median')` fit on Train fold only.
   * Standard scaler: `StandardScaler` fit on Train fold only (used for `linear_svm`).
4. **Feature Coercion:**
   * Feature values coerced to numeric `float32`.
   * Rows with `NaN` or infinite values are dropped with logged counts (following paper: $n < 50$ NaN flows dropped).
5. **Supported Models:**
   * `random_forest`: `RandomForestClassifier(n_estimators=100, criterion='gini', min_samples_split=2, random_state=seed, n_jobs=-1)`
   * `decision_tree`: `DecisionTreeClassifier(criterion='entropy', splitter='best', min_samples_split=2, random_state=seed)`
   * `gaussian_nb`: `GaussianNB(var_smoothing=1e-9)`
   * `linear_svm`: `LinearSVC(C=1.0, max_iter=2000, random_state=seed, dual=False)`
   * **Explicit Prohibitions:** No RBF SVM (prohibitive $O(N^2)$ to $O(N^3)$ complexity causes CPU hangs on large datasets), No LSTM, No model weight checkpoints.

---

## 6. CLI Arguments Reference

CLI flags override values in `run_config.json` for local experimentation:

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--config` | Path | `None` | Path to JSON run config file (default: auto-discover `run_config.json`). |
| `--mode` | String | `None` | Execution mode: `audit` or `train` (overrides `run_config.json`). |
| `--input-dir` | Path | `None` | Input directory containing mounted datasets (default: `/kaggle/input`). |
| `--output-dir` | Path | `None` | Output directory for manifests and metrics (default: `/kaggle/working`). |
| `--data-file` | String \| null | `None` | Filename or path of tabular file (`.parquet` or `.csv`) to train on. Overrides `run_config.json`. (`--csv-file` is accepted as a deprecated alias). |
| `--audit-only` | Flag | `False` | Forces audit mode and exits successfully after audit. |
| `--task` | String | `None` | Classification task: `l1` (DoH vs Non-DoH) or `l2` (Benign vs Malicious). |
| `--label-column` | String | `None` | Target column name. Required if column name is non-standard. |
| `--model` | String | `None` | Model to train: `all`, `random_forest`, `decision_tree`, `gaussian_nb`, `linear_svm`. |
| `--seed` | Int | `None` | Random seed for data split and classifiers. |
| `--max-samples-per-class` | Int | `None` | Optional cap per class for quick testing or memory management. |
| `--dataset-slug` | String | `None` | Kaggle dataset identifier. |
| `--dataset-version` | String | `None` | Dataset version tag. |
---

## 7. Emitted Artifacts

Every completed run produces small, auditable artifacts in `--output-dir`, cleanly distinguishing audit success from training success:

1. `schema_audit.json`:
   Emitted in both audit and train modes (`status: "audit_complete"`). Full inventory of discovered tabular files (Parquet / CSV): relative paths, byte sizes, streaming SHA-256 hashes, row counts, column counts, data types, and candidate label column audit (`candidate_label_columns`). For each candidate label column, provides complete-column verification (`complete_column_audit: true`, `is_complete_audit: true`), exact full value frequencies across the entire column (`value_counts`), `null_count`, total and unique counts, alongside supplementary bounded sample previews (`sample_unique_values`).
2. `metrics.json`:
   * **In Audit Mode:** Emitted with `status: "not_trained"`, empty models dictionary, and timestamp. Never fabricates dummy evaluation scores.
   * **In Training Mode:** Emitted with `status: "training_success"`. Full evaluation metrics per model on the test split: Accuracy, Macro/Weighted Precision/Recall/F1, Positive class Precision/Recall/F1, False Positive Rate (FPR), ROC-AUC, PR-AUC, confusion matrix entries (`tn`, `fp`, `fn`, `tp`), fit time, and per-sample inference latency.
3. `experiment_manifest.json`:
   * **In Audit Mode:** Emitted with `status: "audit_only"`. Contains input file streaming SHA-256 hashes, Git SHA, source snapshot hash, package versions, execution configuration, and strict non-claim scope statement.
   * **In Training Mode:** Emitted with `status: "training_success"`. Full provenance metadata: Git commit SHA, source snapshot hash, dataset slug, dataset version, random seed, split protocol (`paper_flow_random_80_20`), train/test sample counts, class distributions, feature names, stripped identifier columns, hyperparameter records, package versions, and strict non-claim scope statement.
4. `confusion_matrix_<model>.csv` (Training mode only):
   Formatted confusion matrix table with canonical class names for each trained baseline model.

---

## 8. Exact Execution Commands

### Local Verification / Pre-flight Run
```bash
# 1. Run audit mode using tracked run_config.json (default mode: "audit")
python3 doh_tunnel_detection/experiments/kaggle/statistical_baseline/train_statistical.py \
    --input-dir /path/to/local/input \
    --output-dir /path/to/local/artifacts

# 2. Alternatively, force audit-only via CLI flag
python3 doh_tunnel_detection/experiments/kaggle/statistical_baseline/train_statistical.py \
    --input-dir /path/to/local/input \
    --output-dir /path/to/local/artifacts \
    --audit-only

# 3. Train Layer 1 baseline (DoH vs Non-DoH) with CLI overrides
python3 doh_tunnel_detection/experiments/kaggle/statistical_baseline/train_statistical.py \
    --input-dir /path/to/local/input \
    --output-dir /path/to/local/artifacts \
    --data-file L1-DoH-NonDoH.parquet \
    --task l1 \
    --label-column Label \
    --model all \
    --seed 42

# 4. Train Layer 2 baseline (Benign DoH vs Malicious DoH) with sample cap
python3 doh_tunnel_detection/experiments/kaggle/statistical_baseline/train_statistical.py \
    --input-dir /path/to/local/input \
    --output-dir /path/to/local/artifacts \
    --data-file L2-BenignDoH-MaliciousDoH.parquet \
    --task l2 \
    --label-column Label \
    --max-samples-per-class 50000 \
    --model random_forest \
    --seed 42
```
### Kaggle CLI Push & Run Workflow
To keep usernames and personal tokens out of source control, export your Kaggle kernel identifier as an environment variable before pushing:

```bash
# Set environment variables in your terminal session
export KAGGLE_KERNEL_ID="<your-kaggle-username>/cicdohbrw2020-statistical-baseline"
export KAGGLE_GIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

# Prepare push directory with substituted kernel ID
TMP_PUSH_DIR="$(mktemp -d)"
cp -r doh_tunnel_detection/experiments/kaggle/statistical_baseline/* "$TMP_PUSH_DIR/"
sed -i "s|INSERT_KAGGLE_USERNAME/cicdohbrw2020-statistical-baseline|${KAGGLE_KERNEL_ID}|" "$TMP_PUSH_DIR/kernel-metadata.json"

# Push private script kernel to Kaggle
kaggle kernels push -p "$TMP_PUSH_DIR"
rm -rf "$TMP_PUSH_DIR"

# Monitor kernel execution status
kaggle kernels status "$KAGGLE_KERNEL_ID"

# Once completed, retrieve output artifacts only (small JSON/CSV files)
kaggle kernels output "$KAGGLE_KERNEL_ID" -p artifacts/kaggle/statistical_baseline/
```
