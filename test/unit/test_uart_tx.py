# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Unit test for the `uart_tx` module.

Checks:
  * Single-byte framing: each transmitted byte decodes back to the value sent,
    proving start bit + 8 data bits (LSB-first) + stop bit are correct.
  * Bit-period timing: the gap between every `tx` transition is exactly
    `BAUD_DIV` cycles. This is the one thing the round-trip cannot prove, since
    the monitor samples using the same `BAUD_DIV` it assumes (an off-by-one in
    the bit period could otherwise slip through).
  * `busy` behaviour: low when idle, high for the whole frame, and a `send`
    pulse asserted mid-frame is ignored (the in-flight byte is unharmed and the
    injected byte is dropped).
  * Random stream: a background receiver recovers every byte of a random stream
    in order, with no drops or merges.

The suite runs twice from two pytest entry points: once at a small `BAUD_DIV`
(fast), and once at the real default 434 (exercises the full-width counter and
the `BAUD_DIV//2` half-period). `BAUD_DIV` is taken from the environment so the
Python timing always matches the value compiled into the DUT.

Run from the test/ directory:
    ./run_unit_tests.sh -k uart_tx
"""

import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Edge, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time

# Bit period (clock cycles) and clock period (ns). BAUD_DIV is read from the
# environment, set by the pytest entry point to match the build parameter.
BAUD_DIV = int(os.getenv("UART_TX_BAUD_DIV", "8"))
CLK_PERIOD_NS = 10


async def reset(dut):
    """Hold reset low for a few cycles, then release. Inputs start de-asserted."""
    dut.send.value = 0
    dut.data.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def send_byte(dut, value: int):
    """Hand one byte to the transmitter, respecting the `busy` handshake.

    Waits for the transmitter to be free, presents `data`, pulses `send` for one
    cycle, then waits for `busy` to assert so the caller knows the frame is under
    way (and a back-to-back call will correctly see `busy` high first).
    """
    while dut.busy.value == 1:  # wait until the previous frame finishes
        await RisingEdge(dut.clk)
    dut.data.value = value
    dut.send.value = 1
    await RisingEdge(dut.clk)  # send is sampled on this edge
    dut.send.value = 0
    while dut.busy.value == 0:  # frame has started
        await RisingEdge(dut.clk)


async def uart_recv(dut) -> int:
    """Recover one byte from the `tx` line — a software UART receiver.

    Locks onto the start-bit falling edge, waits to the centre of bit 0, then
    samples every `BAUD_DIV` cycles, LSB-first. Because it syncs to the real
    edge, the transmitter's one-cycle registered output delay is irrelevant.
    Asserts the stop bit is high (framing check).
    """
    await FallingEdge(dut.tx)  # start bit
    await ClockCycles(dut.clk, BAUD_DIV + BAUD_DIV // 2)  # centre of bit 0
    byte = 0
    for i in range(8):
        byte |= int(dut.tx.value) << i  # sample, LSB-first
        await ClockCycles(dut.clk, BAUD_DIV)
    assert int(dut.tx.value) == 1, "framing error: stop bit was not high"
    return byte


@cocotb.test()
async def single_byte_framing(dut):
    """Each sent byte must decode back identically (start/data-LSB-first/stop)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    # Values chosen to exercise bit ordering and the all-0 / all-1 extremes.
    for value in (0x00, 0xFF, 0xA5, 0x01, 0x80, 0x5A):
        rx = cocotb.start_soon(uart_recv(dut))  # arm the receiver first
        await send_byte(dut, value)
        got = await rx
        assert got == value, f"sent {value:#04x}, received {got:#04x}"


@cocotb.test()
async def bit_period_timing(dut):
    """Every `tx` transition must be exactly BAUD_DIV cycles apart.

    Sending 0x55 yields a fully alternating frame — start(0), data 1,0,1,0,1,0,
    1,0 (LSB-first), stop(1) — so the line is 0,1,0,1,0,1,0,1,0,1 across the ten
    bit slots and toggles at all nine internal boundaries. Measuring the spacing
    of those nine edges checks the bit period directly, independent of any
    assumption baked into the byte-level monitor.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    dut.data.value = 0x55
    dut.send.value = 1
    await RisingEdge(dut.clk)
    dut.send.value = 0

    await FallingEdge(dut.tx)  # falling edge into the start bit
    t_prev = get_sim_time("ns")
    for k in range(9):  # 9 boundaries: start->b0->...->b7->stop
        await Edge(dut.tx)
        t_now = get_sim_time("ns")
        cycles = round((t_now - t_prev) / CLK_PERIOD_NS)
        assert (
            cycles == BAUD_DIV
        ), f"bit-slot boundary {k}: {cycles} cycles, expected {BAUD_DIV}"
        t_prev = t_now


@cocotb.test()
async def busy_and_send_ignored(dut):
    """`busy` covers the whole frame; a mid-frame `send` is ignored."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset(dut)
    assert dut.busy.value == 0, "busy should be low when idle"

    rx = cocotb.start_soon(uart_recv(dut))

    # Send byte A (0xC3).
    dut.data.value = 0xC3
    dut.send.value = 1
    await RisingEdge(dut.clk)
    dut.send.value = 0
    while dut.busy.value == 0:
        await RisingEdge(dut.clk)

    # Mid-frame: busy is still high, and an injected send must be dropped.
    await ClockCycles(dut.clk, 3 * BAUD_DIV)
    assert dut.busy.value == 1, "busy should stay high during the frame"
    dut.data.value = 0x55
    dut.send.value = 1
    await RisingEdge(dut.clk)
    dut.send.value = 0

    # The recovered byte must be A, proving the mid-frame send had no effect.
    got = await rx
    assert got == 0xC3, f"mid-frame send not ignored: received {got:#04x}"

    # The dropped byte started no new frame, so busy returns low and stays low.
    await ClockCycles(dut.clk, 2 * BAUD_DIV)
    assert dut.busy.value == 0, "busy should be low after the frame"

    # Recovery: dropping a mid-frame send must leave the FSM clean, so the next
    # legitimate byte still transmits correctly.
    rx2 = cocotb.start_soon(uart_recv(dut))
    await send_byte(dut, 0x55)
    got2 = await rx2
    assert got2 == 0x55, f"transmitter did not recover after a dropped send: {got2:#04x}"


@cocotb.test()
async def random_stream(dut):
    """A background receiver recovers a random stream in order, no drops."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    received = []

    async def collector():
        while True:
            received.append(await uart_recv(dut))

    cocotb.start_soon(collector())

    random.seed(0x1234)
    sent = [random.randrange(256) for _ in range(16)]
    for value in sent:
        await send_byte(dut, value)

    await ClockCycles(dut.clk, 12 * BAUD_DIV)  # let the final frame drain
    assert received == sent, f"stream mismatch:\n  sent = {sent}\n  got  = {received}"


def _run(baud_div: int):
    """Build `uart_tx` with the given BAUD_DIV and run the cocotb tests.

    The BAUD_DIV is passed both as a Verilog parameter (into the DUT) and via the
    environment (so the Python timing here matches).
    """
    from cocotb_tools.runner import get_runner

    os.environ["UART_TX_BAUD_DIV"] = str(baud_div)

    sim = os.getenv("SIM", "icarus")
    test_dir = Path(__file__).resolve().parent  # test/unit
    src = test_dir.parent.parent / "src"  # ../../src
    build_dir = test_dir.parent / "sim_build" / f"uart_tx_{baud_div}"

    runner = get_runner(sim)
    runner.build(
        sources=[src / "uart_tx.sv"],
        hdl_toplevel="uart_tx",
        parameters={"BAUD_DIV": baud_div},
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="uart_tx",
        test_module="test_uart_tx",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )


def test_uart_tx():
    """Full suite at a small BAUD_DIV (fast)."""
    _run(8)


def test_uart_tx_baud434():
    """Full suite at the real default BAUD_DIV=434 (full-width counter, half-period)."""
    _run(434)
