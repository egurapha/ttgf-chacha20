#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Synthesis sanity check for a single module.
#
# Runs Yosys generic synthesis on the named top module (pulling in every file in
# src/ so dependencies resolve) and fails if:
#   * synthesis errors out (non-synthesizable construct, undefined module, ...), or
#   * any latch is inferred (an unintended latch is the classic bug that simulates
#     fine but is wrong hardware).
#
# This is a fast RTL-level gate, NOT the full OpenLane/TT hardening flow — it does
# not check timing or use the PDK. It just confirms the RTL maps to clean
# flip-flop logic.
#
# Usage (from the test/ directory):
#   ./synth_check.sh chacha20_core
#   ./synth_check.sh quarter_round

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <top_module>" >&2
    exit 2
fi
TOP="$1"

# Locate src/ relative to this script (test/ -> ../src).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/../src"

# Use the local OSS-CAD Suite if present (dev machines); otherwise assume yosys is
# already on PATH (e.g. apt-installed in CI).
if [ -f /opt/oss-cad-suite/environment ]; then
    source /opt/oss-cad-suite/environment
fi

# read every source so instantiated submodules resolve; hierarchy -top prunes to
# the target's subtree, so unrelated modules are ignored.
yosys -p "
    read_verilog -sv $SRC_DIR/*.sv;
    hierarchy -top $TOP;
    synth -top $TOP;
    select -assert-none t:\$dlatch t:\$_DLATCH_P_ t:\$_DLATCH_N_;
    stat
"

echo "synth_check: $TOP synthesized cleanly with no inferred latches."
