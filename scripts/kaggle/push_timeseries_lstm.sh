#!/bin/sh
set -eu

# Discover paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv-tools"
KERNEL_SRC_DIR="$PROJECT_ROOT/experiments/kaggle/timeseries_clump_lstm"
SRC_PACKAGE_DIR="$PROJECT_ROOT/src/doh_reproduction"

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

# Load .env if present
load_env

# 1. Parse arguments
DRY_RUN=false
DRY_RUN_DIR=""
KERNEL_ARG=""

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            echo "Usage: $0 [--dry-run [out_dir]] [owner/slug]"
            echo ""
            echo "Packages and pushes the time-series packet-clump LSTM kernel to Kaggle with truthful provenance."
            echo ""
            echo "Options:"
            echo "  --dry-run [out_dir]  Perform full packaging, staging, security audit, and snapshot"
            echo "                       calculation without calling Kaggle API or pushing kernel."
            echo ""
            echo "Prerequisites:"
            echo "  1. KAGGLE_KERNEL_ID or KAGGLE_TIMESERIES_KERNEL_ID set via argument, environment, or $SCRIPT_DIR/.env"
            echo "  2. Kaggle CLI installed via scripts/kaggle/bootstrap_cli.sh"
            echo "  3. Private raw-PCAP dataset uploaded and ready (verified via kaggle datasets status for train mode)"
            echo "  4. For official reproducible results: source committed and clean in Git"
            echo "     (audit runs may proceed with snapshot hash while source is untracked)"
            echo "  5. Kaggle credentials configured (~/.kaggle/kaggle.json, access_token, or env vars)"
            exit 0
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            if [ $# -gt 0 ]; then
                case "$1" in
                    -*)
                        # Next token is another option
                        ;;
                    /*|./*|../*|~*)
                        # Absolute or path-like token is output directory
                        DRY_RUN_DIR="$1"
                        shift
                        ;;
                    *)
                        if [ -d "$1" ] || [ $# -ge 2 ]; then
                            # Existing directory or followed by later owner/slug arg
                            DRY_RUN_DIR="$1"
                            shift
                        fi
                        ;;
                esac
            fi
            ;;
        --dry-run=*)
            DRY_RUN=true
            DRY_RUN_DIR="${1#*=}"
            shift
            ;;
        -*)
            echo "Error: Unknown option '$1'." >&2
            echo "Usage: $0 [--dry-run [out_dir]] [owner/slug]" >&2
            exit 1
            ;;
        *)
            KERNEL_ARG="$1"
            shift
            ;;
    esac
done

# Target independently from statistical kernel:
# If user provided an argument, use it; otherwise prefer KAGGLE_TIMESERIES_KERNEL_ID, then KAGGLE_KERNEL_ID
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

# 3. Verify Kaggle CLI, Python binary, and credentials
KAGGLE_BIN="$VENV_DIR/bin/kaggle"
PYTHON_BIN="$VENV_DIR/bin/python"

if [ ! -x "$KAGGLE_BIN" ]; then
    if command -v kaggle >/dev/null 2>&1; then
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
        echo "Error: python3 is required for kernel staging but was not found." >&2
        exit 1
    fi
fi

# Verify Kaggle credentials are configured and not absent
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
    # Test if CLI has working auth anyway (e.g. keyring / keychain)
    if ! "$KAGGLE_BIN" kernels list --mine --csv >/dev/null 2>&1; then
        echo "Error: Kaggle credentials absent. Configure ~/.kaggle/kaggle.json, ~/.kaggle/access_token, or export KAGGLE_USERNAME and KAGGLE_KEY." >&2
        exit 1
    fi
fi

# 4. Verify kernel source directory and required files
if [ ! -d "$KERNEL_SRC_DIR" ]; then
    echo "Error: Kernel source directory not found at $KERNEL_SRC_DIR." >&2
    exit 1
fi

METADATA_SRC="$KERNEL_SRC_DIR/kernel-metadata.json"
if [ ! -f "$METADATA_SRC" ]; then
    echo "Error: kernel-metadata.json not found at $METADATA_SRC." >&2
    exit 1
fi

CODE_SRC="$KERNEL_SRC_DIR/train_timeseries.py"
if [ ! -f "$CODE_SRC" ]; then
    echo "Error: Kernel code file train_timeseries.py not found at $CODE_SRC." >&2
    exit 1
fi

CONFIG_SRC="$KERNEL_SRC_DIR/run_config.json"
if [ ! -f "$CONFIG_SRC" ]; then
    echo "Error: Run configuration file run_config.json not found at $CONFIG_SRC." >&2
    exit 1
fi

if [ ! -d "$SRC_PACKAGE_DIR" ]; then
    echo "Error: Source package directory not found at $SRC_PACKAGE_DIR." >&2
    exit 1
fi

# 5. Strictly validate run_config.json before staging
echo "Validating run_config.json..."
CONFIG_VALIDATION_OUT="$("$PYTHON_BIN" - "$CONFIG_SRC" <<'PYEOF'
import json
import re
import sys

config_path = sys.argv[1]

try:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except Exception as exc:
    print(f"Error: Failed to parse JSON from {config_path}: {exc}", file=sys.stderr)
    sys.exit(1)

if not isinstance(cfg, dict):
    print(f"Error: run_config.json must contain a JSON object, got {type(cfg).__name__}", file=sys.stderr)
    sys.exit(1)

# Check mode
mode = cfg.get("mode")
if mode not in ("audit", "train"):
    print(f"Error: Invalid 'mode' in run_config.json: {mode!r}. Must be 'audit' or 'train'.", file=sys.stderr)
    sys.exit(1)

# Check placeholder tokens across all string fields
placeholder_pattern = re.compile(r"INSERT_[A-Za-z0-9_]+|YOUR_[A-Za-z0-9_]+|<[^>]+>|your_username|your-username|placeholder", re.IGNORECASE)
for k, v in cfg.items():
    if isinstance(v, str) and placeholder_pattern.search(v):
        print(f"Error: Placeholder detected in run_config.json field '{k}': {v!r}", file=sys.stderr)
        sys.exit(1)

# Validate split_protocol
split_proto = cfg.get("split_protocol")
valid_splits = ("session_scenario_disjoint", "paper_flow_random", "both")
if split_proto is not None and split_proto not in valid_splits:
    print(f"Error: Invalid 'split_protocol' {split_proto!r}. Must be one of {valid_splits}.", file=sys.stderr)
    sys.exit(1)

# Validate task
task = cfg.get("task")
valid_tasks = ("l1", "l2", "both")
if task is not None and task not in valid_tasks:
    print(f"Error: Invalid 'task' {task!r}. Must be one of {valid_tasks}.", file=sys.stderr)
    sys.exit(1)

# Validate models
models = cfg.get("models")
valid_model_names = {"paper_v4", "improved_bidi_gru"}
if models is not None:
    if isinstance(models, str):
        models = [models]
    if not isinstance(models, list) or not models:
        print("Error: 'models' in run_config.json must be a non-empty list of model names.", file=sys.stderr)
        sys.exit(1)
    for m in models:
        if m not in valid_model_names:
            print(f"Error: Invalid model name {m!r} in 'models'. Must be in {sorted(valid_model_names)}.", file=sys.stderr)
            sys.exit(1)

# Validate window_sizes
window_sizes = cfg.get("window_sizes")
if window_sizes is not None:
    if not isinstance(window_sizes, list) or not window_sizes:
        print("Error: 'window_sizes' must be a non-empty list of positive integers.", file=sys.stderr)
        sys.exit(1)
    for w in window_sizes:
        if not isinstance(w, int) or isinstance(w, bool) or w <= 0:
            print(f"Error: Invalid window size {w!r}. Must be positive integer.", file=sys.stderr)
            sys.exit(1)

# Validate numerical parameters
seed = cfg.get("seed")
if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
    print(f"Error: Invalid 'seed' {seed!r}. Must be integer.", file=sys.stderr)
    sys.exit(1)

max_capture = cfg.get("max_capture_members")
if max_capture is not None and (not isinstance(max_capture, int) or isinstance(max_capture, bool) or max_capture <= 0):
    print(f"Error: Invalid 'max_capture_members' {max_capture!r}. Must be positive integer.", file=sys.stderr)
    sys.exit(1)

max_flows = cfg.get("max_flows_per_class")
if max_flows is not None and (not isinstance(max_flows, int) or isinstance(max_flows, bool) or max_flows <= 0):
    print(f"Error: Invalid 'max_flows_per_class' {max_flows!r}. Must be positive integer.", file=sys.stderr)
    sys.exit(1)

batch_size = cfg.get("batch_size")
if batch_size is not None and (not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0):
    print(f"Error: Invalid 'batch_size' {batch_size!r}. Must be positive integer.", file=sys.stderr)
    sys.exit(1)

epochs = cfg.get("epochs")
if epochs is not None and (not isinstance(epochs, int) or isinstance(epochs, bool) or epochs <= 0):
    print(f"Error: Invalid 'epochs' {epochs!r}. Must be positive integer.", file=sys.stderr)
    sys.exit(1)

lr = cfg.get("learning_rate")
if lr is not None and (not isinstance(lr, (int, float)) or isinstance(lr, bool) or lr <= 0 or lr >= 1.0):
    print(f"Error: Invalid 'learning_rate' {lr!r}. Must be float in (0.0, 1.0).", file=sys.stderr)
    sys.exit(1)

target_fpr = cfg.get("target_false_positive_rate")
if target_fpr is not None and (not isinstance(target_fpr, (int, float)) or isinstance(target_fpr, bool) or not (0.0 < float(target_fpr) < 1.0)):
    print(f"Error: Invalid 'target_false_positive_rate' {target_fpr!r}. Must be float in (0.0, 1.0).", file=sys.stderr)
    sys.exit(1)

# Enforce strict requirements for train mode
if mode == "train":
    if not cfg.get("dataset_slug") and not cfg.get("dataset_dir"):
        print("Error: 'dataset_slug' or 'dataset_dir' is required in run_config.json for train mode.", file=sys.stderr)
        sys.exit(1)
    if not task:
        print("Error: 'task' ('l1', 'l2', or 'both') is required in run_config.json for train mode.", file=sys.stderr)
        sys.exit(1)
    if not split_proto:
        print("Error: 'split_protocol' is required in run_config.json for train mode.", file=sys.stderr)
        sys.exit(1)
    if not models:
        print("Error: 'models' must be specified for train mode.", file=sys.stderr)
        sys.exit(1)
    if not window_sizes:
        print("Error: 'window_sizes' must be specified for train mode.", file=sys.stderr)
        sys.exit(1)

# Emit mode and dataset slug
dataset_slug = cfg.get("dataset_slug", "")
print(f"MODE={mode}")
print(f"DATASET_SLUG={dataset_slug}")
PYEOF
)"

RUN_MODE="$(echo "$CONFIG_VALIDATION_OUT" | grep '^MODE=' | cut -d= -f2)"
CONFIG_DATASET_SLUG="$(echo "$CONFIG_VALIDATION_OUT" | grep '^DATASET_SLUG=' | cut -d= -f2)"

# 6. Inspect Git tracking and provenance context
PARENT_GIT_SHA="none"
if command -v git >/dev/null 2>&1; then
    PARENT_GIT_SHA="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || true)"
    if [ -z "$PARENT_GIT_SHA" ]; then
        PARENT_GIT_SHA="none"
    fi
fi

IS_TRACKED=0
IS_CLEAN=0
GIT_SOURCE_STATUS="unknown"

if [ "$PARENT_GIT_SHA" != "none" ]; then
    TRACKED_CODE=0
    TRACKED_PKG=0
    if git -C "$PROJECT_ROOT" ls-files --error-unmatch "$KERNEL_SRC_DIR/train_timeseries.py" >/dev/null 2>&1; then
        TRACKED_CODE=1
    fi
    if git -C "$PROJECT_ROOT" ls-files --error-unmatch "$SRC_PACKAGE_DIR/clumping.py" >/dev/null 2>&1; then
        TRACKED_PKG=1
    fi

    if [ "$TRACKED_CODE" = "1" ] && [ "$TRACKED_PKG" = "1" ]; then
        IS_TRACKED=1
        DIRTY_CHECK="$(git -C "$PROJECT_ROOT" status --porcelain -- "$KERNEL_SRC_DIR" "$SRC_PACKAGE_DIR" 2>/dev/null || true)"
        if [ -z "$DIRTY_CHECK" ]; then
            IS_CLEAN=1
            GIT_SOURCE_STATUS="tracked_and_clean"
        else
            GIT_SOURCE_STATUS="uncommitted_changes"
        fi
    else
        GIT_SOURCE_STATUS="untracked_in_git"
    fi
else
    GIT_SOURCE_STATUS="no_git_repository"
fi

# Strict check: Reject dirty/untracked source for train mode; allow audit mode with truthful unknown_uncommitted_source
if [ "$RUN_MODE" = "train" ]; then
    if [ "$IS_TRACKED" != "1" ] || [ "$IS_CLEAN" != "1" ]; then
        echo "Error: Refusing to push official train kernel from dirty or untracked source ($GIT_SOURCE_STATUS)." >&2
        echo "Official reproducible train runs require clean, committed Git provenance." >&2
        echo "To run schema/PCAP audit without training, set \"mode\": \"audit\" in run_config.json." >&2
        echo "To push an official train experiment, commit all changes in $KERNEL_SRC_DIR and $SRC_PACKAGE_DIR first." >&2
        exit 1
    fi
    KAGGLE_GIT_SHA="$PARENT_GIT_SHA"
    echo "Git provenance: Kernel source is tracked and clean at commit $KAGGLE_GIT_SHA."
else
    if [ "$IS_TRACKED" = "1" ] && [ "$IS_CLEAN" = "1" ]; then
        KAGGLE_GIT_SHA="$PARENT_GIT_SHA"
        echo "Git provenance: Kernel source is tracked and clean at commit $KAGGLE_GIT_SHA."
    else
        KAGGLE_GIT_SHA="unknown_uncommitted_source"
        echo "Notice: Kernel source is not tracked and clean at parent git commit (${PARENT_GIT_SHA:-none})." >&2
        echo "  Status: $GIT_SOURCE_STATUS" >&2
        echo "  KAGGLE_GIT_SHA recorded as: unknown_uncommitted_source" >&2
        echo "  Push provenance is evidenced by deterministic KAGGLE_SOURCE_SNAPSHOT_SHA256." >&2
        echo "  Audit execution is permitted with unknown_uncommitted_source." >&2
    fi
fi

export KAGGLE_GIT_SHA
export PARENT_GIT_SHA

# 7. Resolve and validate private dataset readiness
DATASET_ID="${KAGGLE_DATASET_ID:-}"
if [ -z "$DATASET_ID" ]; then
    if [ -n "$CONFIG_DATASET_SLUG" ]; then
        DATASET_ID="$CONFIG_DATASET_SLUG"
    else
        DATASET_ID="nhtminhmai/cicdohbrw2020-raw-pcaps"
    fi
fi

# Reject placeholders in DATASET_ID
case "$DATASET_ID" in
    INSERT_*|YOUR_*|*placeholder*|*PLACEHOLDER*|*\<*|*\>*)
        echo "Error: DATASET_ID contains placeholder: '$DATASET_ID'." >&2
        exit 1
        ;;
esac

case "$DATASET_ID" in
    */*)
        ;;
    *)
        echo "Error: DATASET_ID ('$DATASET_ID') must match 'owner/slug' format." >&2
        exit 1
        ;;
esac

echo "Validating dataset readiness for '$DATASET_ID'..."
DATASET_STATUS_EXIT=0
DATASET_STATUS_RAW="$("$KAGGLE_BIN" datasets status "$DATASET_ID" 2>&1)" || DATASET_STATUS_EXIT=$?

if [ "$RUN_MODE" = "train" ]; then
    if [ "$DATASET_STATUS_EXIT" -ne 0 ]; then
        echo "Error: Private dataset '$DATASET_ID' is missing or inaccessible via Kaggle CLI." >&2
        echo "$DATASET_STATUS_RAW" >&2
        echo "Please ensure the dataset exists and is accessible. Upload with:" >&2
        echo "  $PROJECT_ROOT/scripts/kaggle/upload_raw_pcap_dataset.sh" >&2
        exit 1
    fi

    case "$DATASET_STATUS_RAW" in
        *[Rr][Ee][Aa][Dd][Yy]*)
            echo "Dataset '$DATASET_ID' is verified ready."
            ;;
        *)
            echo "Error: Private dataset '$DATASET_ID' is not ready (status output: '$DATASET_STATUS_RAW')." >&2
            echo "Kaggle may still be unpacking or processing the archive server-side." >&2
            echo "Wait until dataset status is 'ready' before pushing the kernel." >&2
            exit 1
            ;;
    esac
else
    # Audit mode: audit may run while inspecting an attached ready dataset
    if [ "$DATASET_STATUS_EXIT" -eq 0 ]; then
        case "$DATASET_STATUS_RAW" in
            *[Rr][Ee][Aa][Dd][Yy]*)
                echo "Attached dataset '$DATASET_ID' is ready for audit inspection."
                ;;
            *)
                echo "Notice: Attached dataset '$DATASET_ID' status: '$DATASET_STATUS_RAW'."
                echo "Audit execution is permitted while dataset is processing or inspecting."
                ;;
        esac
    else
        echo "Notice: Could not query dataset status for '$DATASET_ID' ($DATASET_STATUS_RAW)."
        echo "Audit execution is permitted without requiring server-side dataset readiness."
    fi
fi

# 8. Stage runner and src/doh_reproduction package into temporary directory
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kaggle_push_timeseries.XXXXXXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT INT TERM

# Render temporary metadata outside version control and verify placeholders
"$PYTHON_BIN" - "$METADATA_SRC" "$TEMP_DIR/kernel-metadata.json" "$KAGGLE_KERNEL_ID" "$DATASET_ID" <<'PYEOF'
import sys
import json
import re

src_path = sys.argv[1]
dst_path = sys.argv[2]
kernel_id = sys.argv[3]
dataset_id = sys.argv[4]

with open(src_path, "r", encoding="utf-8") as f:
    try:
        data = json.load(f)
    except Exception as exc:
        print(f"Error: Invalid JSON in {src_path}: {exc}", file=sys.stderr)
        sys.exit(1)

# Assign verified kernel id and dataset sources
data["id"] = kernel_id
data["dataset_sources"] = [dataset_id]
data["code_file"] = "train_timeseries.py"
data["enable_gpu"] = True
data["enable_internet"] = False
data["is_private"] = True
rendered = json.dumps(data, indent=2)

# Verify no placeholders remain
placeholder_patterns = [
    r"INSERT_[A-Za-z0-9_]+",
    r"YOUR_[A-Za-z0-9_]+",
    r"<[^>]+>",
    r"your_username",
    r"your-username",
    r"placeholder",
]
for pat in placeholder_patterns:
    found = re.findall(pat, rendered, re.IGNORECASE)
    if found:
        print(f"Error: Rendered kernel-metadata.json still contains placeholder pattern '{pat}': {found}", file=sys.stderr)
        sys.exit(1)

with open(dst_path, "w", encoding="utf-8") as f:
    f.write(rendered + "\n")
PYEOF

# Copy declared kernel files only (excluding metadata template and hidden files)
for file_item in "$KERNEL_SRC_DIR"/*; do
    if [ -f "$file_item" ]; then
        base_name="$(basename "$file_item")"
        if [ "$base_name" != "kernel-metadata.json" ]; then
            cp "$file_item" "$TEMP_DIR/$base_name"
        fi
    fi
done

# Stage all required src/doh_reproduction modules into staged package
mkdir -p "$TEMP_DIR/doh_reproduction"
for pkg_file in "$SRC_PACKAGE_DIR"/*; do
    if [ -f "$pkg_file" ]; then
        pkg_base="$(basename "$pkg_file")"
        case "$pkg_base" in
            *.py)
                cp "$pkg_file" "$TEMP_DIR/doh_reproduction/$pkg_base"
                ;;
        esac
    fi
done

# Ensure package __init__.py is present
if [ ! -f "$TEMP_DIR/doh_reproduction/__init__.py" ]; then
    touch "$TEMP_DIR/doh_reproduction/__init__.py"
fi

# Clean any pycache or temporary files in staged package
rm -rf "$TEMP_DIR/doh_reproduction/__pycache__" "$TEMP_DIR/doh_reproduction/"*.pyc

# 9. Strict security audit of staged directory: reject placeholders, secrets, and raw PCAPs
echo "Auditing staged directory for security compliance (zero secrets, zero PCAPs, zero placeholders)..."
"$PYTHON_BIN" - "$TEMP_DIR" <<'PYEOF'
import os
import re
import sys

temp_dir = sys.argv[1]

# Forbidden extensions (never push binary weights or raw capture bytes)
forbidden_exts = {
    ".pcap", ".pcapng", ".cap", ".dmp",
    ".pt", ".pth", ".bin", ".h5", ".ckpt", ".onnx", ".weights", ".model",
    ".tar", ".gz", ".zip", ".bz2", ".xz",
}

pcap_magics = [
    b"\xd4\xc3\xb2\xa1",  # Standard PCAP (microsecond)
    b"\xa1\xb2\xc3\xd4",  # Standard PCAP (swapped)
    b"\x4d\x3c\xb2\xa1",  # Nanosecond PCAP
    b"\xa1\xb2\x3c\x4d",  # Nanosecond PCAP (swapped)
    b"\x0a\x0d\x0d\x0a",  # PCAPNG
]

placeholder_patterns = [
    re.compile(r"INSERT_[A-Za-z0-9_]+", re.IGNORECASE),
    re.compile(r"YOUR_[A-Za-z0-9_]+", re.IGNORECASE),
    re.compile(r"<(?:owner|slug|username|user|kaggle_username|kernel_id|dataset_id|token|key|api_key|password)>", re.IGNORECASE),
    re.compile(r"\byour_username\b", re.IGNORECASE),
    re.compile(r"\byour-username\b", re.IGNORECASE),
]

secret_patterns = [
    re.compile(r"-----BEGIN\s+[A-Z\s]+PRIVATE\s+KEY-----"),
    re.compile(r'"key"\s*:\s*"[0-9a-fA-F]{32}"'),
    re.compile(r'KAGGLE_KEY\s*=\s*["\']?[0-9a-fA-F]{32}["\']?'),
    re.compile(r'AKIA[0-9A-Z]{16}'),
]

for root, dirs, files in os.walk(temp_dir):
    # Remove pycache
    if "__pycache__" in dirs:
        dirs.remove("__pycache__")
    for fname in files:
        fpath = os.path.join(root, fname)
        rel = os.path.relpath(fpath, temp_dir)
        ext = os.path.splitext(fname)[1].lower()

        # Check forbidden extensions
        if ext in forbidden_exts:
            print(f"Error: Forbidden file type '{ext}' found in staged kernel: {rel}", file=sys.stderr)
            sys.exit(1)

        # Check magic bytes for PCAP
        try:
            with open(fpath, "rb") as f:
                head = f.read(8)
                if any(head.startswith(m) for m in pcap_magics):
                    print(f"Error: Raw PCAP bytes detected in staged file: {rel}", file=sys.stderr)
                    sys.exit(1)
        except Exception:
            pass

        # Text files inspection for secrets and placeholders
        if ext in (".py", ".json", ".txt", ".md", ".sh"):
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                # Exclude README from generic placeholder checks
                if fname != "README.md":
                    for pat in placeholder_patterns:
                        m = pat.search(content)
                        if m:
                            print(f"Error: Unresolved placeholder {m.group(0)!r} in staged file: {rel}", file=sys.stderr)
                            sys.exit(1)
                for spat in secret_patterns:
                    m = spat.search(content)
                    if m:
                        print(f"Error: Secret pattern detected in staged file: {rel}", file=sys.stderr)
                        sys.exit(1)
            except Exception as exc:
                print(f"Error inspecting {rel}: {exc}", file=sys.stderr)
                sys.exit(1)

print("Security audit passed: 0 secrets, 0 PCAP files, 0 placeholders.")
PYEOF

# 10. Inject provenance and configuration constants at exact declarations
echo "Injecting configuration and Git provenance at exact declarations in train_timeseries.py..."
"$PYTHON_BIN" - "$CONFIG_SRC" "$TEMP_DIR/train_timeseries.py" "$KAGGLE_GIT_SHA" <<'PYEOF'
import json
import os
import re
import sys

config_path = sys.argv[1]
script_path = sys.argv[2]
git_sha = sys.argv[3]

with open(config_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

clean_json_str = json.dumps(cfg, indent=2)
escaped_json_literal = json.dumps(clean_json_str)

if not os.path.isfile(script_path):
    print(f"Error: Script file '{script_path}' not found for injection.", file=sys.stderr)
    sys.exit(1)

with open(script_path, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Inject EMBEDDED_CONFIG_JSON at exact declaration
pattern_cfg = re.compile(r'^(EMBEDDED_CONFIG_JSON(?:\s*:[^=]+)?\s*=\s*).*$', re.MULTILINE)
if not pattern_cfg.search(code):
    print(f"Error: Could not find declaration of EMBEDDED_CONFIG_JSON in {script_path}.", file=sys.stderr)
    sys.exit(1)

code, count_cfg = pattern_cfg.subn(lambda m: m.group(1) + escaped_json_literal, code, count=1)
if count_cfg != 1:
    print(f"Error: Failed to inject EMBEDDED_CONFIG_JSON (replacements={count_cfg}).", file=sys.stderr)
    sys.exit(1)

# 2. Inject KAGGLE_GIT_SHA at exact declaration
pattern_git = re.compile(r'^(KAGGLE_GIT_SHA(?:\s*:[^=]+)?\s*=\s*).*$', re.MULTILINE)
if not pattern_git.search(code):
    print(f"Error: Could not find declaration of KAGGLE_GIT_SHA in {script_path}.", file=sys.stderr)
    sys.exit(1)

code, count_git = pattern_git.subn(lambda m: m.group(1) + f'os.environ.get("KAGGLE_GIT_SHA", "{git_sha}")', code, count=1)
if count_git != 1:
    print(f"Error: Failed to inject KAGGLE_GIT_SHA (replacements={count_git}).", file=sys.stderr)
    sys.exit(1)

with open(script_path, "w", encoding="utf-8") as f:
    f.write(code)

print("Successfully injected EMBEDDED_CONFIG_JSON and KAGGLE_GIT_SHA at exact declarations.")
PYEOF

# 11. Compute deterministic SHA-256 content snapshot over deterministic files
KAGGLE_SOURCE_SNAPSHOT_SHA256="$("$PYTHON_BIN" - "$TEMP_DIR" <<'PYEOF'
import hashlib
import os
import re
import sys

temp_dir = sys.argv[1]

all_files = []
for root, dirs, files in os.walk(temp_dir):
    if "__pycache__" in dirs:
        dirs.remove("__pycache__")
    for f in sorted(files):
        if f != "kernel-metadata.json" and not f.startswith(".") and not f.endswith(".pyc"):
            fpath = os.path.join(root, f)
            relpath = os.path.relpath(fpath, temp_dir).replace("\\", "/")
            all_files.append((relpath, fpath))

all_files.sort(key=lambda item: item[0])

if not all_files:
    print("Error: No kernel files found in temporary directory.", file=sys.stderr)
    sys.exit(1)

hasher = hashlib.sha256()
for relpath, fpath in all_files:
    hasher.update(relpath.encode("utf-8"))
    hasher.update(b"\0")
    with open(fpath, "rb") as f:
        if os.path.basename(fpath) == "train_timeseries.py":
            # Deterministic normalization of snapshot constant declaration before hashing
            content = f.read()
            norm_content = re.sub(
                rb'^(KAGGLE_SOURCE_SNAPSHOT_SHA256(?:\s*:[^=]+)?\s*=\s*).*$',
                rb'\1os.environ.get("KAGGLE_SOURCE_SNAPSHOT_SHA256", "unknown")',
                content,
                flags=re.MULTILINE,
            )
            hasher.update(norm_content)
        else:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
    hasher.update(b"\0")

print(hasher.hexdigest())
PYEOF
)"
export KAGGLE_SOURCE_SNAPSHOT_SHA256

# 12. Inject resolved KAGGLE_SOURCE_SNAPSHOT_SHA256 at exact declaration and validate syntax
echo "Injecting KAGGLE_SOURCE_SNAPSHOT_SHA256 at exact declaration..."
"$PYTHON_BIN" - "$TEMP_DIR/train_timeseries.py" "$KAGGLE_SOURCE_SNAPSHOT_SHA256" <<'PYEOF'
import ast
import re
import sys

script_file = sys.argv[1]
snapshot_sha = sys.argv[2]

with open(script_file, "r", encoding="utf-8") as f:
    code = f.read()

pattern_snap = re.compile(r'^(KAGGLE_SOURCE_SNAPSHOT_SHA256(?:\s*:[^=]+)?\s*=\s*).*$', re.MULTILINE)
if not pattern_snap.search(code):
    print(f"Error: Could not find declaration of KAGGLE_SOURCE_SNAPSHOT_SHA256 in {script_file}.", file=sys.stderr)
    sys.exit(1)

code, count_snap = pattern_snap.subn(
    lambda m: m.group(1) + f'os.environ.get("KAGGLE_SOURCE_SNAPSHOT_SHA256", "{snapshot_sha}")',
    code,
    count=1,
)
if count_snap != 1:
    print(f"Error: Failed to inject KAGGLE_SOURCE_SNAPSHOT_SHA256 (replacements={count_snap}).", file=sys.stderr)
    sys.exit(1)

# Validate syntax of injected code
try:
    ast.parse(code, filename="train_timeseries.py")
except SyntaxError as exc:
    print(f"Error: Syntax error in train_timeseries.py after provenance injection: {exc}", file=sys.stderr)
    sys.exit(1)

with open(script_file, "w", encoding="utf-8") as f:
    f.write(code)

print("Injected source is syntactically valid.")
PYEOF

# 12.5. Verify staged package imports resolve
echo "Verifying staged package imports resolve..."
"$PYTHON_BIN" - "$TEMP_DIR" <<'PYEOF'
import sys
import os

temp_dir = sys.argv[1]
sys.path.insert(0, temp_dir)

try:
    import doh_reproduction
    from doh_reproduction import clumping, pcap, raw_dataset, timeseries_data, timeseries_models
    print("Staged imports verified: doh_reproduction package resolves correctly.")
except Exception as exc:
    print(f"Error: Failed to resolve staged doh_reproduction package imports: {exc}", file=sys.stderr)
    sys.exit(1)
PYEOF

if [ "$DRY_RUN" = "true" ]; then
    echo ""
    echo "================================================================="
    echo "Dry-run packaging complete (no network side effects)."
    echo "================================================================="
    echo "  Kernel ID: $KAGGLE_KERNEL_ID"
    echo "  Mode: $RUN_MODE"
    echo "  Dataset ID: $DATASET_ID"
    echo "  Kernel Git SHA: $KAGGLE_GIT_SHA"
    echo "  Source snapshot SHA-256: $KAGGLE_SOURCE_SNAPSHOT_SHA256"
    if [ -n "$DRY_RUN_DIR" ]; then
        mkdir -p "$DRY_RUN_DIR"
        cp -R "$TEMP_DIR"/* "$DRY_RUN_DIR"/
        echo "  Staged kernel directory preserved at: $DRY_RUN_DIR"
    else
        trap - EXIT INT TERM
        echo "  Staged kernel directory preserved at: $TEMP_DIR"
    fi
    exit 0
fi

# 13. Push kernel via Kaggle CLI
echo "Pushing kernel '$KAGGLE_KERNEL_ID'..."
echo "  Mode: $RUN_MODE"
echo "  Dataset: $DATASET_ID"
echo "  Parent worktree Git SHA: ${PARENT_GIT_SHA:-none}"
echo "  Kernel Git SHA (KAGGLE_GIT_SHA): $KAGGLE_GIT_SHA"
echo "  Source snapshot SHA-256 (KAGGLE_SOURCE_SNAPSHOT_SHA256): $KAGGLE_SOURCE_SNAPSHOT_SHA256"
echo "  Staged directory: $TEMP_DIR"
"$KAGGLE_BIN" kernels push -p "$TEMP_DIR"

echo "Kernel push initiated successfully."
echo "Monitor execution status with:"
echo "  bash scripts/kaggle/status_timeseries_lstm.sh $KAGGLE_KERNEL_ID"
echo "Download outputs once complete with:"
echo "  bash scripts/kaggle/pull_timeseries_outputs.sh $KAGGLE_KERNEL_ID"
