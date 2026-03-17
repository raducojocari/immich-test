#!/usr/bin/env bash
# run_tests.sh - Runs the full Immich script test suite.
# Installs bats-core automatically if not already present.

set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATS_INSTALL_DIR="${TESTS_DIR}/.bats-core"

# ---------------------------------------------------------------------------
# Resolve bats binary
# ---------------------------------------------------------------------------
find_or_install_bats() {
    if command -v bats >/dev/null 2>&1; then
        echo "bats"
        return
    fi

    if [[ -x "${BATS_INSTALL_DIR}/bin/bats" ]]; then
        echo "${BATS_INSTALL_DIR}/bin/bats"
        return
    fi

    echo "[INFO]  bats not found. Attempting to install via Homebrew..." >&2
    if command -v brew >/dev/null 2>&1; then
        brew install bats-core >&2
        echo "bats"
        return
    fi

    echo "[INFO]  Homebrew not available. Cloning bats-core locally..." >&2
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 https://github.com/bats-core/bats-core.git "${BATS_INSTALL_DIR}" >&2
        echo "${BATS_INSTALL_DIR}/bin/bats"
        return
    fi

    echo "[ERROR] Cannot install bats-core. Please install it manually:" >&2
    echo "          brew install bats-core" >&2
    echo "        Or visit: https://bats-core.readthedocs.io/en/stable/installation.html" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------
BATS="$(find_or_install_bats)"

echo "=== Immich Script Test Suite ==="
echo "Using bats: ${BATS}"
echo ""

"${BATS}" \
    --print-output-on-failure \
    "${TESTS_DIR}/test_install.bats" \
    "${TESTS_DIR}/test_start.bats" \
    "${TESTS_DIR}/test_stop.bats" \
    "${TESTS_DIR}/test_reset.bats"

echo ""
echo "=== Python import tests ==="
python3 -m pytest "${TESTS_DIR}/test_import.py" -v
