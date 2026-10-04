#!/bin/sh
set -eu

# Discover paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv-tools"
KERNEL_SRC_DIR="$PROJECT_ROOT/experiments/kaggle/statistical_baseline"

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
if [ $# -gt 0 ]; then
    case "$1" in
        -h|--help)
            echo "Usage: $0 [owner/slug]"
            echo ""
            echo "Pushes the statistical baseline kernel to Kaggle with truthful provenance."
            echo ""
            echo "Prerequisites:"
            echo "  1. KAGGLE_KERNEL_ID set via argument, environment, or $SCRIPT_DIR/.env"
            echo "  2. Kaggle CLI installed via scripts/kaggle/bootstrap_cli.sh"
            echo "  3. Source snapshot hash computed automatically (KAGGLE_SOURCE_SNAPSHOT_SHA256)"
            echo "  4. For official reproducible results: source committed and clean in Git"
            echo "     (audit runs may proceed with snapshot hash while source is untracked)"
            echo "  5. Kaggle credentials configured (~/.kaggle/kaggle.json or 'kaggle auth login')"
            exit 0
            ;;
        -*)
            echo "Error: Unknown option '$1'." >&2
            echo "Usage: $0 [owner/slug]" >&2
            exit 1
            ;;
        *)
            KAGGLE_KERNEL_ID="$1"
            ;;
    esac
fi

# Load .env if KAGGLE_KERNEL_ID is not yet set
if [ -z "${KAGGLE_KERNEL_ID:-}" ]; then
    load_env
fi

# 2. Verify KAGGLE_KERNEL_ID
if [ -z "${KAGGLE_KERNEL_ID:-}" ]; then
    echo "Error: Missing required kernel ID." >&2
    echo "Please provide KAGGLE_KERNEL_ID via argument, environment variable, or $SCRIPT_DIR/.env." >&2
    echo "Example: $0 myusername/cicdohbrw2020-statistical-baseline" >&2
    exit 1
fi

case "$KAGGLE_KERNEL_ID" in
    */*)
        OWNER="${KAGGLE_KERNEL_ID%%/*}"
        SLUG="${KAGGLE_KERNEL_ID#*/}"
        ;;
    *)
        echo "Error: KAGGLE_KERNEL_ID ('$KAGGLE_KERNEL_ID') must match 'owner/slug' format." >&2
        exit 1
        ;;
esac

case "$SLUG" in
    */*)
        echo "Error: KAGGLE_KERNEL_ID ('$KAGGLE_KERNEL_ID') must contain exactly one slash ('owner/slug')." >&2
        exit 1
        ;;
esac

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

# 3. Inspect Git tracking and provenance context
# Note: A parent worktree commit SHA does NOT prove kernel source identity
# unless the kernel source files are tracked and clean at that commit.
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
    if git -C "$PROJECT_ROOT" ls-files --error-unmatch "$KERNEL_SRC_DIR/train_statistical.py" >/dev/null 2>&1; then
        IS_TRACKED=1
        DIRTY_CHECK="$(git -C "$PROJECT_ROOT" status --porcelain -- "$KERNEL_SRC_DIR" 2>/dev/null || true)"
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

if [ "$IS_TRACKED" = "1" ] && [ "$IS_CLEAN" = "1" ]; then
    KAGGLE_GIT_SHA="$PARENT_GIT_SHA"
    echo "Git provenance: Kernel source is tracked and clean at commit $KAGGLE_GIT_SHA."
else
    # Truthful provenance: do not claim Git commit proves source identity unless tracked and clean.
    KAGGLE_GIT_SHA="unknown_uncommitted_source"
    echo "Notice: Kernel source is not tracked and clean at parent git commit (${PARENT_GIT_SHA:-none})." >&2
    echo "  Status: $GIT_SOURCE_STATUS" >&2
    echo "  KAGGLE_GIT_SHA recorded as: unknown_uncommitted_source" >&2
    echo "  Push provenance is evidenced by deterministic KAGGLE_SOURCE_SNAPSHOT_SHA256." >&2
    echo "  Note: Official experiment results require committing this project to Git before promotion." >&2
fi

case "$KAGGLE_GIT_SHA" in
    unknown_uncommitted_source)
        ;;
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]*)
        ;;
    *)
        echo "Error: Invalid git commit SHA '$KAGGLE_GIT_SHA'." >&2
        exit 1
        ;;
esac

export KAGGLE_GIT_SHA
export PARENT_GIT_SHA

# 4. Verify kernel source directory and metadata template
if [ ! -d "$KERNEL_SRC_DIR" ]; then
    echo "Error: Kernel source directory not found at $KERNEL_SRC_DIR." >&2
    exit 1
fi

METADATA_SRC="$KERNEL_SRC_DIR/kernel-metadata.json"
if [ ! -f "$METADATA_SRC" ]; then
    echo "Error: kernel-metadata.json not found at $METADATA_SRC." >&2
    exit 1
fi

CODE_SRC="$KERNEL_SRC_DIR/train_statistical.py"
if [ ! -f "$CODE_SRC" ]; then
    echo "Error: Kernel code file train_statistical.py not found at $CODE_SRC." >&2
    exit 1
fi

CONFIG_SRC="$KERNEL_SRC_DIR/run_config.json"
if [ ! -f "$CONFIG_SRC" ]; then
    echo "Error: Run configuration file run_config.json not found at $CONFIG_SRC." >&2
    exit 1
fi

# 5. Verify virtualenv Kaggle CLI
KAGGLE_BIN="$VENV_DIR/bin/kaggle"
PYTHON_BIN="$VENV_DIR/bin/python"

if [ ! -x "$KAGGLE_BIN" ]; then
    echo "Error: Kaggle CLI executable not found at $KAGGLE_BIN." >&2
    echo "Please bootstrap the tools virtual environment first by running:" >&2
    echo "  $PROJECT_ROOT/scripts/kaggle/bootstrap_cli.sh" >&2
    exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v python3)"
    else
        echo "Error: python3 is required for metadata rendering but was not found." >&2
        exit 1
    fi
fi

# 6. Render temporary metadata outside version control and verify placeholders
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kaggle_push.XXXXXXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT INT TERM

"$PYTHON_BIN" - "$METADATA_SRC" "$TEMP_DIR/kernel-metadata.json" "$KAGGLE_KERNEL_ID" <<'PYEOF'
import sys
import json
import re

src_path = sys.argv[1]
dst_path = sys.argv[2]
kernel_id = sys.argv[3]

with open(src_path, "r", encoding="utf-8") as f:
    try:
        data = json.load(f)
    except Exception as exc:
        print(f"Error: Invalid JSON in {src_path}: {exc}", file=sys.stderr)
        sys.exit(1)

# Assign verified kernel id
data["id"] = kernel_id

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

# Validate local tracked run_config.json and inject into temporary train_statistical.py
# before computing/uploading the source snapshot
echo "Validating run_config.json and injecting embedded configuration..."
"$PYTHON_BIN" - "$CONFIG_SRC" "$TEMP_DIR/train_statistical.py" <<'PYEOF'
import json
import os
import re
import sys

config_path = sys.argv[1]
script_path = sys.argv[2]

if not os.path.isfile(config_path):
    print(f"Error: Local tracked run_config.json not found at {config_path}", file=sys.stderr)
    sys.exit(1)

try:
    with open(config_path, "r", encoding="utf-8") as f:
        config_raw = f.read()
    cfg = json.loads(config_raw)
except Exception as exc:
    print(f"Error: Failed to parse JSON from {config_path}: {exc}", file=sys.stderr)
    sys.exit(1)

if not isinstance(cfg, dict):
    print(f"Error: run_config.json must contain a JSON object (dict), got {type(cfg).__name__}", file=sys.stderr)
    sys.exit(1)

# Validate mode
mode = cfg.get("mode")
if mode not in ("audit", "train"):
    print(f"Error: Invalid 'mode' in run_config.json: {mode!r}. Must be 'audit' or 'train'.", file=sys.stderr)
    sys.exit(1)

# Validate data_file / csv_file
data_file = cfg.get("data_file")
csv_file = cfg.get("csv_file")
target_file = data_file if data_file is not None else csv_file
if target_file is not None and not isinstance(target_file, str):
    print(f"Error: 'data_file' in run_config.json must be a string or null, got {type(target_file).__name__}", file=sys.stderr)
    sys.exit(1)

# Validate task
task = cfg.get("task")
if task is not None and task not in ("l1", "l2"):
    print(f"Error: Invalid 'task' in run_config.json: {task!r}. Must be 'l1', 'l2', or null.", file=sys.stderr)
    sys.exit(1)

if mode == "train":
    if not target_file or not target_file.strip():
        print("Error: 'data_file' (or 'csv_file') is required in run_config.json when mode is 'train'.", file=sys.stderr)
        sys.exit(1)
    if not task:
        print("Error: 'task' ('l1' or 'l2') is required in run_config.json when mode is 'train'.", file=sys.stderr)
        sys.exit(1)

# Validate model
model = cfg.get("model")
valid_models = {"all", "random_forest", "decision_tree", "gaussian_nb", "linear_svm"}
if model is not None and model not in valid_models:
    print(f"Error: Invalid 'model' in run_config.json: {model!r}. Must be one of {sorted(valid_models)}.", file=sys.stderr)
    sys.exit(1)

# Validate seed
seed = cfg.get("seed")
if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
    print(f"Error: Invalid 'seed' in run_config.json: {seed!r}. Must be integer.", file=sys.stderr)
    sys.exit(1)

# Validate max_samples_per_class
max_samples = cfg.get("max_samples_per_class")
if max_samples is not None and (not isinstance(max_samples, int) or isinstance(max_samples, bool) or max_samples <= 0):
    print(f"Error: Invalid 'max_samples_per_class' in run_config.json: {max_samples!r}. Must be positive integer or null.", file=sys.stderr)
    sys.exit(1)

# Serialize canonical JSON and escape safely for a Python string literal
clean_json_str = json.dumps(cfg, indent=2)
escaped_json_literal = json.dumps(clean_json_str)

if not os.path.isfile(script_path):
    print(f"Error: Temporary script '{script_path}' not found for injection.", file=sys.stderr)
    sys.exit(1)

with open(script_path, "r", encoding="utf-8") as f:
    script_content = f.read()

pattern = re.compile(r'^(EMBEDDED_CONFIG_JSON(?:\s*:[^=]+)?\s*=\s*)None\b', re.MULTILINE)
if not pattern.search(script_content):
    print(
        "Error: Could not find explicit embedded-config constant 'EMBEDDED_CONFIG_JSON = None' in train_statistical.py. "
        "Cannot inject validated run_config.json into kernel script.",
        file=sys.stderr,
    )
    sys.exit(1)

updated_script, count = pattern.subn(lambda m: m.group(1) + escaped_json_literal, script_content, count=1)
if count != 1:
    print(f"Error: Failed to inject embedded configuration into train_statistical.py (replacements={count}).", file=sys.stderr)
    sys.exit(1)

try:
    import ast
    ast.parse(updated_script, filename="train_statistical.py")
except SyntaxError as exc:
    print(f"Error: Syntax error in train_statistical.py after configuration injection: {exc}", file=sys.stderr)
    sys.exit(1)

with open(script_path, "w", encoding="utf-8") as f:
    f.write(updated_script)

print(f"Validated run_config.json and injected embedded configuration (mode='{mode}').")
PYEOF

# Compute deterministic SHA-256 content snapshot across exact kernel files copied
KAGGLE_SOURCE_SNAPSHOT_SHA256="$("$PYTHON_BIN" - "$TEMP_DIR" <<'PYEOF'
import hashlib
import os
import sys

temp_dir = sys.argv[1]

candidate_files = sorted([
    f for f in os.listdir(temp_dir)
    if f != "kernel-metadata.json" and not f.startswith(".") and os.path.isfile(os.path.join(temp_dir, f))
])

if not candidate_files:
    print("Error: No kernel files found in temporary directory.", file=sys.stderr)
    sys.exit(1)

hasher = hashlib.sha256()
for fname in candidate_files:
    hasher.update(fname.encode("utf-8"))
    hasher.update(b"\0")
    fpath = os.path.join(temp_dir, fname)
    with open(fpath, "rb") as f:
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

# Inject resolved KAGGLE_GIT_SHA and KAGGLE_SOURCE_SNAPSHOT_SHA256 into temporary script for Kaggle execution provenance
if [ -f "$TEMP_DIR/train_statistical.py" ]; then
    "$PYTHON_BIN" - "$TEMP_DIR/train_statistical.py" "$KAGGLE_GIT_SHA" "$KAGGLE_SOURCE_SNAPSHOT_SHA256" <<'PYEOF'
import sys

script_file = sys.argv[1]
git_sha = sys.argv[2]
snapshot_sha = sys.argv[3]

with open(script_file, "r", encoding="utf-8") as f:
    code = f.read()

# Replace fallback default for KAGGLE_GIT_SHA
updated_code = code.replace(
    'os.environ.get("KAGGLE_GIT_SHA", "unknown")',
    f'os.environ.get("KAGGLE_GIT_SHA", "{git_sha}")'
)

# Replace fallback default for KAGGLE_SOURCE_SNAPSHOT_SHA256
updated_code = updated_code.replace(
    'os.environ.get("KAGGLE_SOURCE_SNAPSHOT_SHA256", "unknown")',
    f'os.environ.get("KAGGLE_SOURCE_SNAPSHOT_SHA256", "{snapshot_sha}")'
)

# Inject explicit runtime environment defaults after "import os"
env_inject = (
    f'\nos.environ.setdefault("KAGGLE_GIT_SHA", "{git_sha}")\n'
    f'os.environ.setdefault("KAGGLE_SOURCE_SNAPSHOT_SHA256", "{snapshot_sha}")\n'
)
if "import os\n" in updated_code:
    updated_code = updated_code.replace("import os\n", f"import os\n{env_inject}", 1)

with open(script_file, "w", encoding="utf-8") as f:
    f.write(updated_code)
PYEOF
fi

# 7. Invoke project virtualenv CLI
echo "Pushing kernel '$KAGGLE_KERNEL_ID'..."
echo "  Parent worktree Git SHA: ${PARENT_GIT_SHA:-none}"
echo "  Kernel Git SHA (KAGGLE_GIT_SHA): $KAGGLE_GIT_SHA"
echo "  Source snapshot SHA-256 (KAGGLE_SOURCE_SNAPSHOT_SHA256): $KAGGLE_SOURCE_SNAPSHOT_SHA256"
echo "  Kernel directory: $KERNEL_SRC_DIR"
"$KAGGLE_BIN" kernels push -p "$TEMP_DIR"
