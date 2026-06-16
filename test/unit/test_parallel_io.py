# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Unit test for the `parallel_io` front-end.

Verifies the parallel byte interface in isolation (no core/controller):
  * Input  — a byte on `pdata_in` is captured on the `wr` strobe and presented
    on rx_data/rx_valid (the same contract uart_rx gives the controller).
  * Bubbles — gaps (wr low) between bytes are tolerated; only wr=1 cycles count.
  * Output — on tx_send the byte is driven on pdata_out and `valid`/`tx_busy`
    are held for exactly (hold_sel + 1) cycles, for each hold_sel 0..3.

Run from the test/ directory:
    ./run_unit_tests.sh -k parallel_io
"""

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer


async def reset(dut):
    dut.pdata_in.value = 0
    dut.wr.value = 0
    dut.hold_sel.value = 0
    dut.tx_data.value = 0
    dut.tx_send.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def send_byte(dut, value):
    """Drive one byte in with a single-cycle wr strobe."""
    dut.pdata_in.value = value
    dut.wr.value = 1
    await RisingEdge(dut.clk)   # byte captured on this edge
    dut.wr.value = 0
    dut.pdata_in.value = 0      # prove the capture latched, not a passthrough


@cocotb.test()
async def rx_capture_and_bubbles(dut):
    """Input bytes are captured on wr; gaps between strobes are ignored."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    for value, gap in [(0xA5, 0), (0x3C, 3), (0xFF, 1), (0x00, 2)]:
        await send_byte(dut, value)
        await Timer(1, unit="ns")
        assert int(dut.rx_valid.value) == 1, f"rx_valid not set for {value:#04x}"
        assert int(dut.rx_data.value) == value, (
            f"rx_data={int(dut.rx_data.value):#04x} expected {value:#04x}")

        # The bubble: wr stays low for `gap` cycles -> no spurious rx_valid.
        for _ in range(gap):
            await RisingEdge(dut.clk)
            await Timer(1, unit="ns")
            assert int(dut.rx_valid.value) == 0, "rx_valid pulsed during a bubble"


@cocotb.test()
async def tx_hold_window(dut):
    """On tx_send the byte is held with valid/tx_busy for (hold_sel + 1) cycles."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    for hsel in range(4):                 # hold_sel 0..3 -> hold 1..4 cycles
        dut.hold_sel.value = hsel
        dut.tx_data.value = 0x3C
        dut.tx_send.value = 1
        await RisingEdge(dut.clk)          # parallel_io accepts the byte here
        dut.tx_send.value = 0
        dut.tx_data.value = 0

        high = 0
        await Timer(1, unit="ns")
        while int(dut.valid.value) == 1 and high < 8:
            high += 1
            assert int(dut.pdata_out.value) == 0x3C, "wrong byte on pdata_out"
            assert int(dut.tx_busy.value) == 1, "tx_busy low while holding"
            await RisingEdge(dut.clk)
            await Timer(1, unit="ns")

        assert high == hsel + 1, (
            f"hold_sel={hsel}: valid held {high} cycles, expected {hsel + 1}")
        assert int(dut.tx_busy.value) == 0, "tx_busy stuck after hold"

        await ClockCycles(dut.clk, 2)     # settle back to idle before next case


def test_parallel_io():
    """pytest entry point: build parallel_io and run the cocotb tests above."""
    from cocotb_tools.runner import get_runner

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent
    src = test_dir.parent.parent / "src"
    build_dir = test_dir.parent / "sim_build" / "parallel_io"

    runner = get_runner(sim)
    runner.build(
        sources=[src / "parallel_io.sv"],
        hdl_toplevel="parallel_io",
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="parallel_io",
        test_module="test_parallel_io",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )
