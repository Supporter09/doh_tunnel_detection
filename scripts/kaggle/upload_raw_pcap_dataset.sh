#!/usr/bin/env bash
# Upload the CIC/UNB raw-PCAP archive as a private Kaggle dataset.
# The Kaggle CLI keeps resumable-upload state in /tmp/.kaggle/uploads, so rerun
# this exact command after a transient network failure; do not remove that state.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
KAGGLE_CLI="$PROJECT_ROOT/.venv-tools/bin/kaggle"
PYTHON_BIN="$PROJECT_ROOT/.venv-tools/bin/python"
PCAP_ZIP="${PCAP_ZIP:-/Volumes/KINGSTON/PCAPs.zip}"
UPLOAD_ROOT="${KAGGLE_PCAP_UPLOAD_ROOT:-$HOME/.local/state/doh-reproduction/kaggle-pcap-upload}"

usage() {
    cat <<'EOF'
Usage:
  bash scripts/kaggle/upload_raw_pcap_dataset.sh

Optional environment variables:
  PCAP_ZIP=<absolute path to PCAPs.zip>
  KAGGLE_DATASET_ID=<owner/dataset-slug>
  KAGGLE_PCAP_UPLOAD_ROOT=<persistent staging directory>

Requirements:
  - Kaggle token at ~/.kaggle/kaggle.json with mode 600.
  - The archive remains mounted and unchanged for the full upload.
  - Run from an interactive terminal. Do not use -q: Kaggle CLI progress stays visible.

Recovery:
  If the network disconnects, run this same command again. The Kaggle CLI stores
  resumable-upload state under /tmp/.kaggle/uploads for up to six days.
EOF
}

if [[ "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ ! -x "$KAGGLE_CLI" || ! -x "$PYTHON_BIN" ]]; then
    echo "Kaggle CLI is unavailable. Run: bash scripts/kaggle/bootstrap_cli.sh" >&2
    exit 1
fi

if [[ ! -f "$PCAP_ZIP" ]]; then
    echo "PCAP archive not found: $PCAP_ZIP" >&2
    exit 1
fi

if [[ ! -f "$HOME/.kaggle/kaggle.json" ]]; then
    echo "Kaggle API token is missing at ~/.kaggle/kaggle.json." >&2
    echo "Create one at https://www.kaggle.com/settings, then move the downloaded kaggle.json there with mode 600." >&2
    exit 1
fi

if [[ "$(stat -f '%Lp' "$HOME/.kaggle/kaggle.json")" != "600" ]]; then
    echo "Refusing insecure Kaggle token permissions; run: chmod 600 ~/.kaggle/kaggle.json" >&2
    exit 1
fi

if ! "$KAGGLE_CLI" datasets list --mine >/dev/null 2>&1; then
    echo "Kaggle authentication failed. Check ~/.kaggle/kaggle.json without printing its contents." >&2
    exit 1
fi

KAGGLE_USERNAME="$($PYTHON_BIN -c 'import json, pathlib; print(json.loads((pathlib.Path.home() / ".kaggle" / "kaggle.json").read_text())["username"])')"
DATASET_ID="${KAGGLE_DATASET_ID:-$KAGGLE_USERNAME/cicdohbrw2020-raw-pcaps}"

if [[ ! "$DATASET_ID" =~ ^[a-z0-9][a-z0-9_-]*/[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "Invalid KAGGLE_DATASET_ID: $DATASET_ID" >&2
    exit 1
fi

if "$KAGGLE_CLI" datasets status "$DATASET_ID" >/dev/null 2>&1; then
    echo "Dataset already exists: $DATASET_ID" >&2
    echo "No new upload was started. Check its processing status with:" >&2
    echo "  $KAGGLE_CLI datasets status $DATASET_ID" >&2
    exit 0
fi

mkdir -p "$UPLOAD_ROOT"
ln -sfn "$PCAP_ZIP" "$UPLOAD_ROOT/PCAPs.zip"

ARCHIVE_BYTES="$(stat -f '%z' "$PCAP_ZIP")"
if (( ARCHIVE_BYTES > 200 * 1024 * 1024 * 1024 )); then
    echo "Archive exceeds Kaggle's 200 GiB per-dataset limit." >&2
    exit 1
fi

cat > "$UPLOAD_ROOT/dataset-metadata.json" <<EOF
{
  "title": "CIRA-CIC-DoHBrw-2020 Raw PCAPs",
  "subtitle": "Private raw PCAP archive for packet-clump replication experiments",
  "description": "Private research copy of the CIRA-CIC-DoHBrw-2020 PCAP archive obtained from the CIC/UNB distribution. Source terms and attribution remain applicable. This dataset is for the team's defensive packet-clump and time-series replication experiments only.",
  "id": "$DATASET_ID",
  "licenses": [{"name": "copyright-authors"}],
  "keywords": ["network-security", "cybersecurity", "network-traffic"]
}
EOF

trap 'echo; echo "Upload interrupted or failed. Keep the archive, staging directory, and /tmp/.kaggle/uploads; rerun this exact command to resume." >&2' ERR INT TERM

echo "Preparing private Kaggle dataset: $DATASET_ID"
echo "Archive: $PCAP_ZIP"
echo "Size: $ARCHIVE_BYTES bytes"
echo "Resumable state: /tmp/.kaggle/uploads"
echo "Starting upload now; leave this terminal and the KINGSTON drive connected."
"$KAGGLE_CLI" datasets create --path "$UPLOAD_ROOT" --keep-tabular --dir-mode skip

echo "Upload completed. Kaggle may still be unpacking the archive server-side."
echo "Monitor processing with:"
echo "  $KAGGLE_CLI datasets status $DATASET_ID"
