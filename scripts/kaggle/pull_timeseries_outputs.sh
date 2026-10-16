#!/bin/sh
set -eu

# Discover paths (resolving physical paths)
SCRIPT_DIR="$(cd -P "$(dirname "$0")" && pwd -P)"
PROJECT_ROOT="$(cd -P "$SCRIPT_DIR/../.." && pwd -P)"
VENV_DIR="$PROJECT_ROOT/.venv-tools"

# Helper to load .env safely if present and variable unset
load_env() {
    for env_file in "$SCRIPT_DIR/.env" "$PROJECT_ROOT/.env" ".env"; do
        if [ -f "$env_file" ]; then
            while IFS= read -r line || [ -n "$line" ]; do
                # Strip leading whitespace
                line="${line#"${line%%[! ]*}"}"
                case "$line" in
                    \#*|"") continue ;;
                esac
                case "$line" in
                    [A-Za-z_][A-Za-z0-9_]*=*)
                        key="${line%%=*}"
                        val="${line#*=}"
                        val="${val#\"}"
                        val="${val%\"}"
                        val="${val#\'}"
                        val="${val%\'}"
                        eval "existing_val=\"\${$key:-}\""
                        if [ -z "$existing_val" ]; then
                            eval "export $key=\"\$val\""
                        fi
                        ;;
                esac
            done < "$env_file"
            break
        fi
    done
}

# 1. Parse arguments
FORCE=false
KERNEL_ARG=""
MAX_FILE_BYTES="${KAGGLE_MAX_FILE_BYTES:-10485760}"        # 10 MiB default limit per file
MAX_CUMULATIVE_BYTES="${KAGGLE_MAX_CUMULATIVE_BYTES:-52428800}"  # 50 MiB default cumulative limit

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            echo "Usage: $0 [--force] [--max-file-bytes N] [--max-cumulative-bytes N] [owner/slug]"
            echo ""
            echo "Downloads and verifies output artifacts from the time-series LSTM Kaggle kernel."
            echo "Outputs are stored in artifacts/kaggle/<slug>/."
            echo ""
            echo "Options:"
            echo "  -f, --force                  Overwrite existing files in target directory"
            echo "      --max-file-bytes N       Maximum allowed size for any single artifact file (default: $MAX_FILE_BYTES bytes)"
            echo "      --max-cumulative-bytes N Maximum allowed cumulative size for all artifacts (default: $MAX_CUMULATIVE_BYTES bytes)"
            echo "  -h, --help                   Show this help message"
            echo ""
            echo "Security & Guard Rails:"
            echo "  - Pulls ONLY after kernel status is verified 'complete'."
            echo "  - Requests only exact lightweight outputs via Kaggle CLI --file-pattern (exact producer grammar capping remote discovery)."
            echo "  - Strictly fails on binary weights, PCAPs, archives, or unauthorized arbitrary files."
            echo "  - Enforces local post-download per-file and cumulative byte quotas in quarantine staging before promotion."
            echo "  - Serializes promotion with a lock directory to prevent concurrent collisions."
            echo "  - Atomically replaces target directory on --force with rollback protection to prevent stale or merged artifacts."
            echo "  - Re-verifies required and prohibited files directly on target directory before success."
            exit 0
            ;;
        -f|--force)
            FORCE=true
            shift
            ;;
        --max-file-bytes)
            shift
            if [ $# -eq 0 ]; then
                echo "Error: --max-file-bytes requires an integer argument." >&2
                exit 1
            fi
            MAX_FILE_BYTES="$1"
            shift
            ;;
        --max-cumulative-bytes|--max-total-bytes)
            shift
            if [ $# -eq 0 ]; then
                echo "Error: --max-cumulative-bytes requires an integer argument." >&2
                exit 1
            fi
            MAX_CUMULATIVE_BYTES="$1"
            shift
            ;;
        -*)
            echo "Error: Unknown option '$1'." >&2
            echo "Usage: $0 [--force] [--max-file-bytes N] [--max-cumulative-bytes N] [owner/slug]" >&2
            exit 1
            ;;
        *)
            if [ -z "$KERNEL_ARG" ]; then
                KERNEL_ARG="$1"
            else
                echo "Error: Unexpected additional argument '$1'." >&2
                echo "Usage: $0 [--force] [--max-file-bytes N] [--max-cumulative-bytes N] [owner/slug]" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

# Load .env if present
load_env

# Validate integer byte limits
case "$MAX_FILE_BYTES" in
    ''|*[!0-9]*)
        echo "Error: MAX_FILE_BYTES must be a positive integer, got '$MAX_FILE_BYTES'." >&2
        exit 1
        ;;
esac

case "$MAX_CUMULATIVE_BYTES" in
    ''|*[!0-9]*)
        echo "Error: MAX_CUMULATIVE_BYTES must be a positive integer, got '$MAX_CUMULATIVE_BYTES'." >&2
        exit 1
        ;;
esac

# Target independently from statistical kernel:
if [ -n "$KERNEL_ARG" ]; then
    KAGGLE_KERNEL_ID="$KERNEL_ARG"
elif [ -n "${KAGGLE_TIMESERIES_KERNEL_ID:-}" ]; then
    KAGGLE_KERNEL_ID="$KAGGLE_TIMESERIES_KERNEL_ID"
elif [ -n "${KAGGLE_KERNEL_ID:-}" ]; then
    case "$KAGGLE_KERNEL_ID" in
        */*)
            _owner="${KAGGLE_KERNEL_ID%%/*}"
            _slug="${KAGGLE_KERNEL_ID#*/}"
            if [ "$_slug" != "cicdohbrw2020-timeseries-lstm" ]; then
                KAGGLE_KERNEL_ID="$_owner/cicdohbrw2020-timeseries-lstm"
            fi
            ;;
    esac
fi

# 2. Verify KAGGLE_KERNEL_ID
if [ -z "${KAGGLE_KERNEL_ID:-}" ]; then
    echo "Error: Missing required kernel ID." >&2
    echo "Please provide KAGGLE_KERNEL_ID via argument, environment variable, or $SCRIPT_DIR/.env." >&2
    echo "Example: $0 myusername/cicdohbrw2020-timeseries-lstm" >&2
    exit 1
fi

case "$KAGGLE_KERNEL_ID" in
    */*)
        OWNER="${KAGGLE_KERNEL_ID%%/*}"
        SLUG="${KAGGLE_KERNEL_ID#*/}"
        ;;
    *)
        OWNER="$KAGGLE_KERNEL_ID"
        SLUG="cicdohbrw2020-timeseries-lstm"
        KAGGLE_KERNEL_ID="$OWNER/$SLUG"
        ;;
esac

if [ "$SLUG" != "cicdohbrw2020-timeseries-lstm" ]; then
    echo "Notice: Script targets time-series kernel. Retargeting slug from '$SLUG' to 'cicdohbrw2020-timeseries-lstm'." >&2
    SLUG="cicdohbrw2020-timeseries-lstm"
    KAGGLE_KERNEL_ID="$OWNER/$SLUG"
fi

if [ -z "$OWNER" ] || [ -z "$SLUG" ]; then
    echo "Error: KAGGLE_KERNEL_ID ('$KAGGLE_KERNEL_ID') has empty owner or slug." >&2
    exit 1
fi

case "$OWNER" in
    INSERT_*|YOUR_*|*placeholder*|*PLACEHOLDER*|*\<*|*\>*|your_username|your-username)
        echo "Error: KAGGLE_KERNEL_ID contains placeholder owner: '$OWNER'. Please set your real Kaggle username." >&2
        exit 1
        ;;
esac

case "$SLUG" in
    INSERT_*|YOUR_*|*placeholder*|*PLACEHOLDER*|*\<*|*\>*)
        echo "Error: KAGGLE_KERNEL_ID contains placeholder slug: '$SLUG'." >&2
        exit 1
        ;;
esac

# 3. Verify virtualenv Kaggle CLI, Python binary, and credentials
if [ -n "${KAGGLE_BIN_OVERRIDE:-}" ]; then
    KAGGLE_BIN="$KAGGLE_BIN_OVERRIDE"
else
    KAGGLE_BIN="$VENV_DIR/bin/kaggle"
fi
PYTHON_BIN="$VENV_DIR/bin/python"

if [ ! -x "$KAGGLE_BIN" ]; then
    if [ -n "${KAGGLE_BIN_OVERRIDE:-}" ]; then
        echo "Error: Configured KAGGLE_BIN_OVERRIDE executable not found at '$KAGGLE_BIN'." >&2
        exit 1
    elif command -v kaggle >/dev/null 2>&1; then
        KAGGLE_BIN="$(command -v kaggle)"
    else
        echo "Error: Kaggle CLI executable not found at $KAGGLE_BIN or in PATH." >&2
        echo "Please bootstrap the tools virtual environment first by running:" >&2
        echo "  $PROJECT_ROOT/scripts/kaggle/bootstrap_cli.sh" >&2
        exit 1
    fi
fi

if [ ! -x "$PYTHON_BIN" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    else
        echo "Error: python3 is required for output verification but was not found." >&2
        exit 1
    fi
fi

# Verify Kaggle credentials are configured and not absent (bypassed if CLI is overridden for testing)
if [ -z "${KAGGLE_BIN_OVERRIDE:-}" ]; then
    KAGGLE_CONF_DIR="${KAGGLE_CONFIG_DIR:-$HOME/.kaggle}"
    HAS_KAGGLE_CREDS=false
    if [ -f "$KAGGLE_CONF_DIR/kaggle.json" ] || [ -f "$KAGGLE_CONF_DIR/access_token" ]; then
        HAS_KAGGLE_CREDS=true
    elif [ -f "$HOME/.config/kaggle/kaggle.json" ] || [ -f "$HOME/.config/kaggle/access_token" ]; then
        HAS_KAGGLE_CREDS=true
    elif [ -n "${KAGGLE_USERNAME:-}" ] && [ -n "${KAGGLE_KEY:-}" ]; then
        HAS_KAGGLE_CREDS=true
    fi

    if [ "$HAS_KAGGLE_CREDS" != "true" ]; then
        if ! "$KAGGLE_BIN" kernels list --mine --csv >/dev/null 2>&1; then
            echo "Error: Kaggle credentials absent. Configure ~/.kaggle/kaggle.json, ~/.kaggle/access_token, or export KAGGLE_USERNAME and KAGGLE_KEY." >&2
            exit 1
        fi
    fi
fi

# 4. Strict Guard: Query status and pull ONLY after complete
echo "Querying status for kernel '$KAGGLE_KERNEL_ID'..."
STATUS_EXIT=0
STATUS_OUTPUT="$("$KAGGLE_BIN" kernels status "$KAGGLE_KERNEL_ID" 2>&1)" || STATUS_EXIT=$?

if [ "$STATUS_EXIT" -ne 0 ]; then
    echo "Error: Failed to query status for kernel '$KAGGLE_KERNEL_ID'." >&2
    if [ -n "$STATUS_OUTPUT" ]; then
        echo "$STATUS_OUTPUT" >&2
    fi
    echo "" >&2
    echo "Inspect status and credentials with:" >&2
    echo "  bash scripts/kaggle/status_timeseries_lstm.sh $KAGGLE_KERNEL_ID" >&2
    exit 1
fi

KERNEL_STATUS=""
case "$STATUS_OUTPUT" in
    *has\ status\ \"*\"*)
        KERNEL_STATUS="${STATUS_OUTPUT#*has status \"}"
        KERNEL_STATUS="${KERNEL_STATUS%%\"*}"
        ;;
    *)
        KERNEL_STATUS="$(echo "$STATUS_OUTPUT" | head -n 1 | tr -d '\r\n')"
        ;;
esac

case "$KERNEL_STATUS" in
    *.[Cc][Oo][Mm][Pp][Ll][Ee][Tt][Ee]|[Cc][Oo][Mm][Pp][Ll][Ee][Tt][Ee])
        echo "Kernel status: $KERNEL_STATUS (complete). Proceeding with guarded download."
        ;;
    *.[Qq][Uu][Ee][Uu][Ee][Dd]|*.[Rr][Uu][Nn][Nn][Ii][Nn][Gg]|[Qq][Uu][Ee][Uu][Ee][Dd]|[Rr][Uu][Nn][Nn][Ii][Nn][Gg])
        echo "Error: Refusing to pull outputs: Kernel '$KAGGLE_KERNEL_ID' is not complete (observed status: '$KERNEL_STATUS')." >&2
        echo "Output artifacts cannot be downloaded while execution is queued or running." >&2
        echo "" >&2
        echo "Monitor kernel execution with:" >&2
        echo "  bash scripts/kaggle/status_timeseries_lstm.sh $KAGGLE_KERNEL_ID" >&2
        exit 1
        ;;
    *)
        echo "Error: Refusing to pull outputs: Kernel '$KAGGLE_KERNEL_ID' is not complete (observed status: '${KERNEL_STATUS:-unknown}')." >&2
        echo "Expected completed status before downloading outputs." >&2
        case "$STATUS_OUTPUT" in
            *Failure\ message:*)
                echo "$STATUS_OUTPUT" >&2
                ;;
        esac
        exit 1
        ;;
esac

# 5. Check target directory, ancestors, and overwrite guard
TARGET_DIR="$PROJECT_ROOT/artifacts/kaggle/$SLUG"

verify_destination_invariants() {
    # Reject symlinks in every destination ancestor (artifacts, artifacts/kaggle, leaf)
    if [ -L "$PROJECT_ROOT/artifacts" ]; then
        echo "Error: Ancestor directory '$PROJECT_ROOT/artifacts' is a symbolic link. Symlinks in artifact paths are strictly prohibited." >&2
        exit 1
    fi
    if [ -L "$PROJECT_ROOT/artifacts/kaggle" ]; then
        echo "Error: Ancestor directory '$PROJECT_ROOT/artifacts/kaggle' is a symbolic link. Symlinks in artifact paths are strictly prohibited." >&2
        exit 1
    fi
    if [ -L "$TARGET_DIR" ]; then
        echo "Error: Destination directory '$TARGET_DIR' is a symbolic link. Symlinks in artifact paths are strictly prohibited." >&2
        exit 1
    fi

    # Require resolved target parent under project root
    "$PYTHON_BIN" - "$PROJECT_ROOT" "$TARGET_DIR" <<'PYEOF'
import os
import sys
from pathlib import Path

proj_root = Path(sys.argv[1]).resolve()
target_dir = Path(sys.argv[2])

artifacts_dir = proj_root / "artifacts"
if artifacts_dir.is_symlink():
    print(f"Error: Ancestor directory '{artifacts_dir}' is a symbolic link. Symlinks are forbidden.", file=sys.stderr)
    sys.exit(1)

kaggle_dir = artifacts_dir / "kaggle"
if kaggle_dir.is_symlink():
    print(f"Error: Ancestor directory '{kaggle_dir}' is a symbolic link. Symlinks are forbidden.", file=sys.stderr)
    sys.exit(1)

if target_dir.is_symlink():
    print(f"Error: Destination directory '{target_dir}' is a symbolic link. Symlinks are forbidden.", file=sys.stderr)
    sys.exit(1)

target_parent = target_dir.parent.resolve()
if not (str(target_parent).startswith(str(proj_root) + os.sep) or target_parent == proj_root):
    print(f"Error: Target parent '{target_parent}' is not located inside project root '{proj_root}'.", file=sys.stderr)
    sys.exit(1)
PYEOF
}

verify_destination_invariants

if [ -d "$TARGET_DIR" ]; then
    has_files=false
    for entry in "$TARGET_DIR"/* "$TARGET_DIR"/.*; do
        case "$entry" in
            "$TARGET_DIR/\*"|"$TARGET_DIR/."|"$TARGET_DIR/..")
                continue
                ;;
            *)
                if [ -e "$entry" ] || [ -L "$entry" ]; then
                    has_files=true
                    break
                fi
                ;;
        esac
    done

    if [ "$has_files" = "true" ] && [ "$FORCE" != "true" ]; then
        echo "Error: Destination directory '$TARGET_DIR' exists and is not empty." >&2
        echo "Refusing to overwrite existing outputs without explicit --force." >&2
        echo "Re-run with --force to overwrite: $0 --force $KAGGLE_KERNEL_ID" >&2
        exit 1
    fi
fi

# Exact producer grammar for time-series LSTM artifacts:
# Task: l1, l2
# Model: paper_v4, improved_bidi_gru
# Window: 1..10
# Split: paper_flow_random, session_scenario_disjoint
ALLOWED_FILE_PATTERN='^(pcap_audit\.json|metrics\.json|experiment_manifest\.json|training_history\.csv|confusion_matrix_(l1|l2)_(paper_v4|improved_bidi_gru)_w([1-9]|10)_(paper_flow_random|session_scenario_disjoint)\.csv)$'

# Verification helper function for quarantine and destination directories
verify_artifact_tree() {
    _inspect_dir="$1"
    _stage_name="$2"

    "$PYTHON_BIN" - "$_inspect_dir" "$MAX_FILE_BYTES" "$MAX_CUMULATIVE_BYTES" "$_stage_name" <<'PYEOF'
import csv
import json
import os
import re
import sys

check_dir = sys.argv[1]
max_file_bytes = int(sys.argv[2])
max_cumulative_bytes = int(sys.argv[3])
stage_name = sys.argv[4]

forbidden_exts = {
    ".pt", ".pth", ".bin", ".h5", ".hdf5", ".ckpt", ".onnx", ".weights", ".model",
    ".joblib", ".pkl", ".pickle",
    ".pcap", ".pcapng", ".cap", ".dmp",
    ".tar", ".gz", ".zip", ".bz2", ".xz", ".tgz", ".7z",
}

pcap_magics = [
    b"\xd4\xc3\xb2\xa1",
    b"\xa1\xb2\xc3\xd4",
    b"\x4d\x3c\xb2\xa1",
    b"\xa1\xb2\x3c\x4d",
    b"\x0a\x0d\x0d\x0a",
]

archive_magics = [
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b",
    b"BZh",
    b"7z\xbc\xaf\x27\x1c",
    b"\xfd7zXZ\x00",
]

# Exact producer grammar:
# 3 JSONs + 1 training history + (2 tasks * 2 models * 10 windows * 2 splits = 80 CMs) => max 84 files
allowed_pattern = re.compile(
    r"^(pcap_audit\.json|metrics\.json|experiment_manifest\.json|training_history\.csv|confusion_matrix_(l1|l2)_(paper_v4|improved_bidi_gru)_w([1-9]|10)_(paper_flow_random|session_scenario_disjoint)\.csv)$"
)

required_artifacts = ["pcap_audit.json", "metrics.json", "experiment_manifest.json"]
MAX_ALLOWED_FILES = 84

if not os.path.isdir(check_dir):
    print(f"Error [{stage_name}]: Directory does not exist: {check_dir}", file=sys.stderr)
    sys.exit(1)

entries = os.listdir(check_dir)
if not entries:
    print(f"Error [{stage_name}]: Directory '{check_dir}' is empty. No artifacts retrieved.", file=sys.stderr)
    sys.exit(1)

found_files = {}
total_bytes = 0

for fname in entries:
    fpath = os.path.join(check_dir, fname)

    if os.path.islink(fpath):
        print(f"Error [{stage_name}]: Symbolic link detected at '{fname}'. Symbolic links are forbidden.", file=sys.stderr)
        sys.exit(1)

    if os.path.isdir(fpath):
        print(f"Error [{stage_name}]: Unexpected nested directory '{fname}' detected. Only flat artifact files are permitted.", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(fpath):
        print(f"Error [{stage_name}]: Non-regular file '{fname}' detected.", file=sys.stderr)
        sys.exit(1)

    # 1. Reject prohibited extensions
    ext = os.path.splitext(fname)[1].lower()
    if ext in forbidden_exts:
        print(f"Error [{stage_name}]: Prohibited artifact extension '{ext}' detected on '{fname}'. Model weights, raw PCAPs, and archives are strictly forbidden.", file=sys.stderr)
        sys.exit(1)

    # 2. Reject arbitrary outputs not in strict producer grammar
    if not allowed_pattern.match(fname):
        print(f"Error [{stage_name}]: Disallowed/arbitrary artifact '{fname}' detected. Does not match exact producer grammar.", file=sys.stderr)
        sys.exit(1)

    # 3. Size limit checks
    size = os.path.getsize(fpath)
    if size > max_file_bytes:
        print(f"Error [{stage_name}]: File '{fname}' size ({size} bytes) exceeds limit of {max_file_bytes} bytes.", file=sys.stderr)
        sys.exit(1)

    total_bytes += size
    if total_bytes > max_cumulative_bytes:
        print(f"Error [{stage_name}]: Cumulative artifact size ({total_bytes} bytes) exceeds limit of {max_cumulative_bytes} bytes.", file=sys.stderr)
        sys.exit(1)

    # 4. Check binary magic bytes
    try:
        with open(fpath, "rb") as bf:
            head = bf.read(8)
            if any(head.startswith(m) for m in pcap_magics):
                print(f"Error [{stage_name}]: Raw PCAP magic bytes detected in '{fname}'.", file=sys.stderr)
                sys.exit(1)
            if any(head.startswith(m) for m in archive_magics):
                print(f"Error [{stage_name}]: Compressed archive magic bytes detected in '{fname}'.", file=sys.stderr)
                sys.exit(1)
            bf.seek(257)
            if bf.read(5) == b"ustar":
                print(f"Error [{stage_name}]: TAR archive magic bytes detected in '{fname}'.", file=sys.stderr)
                sys.exit(1)
    except Exception as exc:
        print(f"Error [{stage_name}]: Failed to inspect binary content of '{fname}': {exc}", file=sys.stderr)
        sys.exit(1)

    found_files[fname] = fpath

# 5. Finite file count enforcement
if len(found_files) > MAX_ALLOWED_FILES:
    print(f"Error [{stage_name}]: Total file count ({len(found_files)}) exceeds maximum allowed finite count of {MAX_ALLOWED_FILES}.", file=sys.stderr)
    sys.exit(1)

# 6. Verify required artifacts
missing = []
empty = []
invalid_json = []

for req in required_artifacts:
    if req not in found_files:
        missing.append(req)
    else:
        p = found_files[req]
        if os.path.getsize(p) == 0:
            empty.append(req)
        else:
            try:
                with open(p, "r", encoding="utf-8") as jf:
                    data = json.load(jf)
                    if not isinstance(data, dict):
                        invalid_json.append((req, "Root JSON value must be an object/dict"))
            except Exception as exc:
                invalid_json.append((req, str(exc)))

if missing:
    print(f"Error [{stage_name}]: Required lightweight artifact(s) missing: {missing}", file=sys.stderr)
    print(f"Found files: {sorted(found_files.keys())}", file=sys.stderr)
    sys.exit(1)

if empty:
    print(f"Error [{stage_name}]: Required artifact(s) are empty (0 bytes): {empty}", file=sys.stderr)
    sys.exit(1)

if invalid_json:
    print(f"Error [{stage_name}]: Required artifact(s) contain invalid JSON: {invalid_json}", file=sys.stderr)
    sys.exit(1)

# 7. Verify CSV headers and schema
for fname, p in found_files.items():
    if fname.endswith(".csv"):
        if os.path.getsize(p) == 0:
            print(f"Error [{stage_name}]: CSV file '{fname}' is empty (0 bytes).", file=sys.stderr)
            sys.exit(1)
        try:
            with open(p, "r", encoding="utf-8") as cf:
                reader = list(csv.reader(cf))
            if not reader:
                print(f"Error [{stage_name}]: CSV file '{fname}' has no rows.", file=sys.stderr)
                sys.exit(1)
            header = [h.strip() for h in reader[0]]

            if fname == "training_history.csv":
                expected_header = ["task", "model", "window_size", "split_protocol", "epoch", "train_loss", "val_loss"]
                if header != expected_header:
                    print(f"Error [{stage_name}]: CSV '{fname}' header mismatch: expected {expected_header}, got {header}", file=sys.stderr)
                    sys.exit(1)
                data_rows = reader[1:]
                if not data_rows:
                    print(f"Error [{stage_name}]: CSV '{fname}' contains no data rows.", file=sys.stderr)
                    sys.exit(1)
                for r_idx, row in enumerate(data_rows, start=2):
                    if len(row) != 7:
                        print(f"Error [{stage_name}]: CSV '{fname}' row {r_idx} has {len(row)} columns, expected 7.", file=sys.stderr)
                        sys.exit(1)
                    t, m, w, s, ep, tl, vl = [c.strip() for c in row]
                    if t not in ("l1", "l2"):
                        print(f"Error [{stage_name}]: CSV '{fname}' row {r_idx} invalid task '{t}'.", file=sys.stderr)
                        sys.exit(1)
                    if m not in ("paper_v4", "improved_bidi_gru"):
                        print(f"Error [{stage_name}]: CSV '{fname}' row {r_idx} invalid model '{m}'.", file=sys.stderr)
                        sys.exit(1)
                    if not (1 <= int(w) <= 10):
                        print(f"Error [{stage_name}]: CSV '{fname}' row {r_idx} invalid window '{w}'.", file=sys.stderr)
                        sys.exit(1)
                    if s not in ("paper_flow_random", "session_scenario_disjoint"):
                        print(f"Error [{stage_name}]: CSV '{fname}' row {r_idx} invalid split '{s}'.", file=sys.stderr)
                        sys.exit(1)
                    int(ep)
                    float(tl)
                    float(vl)

            elif fname.startswith("confusion_matrix_"):
                expected_header = ["actual", "predicted_negative", "predicted_positive"]
                if header != expected_header:
                    print(f"Error [{stage_name}]: CSV '{fname}' header mismatch: expected {expected_header}, got {header}", file=sys.stderr)
                    sys.exit(1)
                data_rows = reader[1:]
                if len(data_rows) != 2:
                    print(f"Error [{stage_name}]: CSV '{fname}' must have exactly 2 data rows, got {len(data_rows)}.", file=sys.stderr)
                    sys.exit(1)
                row1, row2 = data_rows
                if len(row1) != 3 or len(row2) != 3:
                    print(f"Error [{stage_name}]: CSV '{fname}' data rows must have 3 columns.", file=sys.stderr)
                    sys.exit(1)
                if row1[0].strip() != "negative":
                    print(f"Error [{stage_name}]: CSV '{fname}' row 1 actual must be 'negative', got '{row1[0]}'.", file=sys.stderr)
                    sys.exit(1)
                if row2[0].strip() != "positive":
                    print(f"Error [{stage_name}]: CSV '{fname}' row 2 actual must be 'positive', got '{row2[0]}'.", file=sys.stderr)
                    sys.exit(1)
                int(row1[1].strip())
                int(row1[2].strip())
                int(row2[1].strip())
                int(row2[2].strip())
        except Exception as exc:
            print(f"Error [{stage_name}]: CSV validation failed on '{fname}': {exc}", file=sys.stderr)
            sys.exit(1)

print(f"[{stage_name}] Artifact verification passed: {len(found_files)} verified file(s), {total_bytes} bytes total.")
PYEOF
}

# 6. Download outputs into a temporary quarantine directory for safety inspection
# NOTE: The remote Kaggle API does not expose pre-transfer file byte metadata in its session output endpoint.
# Pre-transfer bounding is enforced by the exact finite filename grammar above (--file-pattern), which caps
# discoverable remote files to at most 84 known lightweight artifacts and blocks arbitrary/model/PCAP files.
# Per-file (MAX_FILE_BYTES) and cumulative (MAX_CUMULATIVE_BYTES) byte quotas are enforced locally in quarantine
# immediately post-download before deep inspection and promotion (failing closed).
PULL_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kaggle_pull_ts.XXXXXXXXXX")"
trap 'rm -rf "$PULL_TEMP_DIR"' EXIT INT TERM HUP

echo "Downloading outputs for kernel '$KAGGLE_KERNEL_ID' into quarantine staging..."
PULL_EXIT=0
if [ "$FORCE" = "true" ]; then
    "$KAGGLE_BIN" kernels output "$KAGGLE_KERNEL_ID" -p "$PULL_TEMP_DIR" --force --file-pattern "$ALLOWED_FILE_PATTERN" || PULL_EXIT=$?
else
    "$KAGGLE_BIN" kernels output "$KAGGLE_KERNEL_ID" -p "$PULL_TEMP_DIR" --file-pattern "$ALLOWED_FILE_PATTERN" || PULL_EXIT=$?
fi

if [ "$PULL_EXIT" -ne 0 ]; then
    echo "Error: Kaggle CLI output command failed for kernel '$KAGGLE_KERNEL_ID' (exit code $PULL_EXIT)." >&2
    exit "$PULL_EXIT"
fi

# Clean up auxiliary execution log automatically written by Kaggle CLI client
# so quarantine and final destination contain only the exact requested lightweight artifacts.
rm -f "$PULL_TEMP_DIR/$SLUG.log"

# Enforce early per-file and cumulative byte quotas immediately after download
EARLY_CUMULATIVE_BYTES=0
for entry in "$PULL_TEMP_DIR"/* "$PULL_TEMP_DIR"/.*; do
    case "$entry" in
        "$PULL_TEMP_DIR/\*"|"$PULL_TEMP_DIR/."|"$PULL_TEMP_DIR/..")
            continue
            ;;
        *)
            if [ -L "$entry" ]; then
                echo "Error: Quarantined artifact '$(basename "$entry")' is a symbolic link. Symlinks are strictly prohibited." >&2
                exit 1
            fi
            if [ -f "$entry" ]; then
                _fsize="$(wc -c < "$entry" | tr -d ' \t\r\n')"
                if [ "$_fsize" -gt "$MAX_FILE_BYTES" ]; then
                    echo "Error: Quarantined artifact '$(basename "$entry")' size ($_fsize bytes) exceeds limit of $MAX_FILE_BYTES bytes." >&2
                    exit 1
                fi
                EARLY_CUMULATIVE_BYTES=$((EARLY_CUMULATIVE_BYTES + _fsize))
                if [ "$EARLY_CUMULATIVE_BYTES" -gt "$MAX_CUMULATIVE_BYTES" ]; then
                    echo "Error: Quarantined artifacts cumulative size ($EARLY_CUMULATIVE_BYTES bytes) exceeds limit of $MAX_CUMULATIVE_BYTES bytes." >&2
                    exit 1
                fi
            fi
            ;;
    esac
done

# 7. Quarantine Inspection:
echo "Performing security and artifact completeness inspection on quarantine..."
verify_artifact_tree "$PULL_TEMP_DIR" "quarantine"

# 8. Promote verified lightweight artifacts to target directory atomically with rollback protection
verify_destination_invariants

TARGET_PARENT="$(dirname "$TARGET_DIR")"
mkdir -p "$TARGET_PARENT"
verify_destination_invariants

# Serialize promotion with a lock directory
LOCK_DIR="${TARGET_DIR}.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "Error: Could not acquire promotion lock at '$LOCK_DIR'. Another operation may be in progress." >&2
    exit 1
fi

STAGE_DIR="$(mktemp -d "$TARGET_DIR.stage.XXXXXXXXXX")"

# Variables for rollback management
ROLLBACK_NEEDED=false
BACKUP_DIR=""

cleanup_promotion() {
    _exit_status=$?
    trap - EXIT INT TERM HUP
    if [ "$ROLLBACK_NEEDED" = "true" ] && [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
        echo "Notice: Operation failed or interrupted. Rolling back prior target directory from '$BACKUP_DIR'..." >&2
        if [ -d "$TARGET_DIR" ]; then
            rm -rf "$TARGET_DIR"
        fi
        if mv "$BACKUP_DIR" "$TARGET_DIR"; then
            echo "Notice: Successfully rolled back prior target directory from backup." >&2
        else
            echo "CRITICAL: Rollback failed! Prior target directory could not be restored and remains at '$BACKUP_DIR'." >&2
        fi
        ROLLBACK_NEEDED=false
    fi
    if [ -n "$STAGE_DIR" ] && [ -d "$STAGE_DIR" ]; then
        rm -rf "$STAGE_DIR"
    fi
    if [ -n "$LOCK_DIR" ] && [ -d "$LOCK_DIR" ]; then
        rmdir "$LOCK_DIR" 2>/dev/null || rm -rf "$LOCK_DIR"
    fi
    if [ -n "$PULL_TEMP_DIR" ] && [ -d "$PULL_TEMP_DIR" ]; then
        rm -rf "$PULL_TEMP_DIR"
    fi
    exit "$_exit_status"
}

# Install signal/EXIT rollback trap BEFORE moving old target
trap cleanup_promotion EXIT INT TERM HUP

# Copy verified files from quarantine to stage directory (failing on error, never suppressing)
cp -p "$PULL_TEMP_DIR"/* "$STAGE_DIR"/

# Atomic replacement: Move existing TARGET_DIR to BACKUP_DIR if present
if [ -d "$TARGET_DIR" ]; then
    BACKUP_DIR="$(mktemp -d "$TARGET_DIR.old.XXXXXXXXXX")"
    rmdir "$BACKUP_DIR"
    ROLLBACK_NEEDED=true
    if ! mv "$TARGET_DIR" "$BACKUP_DIR"; then
        echo "Error: Failed to move existing target directory '$TARGET_DIR' to backup location." >&2
        ROLLBACK_NEEDED=false
        exit 1
    fi
fi

# Promote staging directory to TARGET_DIR
if ! mv "$STAGE_DIR" "$TARGET_DIR"; then
    echo "Error: Failed to promote staging artifacts to target directory '$TARGET_DIR'." >&2
    exit 1
fi

# 9. Re-run required-file and prohibited-file checks against final destination before success
# Backup is retained through final verification: if verification fails, the cleanup_promotion trap restores backup!
echo "Performing defense-in-depth verification on final destination directory..."
verify_artifact_tree "$TARGET_DIR" "final destination"

# Verification passed: Disarm rollback and clean up backup and lock
ROLLBACK_NEEDED=false
if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    rm -rf "$BACKUP_DIR"
fi
if [ -n "$LOCK_DIR" ] && [ -d "$LOCK_DIR" ]; then
    rmdir "$LOCK_DIR" 2>/dev/null || rm -rf "$LOCK_DIR"
fi

# Reset trap to clean up only quarantine staging on normal exit
trap 'rm -rf "$PULL_TEMP_DIR"' EXIT INT TERM HUP

REGULAR_FILE_COUNT="$(find "$TARGET_DIR" -type f 2>/dev/null | wc -l | tr -d ' \t\r\n')"

if [ "$REGULAR_FILE_COUNT" -eq 0 ]; then
    echo "Error: Output directory '$TARGET_DIR' contains no regular files after download." >&2
    exit 1
fi

echo ""
echo "Output download and verification complete ($REGULAR_FILE_COUNT regular file(s) retrieved)."
echo "Destination: $TARGET_DIR"
ls -lh "$TARGET_DIR"
