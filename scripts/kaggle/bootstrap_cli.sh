#!/bin/sh
set -eu

# Discover paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv-tools"

# 1. Prerequisite check: python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but was not found in PATH." >&2
    echo "Please install Python 3.9+ and ensure python3 is available in your PATH." >&2
    exit 1
fi

# 2. Create virtual environment if missing
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# 3. Ensure .venv-tools is ignored by Git
if [ ! -f "$VENV_DIR/.gitignore" ]; then
    printf "*\n" > "$VENV_DIR/.gitignore"
fi

# 4. Install or upgrade only kaggle
echo "Installing/upgrading kaggle in $VENV_DIR..."
"$VENV_DIR/bin/python" -m pip install --upgrade kaggle

# 5. Verify kaggle CLI executable
if [ ! -x "$VENV_DIR/bin/kaggle" ]; then
    echo "Error: Kaggle CLI executable not found at $VENV_DIR/bin/kaggle after installation." >&2
    exit 1
fi

echo "Kaggle CLI successfully bootstrapped:"
"$VENV_DIR/bin/kaggle" --version
echo ""
echo "Security note:"
echo "  Do not commit Kaggle API tokens to git."
echo "  Configure credentials at ~/.kaggle/kaggle.json (chmod 600) or via 'kaggle auth login'."
