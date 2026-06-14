# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Unit test for the `quarter_round` module.

Two checks:
  * RFC 8439 section 2.1.1 single quarter-round vector (independent reference values).
  * Random cross-check against the Python reference (chacha20_ref.py).

`chacha20_ref` is made importable by test/conftest.py.

Run from the test/ directory:
    ./run_unit_tests.sh -k quarter_round
"""

import os
import random
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

import chacha20_ref


def ref_quarter_round(a, b, c, d):
    """Reference quarter round on four isolated 32-bit words."""
    state = [a, b, c, d]
    chacha20_ref.quarter_round(state, 0, 1, 2, 3)  # mutates state in place
    return tuple(state)


async def run_qr(dut, a, b, c, d):
    """Compose the 4 staged sub-ops into a full quarter-round.

    `quarter_round` is now pipelined into 4 stages (one ARX op each), selected by
    `stage`. The module is still combinational per stage, so a full quarter-round
    is reconstructed by feeding each stage's output back in as the next stage's
    input, for stage = 0, 1, 2, 3. The composed result equals the original
    one-shot quarter-round, so the RFC / reference checks below are unchanged.
    """
    vals = (a, b, c, d)
    for st in range(4):
        dut.stage.value = st
        dut.a_in.value, dut.b_in.value, dut.c_in.value, dut.d_in.value = vals
        await Timer(1, unit="ns")
        vals = (
            int(dut.a_out.value),
            int(dut.b_out.value),
            int(dut.c_out.value),
            int(dut.d_out.value),
        )
    return vals


@cocotb.test()
async def rfc_2_1_1_vector(dut):
    """RFC 8439 section 2.1.1 single quarter-round test vector."""
    got = await run_qr(dut, 0x11111111, 0x01020304, 0x9B8D6F43, 0x01234567)
    exp = (0xEA2A92F4, 0xCB1CF8CE, 0x4581472E, 0x5881C4BB)
    assert got == exp, (
        "RFC section 2.1.1 mismatch:\n"
        f"  got = {[hex(x) for x in got]}\n"
        f"  exp = {[hex(x) for x in exp]}"
    )


@cocotb.test()
async def random_vectors(dut):
    """Cross-check many random inputs against the reference."""
    random.seed(0xC0FFEE)
    for _ in range(2000):
        a, b, c, d = (random.getrandbits(32) for _ in range(4))
        got = await run_qr(dut, a, b, c, d)
        exp = ref_quarter_round(a, b, c, d)
        assert got == exp, (
            f"mismatch for inputs {[hex(a), hex(b), hex(c), hex(d)]}:\n"
            f"  got = {[hex(x) for x in got]}\n"
            f"  exp = {[hex(x) for x in exp]}"
        )


def test_quarter_round():
    """pytest entry point: build the module and run the cocotb tests above."""
    from cocotb_tools.runner import get_runner

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent          # test/unit
    src = test_dir.parent.parent / "src"                # ../../src
    build_dir = test_dir.parent / "sim_build" / "quarter_round"  # gitignored

    runner = get_runner(sim)
    runner.build(
        sources=[src / "quarter_round.sv"],
        hdl_toplevel="quarter_round",
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="quarter_round",
        test_module="test_quarter_round",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),  # keep xml out of test/unit
        timescale=("1ns", "1ps"),
    )
