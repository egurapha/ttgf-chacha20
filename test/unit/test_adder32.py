# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Unit test for the `adder32` Kogge-Stone parallel-prefix adder.

It must be bit-exact with a plain 32-bit modulo-2^32 add. We hammer carry
propagation specifically (that's the whole point of a hand-written prefix
network) with directed edge cases plus a large random sweep.

Run from the test/ directory:
    ./run_unit_tests.sh -k adder32
"""

import os
import random
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

MASK = 0xFFFFFFFF


async def do_add(dut, a, b):
    dut.a.value = a
    dut.b.value = b
    await Timer(1, unit="ns")  # combinational settle
    return int(dut.sum.value)


def _check(got, a, b):
    exp = (a + b) & MASK
    assert got == exp, f"add32({a:#010x}, {b:#010x}) = {got:#010x}, expected {exp:#010x}"


@cocotb.test()
async def directed_edges(dut):
    """Carry-propagation edge cases that catch prefix-network bugs."""
    cases = [
        (0x00000000, 0x00000000),
        (0x00000000, 0x00000001),
        (0xFFFFFFFF, 0x00000001),   # full carry ripple -> 0 (the classic)
        (0xFFFFFFFF, 0xFFFFFFFF),   # -> 0xFFFFFFFE (overflow/wrap)
        (0x7FFFFFFF, 0x00000001),   # -> 0x80000000 (carry into MSB)
        (0x55555555, 0x55555555),
        (0xAAAAAAAA, 0x55555555),   # -> 0xFFFFFFFF, no carries
        (0x0000FFFF, 0x00000001),   # carry across a half-word boundary
        (0x00FFFFFF, 0x00000001),   # carry across a byte boundary
        (0xFFFFFF00, 0x00000100),
        (0x80000000, 0x80000000),   # MSB + MSB -> 0
    ]
    for a, b in cases:
        _check(await do_add(dut, a, b), a, b)

    # A carry generated at each single bit position (x + x = x<<1).
    for i in range(32):
        a = 1 << i
        _check(await do_add(dut, a, a), a, a)

    # A long carry chain started just below each bit: (2^i - 1) + 1 = 2^i.
    for i in range(1, 33):
        a = (1 << i) - 1
        _check(await do_add(dut, a, 1), a, 1)


@cocotb.test()
async def random_sweep(dut):
    """Many random pairs cross-checked against Python's add."""
    random.seed(0xADDE6332)
    for _ in range(5000):
        a = random.getrandbits(32)
        b = random.getrandbits(32)
        _check(await do_add(dut, a, b), a, b)


def test_adder32():
    """pytest entry point: build adder32 and run the cocotb tests above."""
    from cocotb_tools.runner import get_runner

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent          # test/unit
    src = test_dir.parent.parent / "src"                # ../../src
    build_dir = test_dir.parent / "sim_build" / "adder32"

    runner = get_runner(sim)
    runner.build(
        sources=[src / "adder32.sv"],
        hdl_toplevel="adder32",
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="adder32",
        test_module="test_adder32",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )
