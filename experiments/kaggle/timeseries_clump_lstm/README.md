# CIRA-CIC-DoHBrw-2020 Raw-PCAP Time-Series Packet-Clump Runner (Kaggle)

This directory contains the Kaggle Script kernel runner for reproducing and evaluating the packet-clump sequence classification models (Paper v4 LSTM and Improved Masked BiGRU) on the raw PCAP captures of the `CIRA-CIC-DoHBrw-2020` dataset.

---

## 1. Scientific Scope & Claim Boundaries

This runner enforces a strict, explicit distinction across three scientific paradigms:

1. **Paper-Text Reconstruction:**
   * Reconstructs the methodology described in:
     > MontazeriShatoori et al. (2020), *Detection of DoH Tunnels using Time-series Classification of Encrypted Traffic*, IEEE CyberSciTech 2020.
   * Uses 1 ms packet clumping ($\tau = 0.001\text{ s}$), sliding windows of clumps ($l = 6$ for Layer 1, $l = 3$ for Layer 2), and flow-random 80/20 splitting.
   * **Leakage Caveat:** Flow-random 80/20 splitting distributes flows from the same capture session across both train and test partitions. Any metrics reported under this protocol are explicitly flagged with a prominent data-leakage caveat.
2. **DoHLyzer Reference-Code Facts:**
   * Grounded in the author's reference implementation (`v4.py` and `analyzer/dataset.py`).
   * Architecture: `Dense(10, ReLU)` per step $\to$ `LSTM(8*l, ReLU semantics)` $\to$ `Dense(6*l, ReLU)` $\to$ `Dropout(0.2)` $\to$ `Dense(2*l, ReLU)` $\to$ `Dense(1, Sigmoid)`.
   * Reference feature order: `[interarrival, duration, size, packet_count, direction]`.
   * Normalization: logarithmic min-max scaling for time, duration, size, and packet count; direction in $\{+1, -1\}$; padding vector `[-1.0, -1.0, -1.0, -1.0, 0.0]`.
   * Note: The paper omitted optimizer, learning rate, batch size, and epoch counts; these are documented as project engineering decisions.
3. **Project Improvements (Corrected Protocol):**
   * **Session/Scenario-Disjoint Splitting:** Strict 70/15/15 grouping ensuring zero session or host overlap between train, validation, and test folds.
   * **Mask-Aware Bidirectional GRU:** Handles padded clumps explicitly with attention pooling, avoiding LSTM unrolling over dummy padding steps.
   * **Class-Weighted BCE Loss:** Mitigates severe class imbalance between benign browsing and tunnel traffic.
   * **Validation-Only Platt Calibration & Threshold Selection:** Selects decision threshold $\tau$ on validation fold under a strict false positive rate cap ($\text{FPR} \le 0.001$). Never tunes thresholds on the test fold.

---

## 2. Security, Privacy & Provenance Principles

1. **Defensive Monitoring Only:**
   * Operates strictly on passive offline PCAP files.
   * Never initiates live DNS tunnels (`iodine`, `dns2tcp`, `dnscat2`) and never replays traffic to live networks.
2. **Zero Binary Artifacts or Raw Data in Git:**
   * Raw PCAP files, nested ZIPs, and binary model weights (`.pt`, `.pkl`, `.h5`) are never committed to version control.
   * All outputs are small, structured JSON/CSV files: `pcap_audit.json`, `metrics.json`, `experiment_manifest.json`, `training_history.csv`, and confusion matrices.
3. **Streaming Ingestion & Bounded Memory:**
   * Discovers PCAPs directly inside nested ZIP archives, spooling nested archive members on-the-fly to bounded temporary files without materializing entire archives in RAM or extracting the corpus to `/kaggle/working`.
   * Enforces symlink containment, zip-bomb validation (uncompressed size, cumulative bytes, and compression ratio), `max_capture_members`, per-flow packet/byte limits, window caps, and class flow quotas to stay within Kaggle resource limits.
4. **Deterministic Provenance Tracking:**
   * Tracks Git commit hash via `KAGGLE_GIT_SHA`.
   * Tracks exact source snapshot hash via `KAGGLE_SOURCE_SNAPSHOT_SHA256`.
   * Injects reviewed execution configuration via `EMBEDDED_CONFIG_JSON`.

---

## 3. Two-Stage Execution Lifecycle

```
                     +---------------------------+
                     |      run_config.json      |
                     +---------------------------+
                                   |
                                   v
                     +---------------------------+
                     |   PCAP / ZIP Discovery    |
                     +---------------------------+
                                   |
                                   v
                     +---------------------------+
                     |     pcap_audit.json       |  <-- Always emitted first
                     +---------------------------+
                                   |
                  +----------------+----------------+
                  |                                 |
          mode: "audit"                     mode: "train"
       (Default Safe Mode)              (Verified Config Only)
                  |                                 |
                  v                                 v
        +-------------------+             +-------------------+
        | Exit 0 with:      |             | - Stream Flows    |
        | - pcap_audit.json |             | - Clump Sequences |
        | - manifest (audit)|             | - Split Datasets  |
        | - metrics (audit) |             | - Train Models    |
        +-------------------+             | - Calibrate & Eval|
                                          +-------------------+
                                                    |
                                                    v
                                          +-------------------+
                                          | Exit 0 with:      |
                                          | - pcap_audit.json |
                                          | - manifest.json   |
                                          | - metrics.json    |
                                          | - train_hist.csv  |
                                          | - CM CSVs         |
                                          +-------------------+
```

### Stage 1: Audit Mode (`mode: "audit"`)
* Safe default. Discovers all PCAPs and nested ZIP members, verifies file sizes, calculates SHA-256 hashes, extracts scenario/session metadata, and emits `pcap_audit.json`.
* Emits minimal `metrics.json` and `experiment_manifest.json` with status `"audit_only"` (never fabricating metric numbers). Exits 0 cleanly.

### Stage 2: Train Mode (`mode: "train"`)
* Requires audited dataset and validated configuration.
* **Quota Enforcement by Flow Label:** Enforces `max_flows_per_class` strictly by actual flow label (`non_doh`, `benign_doh`, `malicious_doh`), not capture category provenance.
* **Bounded Flow Preservation & Exact Window Generation:** Preserves raw flow clumps and canonical L1/L2 labels in `BoundedFlowRecord`s. Generates exact window-specific `SequenceSample`s per task and window size ($l \in \{3, 6\}$) with immutable `SequenceMetadata` (no max-window slicing or frozen metadata mutation).
* **DataLoader Adaptation:** Builds real PyTorch `DataLoader`s yielding `(x, y, mask)` batches for both training and evaluation.
* **Model Loss Isolation:** Passes empirical training `pos_weight` strictly to `improved_bidi_gru`, maintaining pure unweighted BCE for `paper_v4`.
* **Validation-Only Calibration & Operating Threshold:** Evaluates uncalibrated test probabilities via `DataLoader`s, fits Platt calibration strictly validation $\to$ test, selects operating threshold via `(y_val, val_scores)` under target FPR, and guarantees test split independence.
---

## 4. Configuration Schema (`run_config.json`)

| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `mode` | `string` | `"audit"` | Execution mode: `"audit"` (safe) or `"train"`. |
| `dataset_dir` | `string` | `"/kaggle/input/cicdohbrw2020-raw-pcaps"` | Directory of raw PCAP dataset on Kaggle. |
| `dataset_slug` | `string` | `"nhtminhmai/cicdohbrw2020-raw-pcaps"` | Kaggle dataset identifier. |
| `dataset_version` | `string` | `"1"` | Kaggle dataset version string. |
| `task` | `string` | `"both"` | Evaluation task: `"l1"`, `"l2"`, or `"both"`. |
| `split_protocol` | `string` | `"session_scenario_disjoint"` | `"session_scenario_disjoint"`, `"paper_flow_random"`, or `"both"`. |
| `window_sizes` | `list[int]` | `[3, 6]` | Clump sequence window sizes ($l$). |
| `models` | `list[str]` | `["paper_v4", "improved_bidi_gru"]` | Models to train. |
| `seed` | `int` | `42` | Global pseudo-random seed. |
| `max_capture_members` | `int` | `20000` | Discovery ceiling above the observed 13,754 captures; training still stops at per-class flow quotas. |
| `max_flows_per_class` | `int` | `500` | Maximum flows to collect per classification class. |
| `max_flows_per_capture` | `int` | `25` | Prevents one capture/session from exhausting a class quota before group-disjoint splitting. |
| `max_raw_packets` | `int` | `1000000` | Finite upper bound on raw packets parsed per capture (1M). |
| `max_raw_bytes` | `int` | `1073741824` | Finite upper bound on raw packet bytes parsed per capture (1 GB). |
| `max_capture_packets` | `int` | `200000` | Finite upper bound on accepted TLS packets per capture (200k). |
| `max_capture_bytes` | `int` | `536870912` | Finite upper bound on accepted TLS application bytes per capture (512 MB). |
| `max_flow_packets` | `int` | `10000` | Finite upper bound on accepted TLS packets per flow (10k). |
| `max_flow_bytes` | `int` | `52428800` | Finite upper bound on accepted TLS application bytes per flow (50 MB). |
| `max_windows_per_flow` | `int` | `1000` | Finite upper bound on sequence windows materialized per flow (1k). |
| `max_windows_per_class` | `int` | `10000` | Finite upper bound on sequence windows materialized per class (10k). |
| `max_standalone_capture_bytes` | `int` | `21474836480` | Finite upper bound on standalone PCAP file size (20 GB). |
| `max_member_bytes` | `int` | `10737418240` | Finite upper bound on uncompressed PCAP archive member size (10 GB). |
| `max_nested_archive_bytes` | `int` | `26843545600` | Finite upper bound on spooled nested ZIP archive container size (25 GB). |
| `max_total_uncompressed_bytes` | `int` | `214748364800` | Finite aggregate uncompressed expansion budget across all archives (200 GB). |
| `max_compression_ratio` | `float` | `100.0` | Maximum allowed uncompressed-to-compressed ratio for ZIP members. |
| `target_false_positive_rate` | `float` | `0.001` | Target FPR cap for Platt calibration threshold. |
| `epochs` | `int` | `15` | Training epochs per model. |
| `batch_size` | `int` | `64` | Mini-batch size. |
| `learning_rate` | `float` | `0.001` | Adam optimizer learning rate. |
| `patience` | `int` | `5` | Early stopping patience on validation loss. |
| `enable_score_calibration` | `bool` | `true` | Enable validation-only Platt calibration. |
