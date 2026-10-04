#!/bin/sh
set -eu

# Discover paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
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

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            echo "Usage: $0 [--force] [owner/slug]"
            echo ""
            echo "Downloads output artifacts from a Kaggle kernel execution into artifacts/kaggle/<slug>/."
            echo ""
            echo "Options:"
            echo "  -f, --force    Overwrite existing files in target directory"
            echo "  -h, --help     Show this help message"
            echo ""
            echo "Prerequisites:"
            echo "  1. KAGGLE_KERNEL_ID set via argument, environment, or $SCRIPT_DIR/.env"
            echo "  2. Kaggle CLI installed via scripts/kaggle/bootstrap_cli.sh"
            echo "  3. Kaggle credentials configured (~/.kaggle/kaggle.json or 'kaggle auth login')"
            echo "  4. Kernel execution status is complete (monitored via status.sh)"
            exit 0
            ;;
        -f|--force)
            FORCE=true
            shift
            ;;
        -*)
            echo "Error: Unknown option '$1'." >&2
            echo "Usage: $0 [--force] [owner/slug]" >&2
            exit 1
            ;;
        *)
            if [ -z "$KERNEL_ARG" ]; then
                KERNEL_ARG="$1"
            else
                echo "Error: Unexpected additional argument '$1'." >&2
                echo "Usage: $0 [--force] [owner/slug]" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -n "$KERNEL_ARG" ]; then
    KAGGLE_KERNEL_ID="$KERNEL_ARG"
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

# 3. Verify virtualenv Kaggle CLI
KAGGLE_BIN="$VENV_DIR/bin/kaggle"

if [ ! -x "$KAGGLE_BIN" ]; then
    echo "Error: Kaggle CLI executable not found at $KAGGLE_BIN." >&2
    echo "Please bootstrap the tools virtual environment first by running:" >&2
    echo "  $PROJECT_ROOT/scripts/kaggle/bootstrap_cli.sh" >&2
    exit 1
fi

# 4. Verify kernel execution status via Kaggle CLI
echo "Querying status for kernel '$KAGGLE_KERNEL_ID'..."
STATUS_EXIT=0
STATUS_OUTPUT="$("$KAGGLE_BIN" kernels status "$KAGGLE_KERNEL_ID" 2>&1)" || STATUS_EXIT=$?

if [ "$STATUS_EXIT" -ne 0 ]; then
    echo "Error: Failed to query status for kernel '$KAGGLE_KERNEL_ID'." >&2
    if [ -n "$STATUS_OUTPUT" ]; then
        echo "$STATUS_OUTPUT" >&2
    fi
    echo "" >&2
    echo "Next command to inspect status and credentials:" >&2
    echo "  bash scripts/kaggle/status.sh $KAGGLE_KERNEL_ID" >&2
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
        echo "Kernel status: $KERNEL_STATUS (complete)"
        ;;
    *.[Qq][Uu][Ee][Uu][Ee][Dd]|*.[Rr][Uu][Nn][Nn][Ii][Nn][Gg]|[Qq][Uu][Ee][Uu][Ee][Dd]|[Rr][Uu][Nn][Nn][Ii][Nn][Gg])
        echo "Error: Kernel '$KAGGLE_KERNEL_ID' is not complete (observed status: '$KERNEL_STATUS')." >&2
        echo "Output artifacts cannot be downloaded while execution is queued or running." >&2
        echo "" >&2
        echo "Next command to monitor kernel status:" >&2
        echo "  bash scripts/kaggle/status.sh $KAGGLE_KERNEL_ID" >&2
        echo "" >&2
        echo "Once status reports complete, download outputs with:" >&2
        if [ "$FORCE" = "true" ]; then
            echo "  $0 --force $KAGGLE_KERNEL_ID" >&2
        else
            echo "  $0 $KAGGLE_KERNEL_ID" >&2
        fi
        exit 1
        ;;
    *)
        echo "Error: Kernel '$KAGGLE_KERNEL_ID' is not complete (observed status: '${KERNEL_STATUS:-unknown}')." >&2
        echo "Expected completed status before downloading outputs." >&2
        case "$STATUS_OUTPUT" in
            *Failure\ message:*)
                echo "$STATUS_OUTPUT" >&2
                ;;
        esac
        echo "" >&2
        echo "Next command to inspect kernel status:" >&2
        echo "  bash scripts/kaggle/status.sh $KAGGLE_KERNEL_ID" >&2
        exit 1
        ;;
esac

# 5. Check target directory and overwrite guard
TARGET_DIR="$PROJECT_ROOT/artifacts/kaggle/$SLUG"

if [ -d "$TARGET_DIR" ]; then
    has_files=false
    for entry in "$TARGET_DIR"/* "$TARGET_DIR"/.*; do
        case "$entry" in
            "$TARGET_DIR/\*"|"$TARGET_DIR/."|"$TARGET_DIR/..")
                continue
                ;;
            *)
                if [ -e "$entry" ]; then
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

mkdir -p "$TARGET_DIR"

# 6. Download outputs
echo "Downloading outputs for kernel '$KAGGLE_KERNEL_ID'..."
echo "Destination: $TARGET_DIR"

if [ "$FORCE" = "true" ]; then
    "$KAGGLE_BIN" kernels output "$KAGGLE_KERNEL_ID" -p "$TARGET_DIR" --force
else
    "$KAGGLE_BIN" kernels output "$KAGGLE_KERNEL_ID" -p "$TARGET_DIR"
fi

# 7. Verify retrieved artifacts
REGULAR_FILE_COUNT="$(find "$TARGET_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')"

if [ "$REGULAR_FILE_COUNT" -eq 0 ]; then
    echo "Error: Output directory '$TARGET_DIR' contains no regular files after download." >&2
    echo "Kernel '$KAGGLE_KERNEL_ID' did not produce any output artifacts, or output retrieval failed." >&2
    exit 1
fi

echo ""
echo "Output download complete ($REGULAR_FILE_COUNT regular file(s) retrieved). Contents of $TARGET_DIR:"
ls -lh "$TARGET_DIR" 2>/dev/null || true
