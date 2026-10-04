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
if [ $# -gt 0 ]; then
    case "$1" in
        -h|--help)
            echo "Usage: $0 [owner/slug]"
            echo ""
            echo "Checks the status of a Kaggle kernel execution."
            echo ""
            echo "Prerequisites:"
            echo "  1. KAGGLE_KERNEL_ID set via argument, environment, or $SCRIPT_DIR/.env"
            echo "  2. Kaggle CLI installed via scripts/kaggle/bootstrap_cli.sh"
            echo "  3. Kaggle credentials configured (~/.kaggle/kaggle.json or 'kaggle auth login')"
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

# 3. Verify virtualenv Kaggle CLI
KAGGLE_BIN="$VENV_DIR/bin/kaggle"

if [ ! -x "$KAGGLE_BIN" ]; then
    echo "Error: Kaggle CLI executable not found at $KAGGLE_BIN." >&2
    echo "Please bootstrap the tools virtual environment first by running:" >&2
    echo "  $PROJECT_ROOT/scripts/kaggle/bootstrap_cli.sh" >&2
    exit 1
fi

# 4. Invoke Kaggle CLI
echo "Querying status for kernel '$KAGGLE_KERNEL_ID'..."
"$KAGGLE_BIN" kernels status "$KAGGLE_KERNEL_ID"
