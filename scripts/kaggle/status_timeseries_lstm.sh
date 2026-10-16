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

# Load .env if present
load_env

# 1. Parse arguments
KERNEL_ARG=""
if [ $# -gt 0 ]; then
    case "$1" in
        -h|--help)
            echo "Usage: $0 [owner/slug]"
            echo ""
            echo "Checks the status of the time-series packet-clump LSTM Kaggle kernel execution."
            echo ""
            echo "Prerequisites:"
            echo "  1. KAGGLE_KERNEL_ID or KAGGLE_TIMESERIES_KERNEL_ID set via argument, environment, or $SCRIPT_DIR/.env"
            echo "  2. Kaggle CLI installed via scripts/kaggle/bootstrap_cli.sh"
            echo "  3. Kaggle credentials configured (~/.kaggle/kaggle.json, access_token, or env vars)"
            exit 0
            ;;
        -*)
            echo "Error: Unknown option '$1'." >&2
            echo "Usage: $0 [owner/slug]" >&2
            exit 1
            ;;
        *)
            KERNEL_ARG="$1"
            ;;
    esac
fi

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

# 3. Verify virtualenv Kaggle CLI and credentials
KAGGLE_BIN="$VENV_DIR/bin/kaggle"

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
    if ! "$KAGGLE_BIN" kernels list --mine --csv >/dev/null 2>&1; then
        echo "Error: Kaggle credentials absent. Configure ~/.kaggle/kaggle.json, ~/.kaggle/access_token, or export KAGGLE_USERNAME and KAGGLE_KEY." >&2
        exit 1
    fi
fi

# 4. Invoke Kaggle CLI to query kernel status
echo "Querying status for kernel '$KAGGLE_KERNEL_ID'..."
STATUS_EXIT=0
STATUS_OUTPUT="$("$KAGGLE_BIN" kernels status "$KAGGLE_KERNEL_ID" 2>&1)" || STATUS_EXIT=$?

if [ "$STATUS_EXIT" -ne 0 ]; then
    echo "Error: Failed to query status for kernel '$KAGGLE_KERNEL_ID'." >&2
    if [ -n "$STATUS_OUTPUT" ]; then
        echo "$STATUS_OUTPUT" >&2
    fi
    exit 1
fi

echo "$STATUS_OUTPUT"

# Provide contextual next action guidance
case "$STATUS_OUTPUT" in
    *[Cc][Oo][Mm][Pp][Ll][Ee][Tt][Ee]*)
        echo ""
        echo "Kernel execution is complete. To download output artifacts, run:"
        echo "  bash scripts/kaggle/pull_timeseries_outputs.sh $KAGGLE_KERNEL_ID"
        ;;
    *[Rr][Uu][Nn][Nn][Ii][Nn][Gg]*|*[Qq][Uu][Ee][Uu][Ee][Dd]*)
        echo ""
        echo "Kernel is currently in progress. Monitor status with:"
        echo "  bash scripts/kaggle/status_timeseries_lstm.sh $KAGGLE_KERNEL_ID"
        ;;
    *[Ee][Rr][Rr][Oo][Rr]*|*[Ff][Aa][Ii][Ll]*)
        echo ""
        echo "Notice: Kernel execution reported an error or failure." >&2
        ;;
esac
