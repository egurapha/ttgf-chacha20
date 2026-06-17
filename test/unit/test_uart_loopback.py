# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""UART loopback test: uart_tx.tx -> uart_rx.rx.

Sends bytes into the transmitter and checks that the receiver recovers each one
identically — proving uart_rx (synchronizer, mid-bit sampling, framing) against
the already-verified uart_tx over a real serial wire.

Runs at two BAUD_DIVs (a small one for speed, and 434) via two pytest entry
points; BAUD_DIV comes from the environment so the Python pacing matches the DUT.
"""

import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

BAUD_DIV = int(os.getenv("UART_LOOPBACK_BAUD_DIV", "8"))
CLK_PERIOD_NS = 10


async def reset(dut):
    dut.tx_data.value = 0
    dut.tx_send.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def send_tx_byte(dut, value: int):
    """Hand one byte to the transmitter (busy handshake)."""
    while dut.tx_busy.value == 1:
        await RisingEdge(dut.clk)
    dut.tx_data.value = value
    dut.tx_send.value = 1
    await RisingEdge(dut.clk)
    dut.tx_send.value = 0
    while dut.tx_busy.value == 0:  # frame under way
        await RisingEdge(dut.clk)


def rx_collector(dut, sink: list):
    """Background: record rx_data on every rx_valid strobe."""

    async def _run():
        while True:
            await RisingEdge(dut.clk)
            if dut.rx_valid.value == 1:
                sink.append(int(dut.rx_data.value))

    return cocotb.start_soon(_run())


@cocotb.test()
async def loopback_fixed_bytes(dut):
    """A spread of bytes (extremes + bit patterns) survive the round trip."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    received = []
    rx_collector(dut, received)

    sent = [0x00, 0xFF, 0xA5, 0x5A, 0x01, 0x80, 0x7F, 0xC3]
    for v in sent:
        await send_tx_byte(dut, v)

    await ClockCycles(dut.clk, 14 * BAUD_DIV)  # let the last frame drain + decode
    assert received == sent, f"loopback mismatch:\n  sent={sent}\n  got ={received}"


@cocotb.test()
async def loopback_random_stream(dut):
    """A random stream round-trips in order with no drops."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    received = []
    rx_collector(dut, received)

    random.seed(0xBEEF)
    sent = [random.randrange(256) for _ in range(24)]
    for v in sent:
        await send_tx_byte(dut, v)

    await ClockCycles(dut.clk, 14 * BAUD_DIV)
    assert received == sent, f"stream mismatch:\n  sent={sent}\n  got ={received}"


def _run(baud_div: int):
    from cocotb_tools.runner import get_runner

    os.environ["UART_LOOPBACK_BAUD_DIV"] = str(baud_div)

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent  # test/unit
    src = test_dir.parent.parent / "src"  # ../../src
    build_dir = test_dir.parent / "sim_build" / f"uart_loopback_{baud_div}"

    runner = get_runner(sim)
    runner.build(
        sources=[
            test_dir / "tb_uart_loopback.sv",
            src / "uart_tx.sv",
            src / "uart_rx.sv",
        ],
        hdl_toplevel="tb_uart_loopback",
        parameters={"BAUD_DIV": baud_div},
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="tb_uart_loopback",
        test_module="test_uart_loopback",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )


def test_uart_loopback():
    """Full loopback suite at a small BAUD_DIV (fast)."""
    _run(8)


def test_uart_loopback_baud434():
    """Full loopback suite at the real default BAUD_DIV=434."""
    _run(434)
