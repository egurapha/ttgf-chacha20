#!/usr/bin/env bash
#
# Run the cocotb unit test suite for the ChaCha20 project.
#
# Sources the OSS-CAD Suite (for Icarus + cocotb), then runs pytest through
# OSS-CAD's Python so cocotb is importable. Any extra args are passed to pytest.
#
# Usage:
#   ./run_unit_tests.sh                  # run every test_*.py
#   ./run_unit_tests.sh -k quarter_round # only matching tests
#   ./run_unit_tests.sh -x               # stop at first failure
#   ./run_unit_tests.sh test_quarter_round.py

OSS_ENV="/opt/oss-cad-suite/environment"
if [[ -f "$OSS_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$OSS_ENV"
else
    echo "warning: $OSS_ENV not found; relying on the current PATH" >&2
fi

set -euo pipefail

# cd to this script's directory (the test/ folder) so pytest discovers the tests
# regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use OSS-CAD's python: the system `pytest` binary won't see OSS-CAD's cocotb.
exec python3 -m pytest -v "$@"
