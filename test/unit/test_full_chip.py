# SPDX-FileCopyrightText: © 2026 Raphael Eguchi
# SPDX-License-Identifier: Apache-2.0
"""Full-chip serial sign-off over the real UART pins.

Drives ONLY the real TT pins of tt_um_egurapha_chacha20 — RX on ui_in[3], TX on
uo_out[4] — through a bit-level serial driver and monitor. This exercises the
complete chain end to end: pin -> uart_rx -> chacha20_controller -> chacha20_core
-> uart_tx -> pin, including the pin mapping itself.

Scoreboarded against chacha20_ref. Built with a small BAUD_DIV (the top is
parameterised) so a real-serial test runs quickly; the silicon default is 200.

Run from the test/ directory:
    ./run_unit_tests.sh -k full_chip
"""

import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

import chacha20_ref

BAUD_DIV = int(os.getenv("FULL_CHIP_BAUD_DIV", "16"))  # >8.4 so a byte never lands mid-block (pipelined core ~84 cyc)
CLK_PERIOD_NS = 10

RX_BIT = 3  # ui_in[3]
TX_BIT = 4  # uo_out[4]

CMD_LOAD_KEY = 0x01
CMD_LOAD_NONCE = 0x02
CMD_LOAD_CTR = 0x03
CMD_GEN = 0x04
CMD_CRYPT = 0x05


def _tx(dut) -> int:
    """Current level of the TX pin (uo_out[4])."""
    return (int(dut.uo_out.value) >> TX_BIT) & 1


async def reset(dut):
    dut.ui_in.value = 1 << RX_BIT  # RX idles high
    dut.uio_in.value = 0
    dut.ena.value = 1
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def serial_send_byte(dut, value: int):
    """Shift one byte onto RX (ui_in[3]) at BAUD_DIV: start, 8 data LSB-first, stop."""
    # start bit (0)
    dut.ui_in.value = 0
    await ClockCycles(dut.clk, BAUD_DIV)
    # 8 data bits, LSB-first
    for i in range(8):
        dut.ui_in.value = ((value >> i) & 1) << RX_BIT
        await ClockCycles(dut.clk, BAUD_DIV)
    # stop bit (1) -> back to idle high
    dut.ui_in.value = 1 << RX_BIT
    await ClockCycles(dut.clk, BAUD_DIV)


async def serial_send_frame(dut, cmd: int, payload: bytes):
    await serial_send_byte(dut, cmd)
    for b in payload:
        await serial_send_byte(dut, b)


def tx_monitor(dut, sink: list):
    """Background serial receiver on TX (uo_out[4]); appends decoded bytes."""

    async def _run():
        while True:
            # wait for a start bit (line idles high, drops to 0)
            while _tx(dut) == 1:
                await RisingEdge(dut.clk)
            # advance to the centre of bit 0
            await ClockCycles(dut.clk, BAUD_DIV + BAUD_DIV // 2)
            byte = 0
            for i in range(8):
                byte |= _tx(dut) << i
                await ClockCycles(dut.clk, BAUD_DIV)
            sink.append(byte)
            # now in the stop bit; the top-of-loop wait skips to the next start

    return cocotb.start_soon(_run())


async def load_config_serial(dut, key: bytes, counter: int, nonce: bytes):
    await serial_send_frame(dut, CMD_LOAD_KEY, key)
    await serial_send_frame(dut, CMD_LOAD_NONCE, nonce)
    await serial_send_frame(dut, CMD_LOAD_CTR, counter.to_bytes(4, "little"))


async def wait_for(dut, sink, n, timeout_cycles):
    waited = 0
    while len(sink) < n and waited < timeout_cycles:
        await RisingEdge(dut.clk)
        waited += 1
    await ClockCycles(dut.clk, BAUD_DIV)


@cocotb.test()
async def full_chip_gen(dut):
    """Keystream end-to-end: framed LOAD_* + GEN over RX; decode TX vs reference."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    key = bytes(range(32))
    nonce = bytes(range(12))
    counter = 1

    received = []
    tx_monitor(dut, received)

    await load_config_serial(dut, key, counter, nonce)
    await serial_send_frame(dut, CMD_GEN, bytes([1]))

    await wait_for(dut, received, 64, 200_000)
    exp = chacha20_ref.chacha20_block(key, counter, nonce)
    assert bytes(received) == exp, (
        f"full-chip GEN mismatch:\n  got={bytes(received).hex()}\n  exp={exp.hex()}"
    )


@cocotb.test()
async def full_chip_crypt_roundtrip(dut):
    """Encrypt a message over the wire, then decrypt the ciphertext back to plaintext."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset(dut)

    key = bytes((i ^ 0x33) & 0xFF for i in range(32))
    nonce = bytes((i + 1) & 0xFF for i in range(12))
    counter = 0x40
    random.seed(0x5151)
    plaintext = bytes(random.randrange(256) for _ in range(24))
    L = len(plaintext)

    # --- encrypt pass ---
    ct = []
    mon = tx_monitor(dut, ct)
    await load_config_serial(dut, key, counter, nonce)
    await serial_send_frame(dut, CMD_CRYPT, L.to_bytes(2, "little") + plaintext)
    await wait_for(dut, ct, L, 200_000)
    mon.kill()

    exp_ct = chacha20_ref.chacha20_crypt(key, counter, nonce, plaintext)
    assert bytes(ct) == exp_ct, (
        f"full-chip encrypt mismatch:\n  got={bytes(ct).hex()}\n  exp={exp_ct.hex()}"
    )

    # --- decrypt pass: feed ciphertext back with the same key/nonce/counter ---
    await reset(dut)
    pt = []
    tx_monitor(dut, pt)
    await load_config_serial(dut, key, counter, nonce)
    await serial_send_frame(dut, CMD_CRYPT, L.to_bytes(2, "little") + bytes(ct))
    await wait_for(dut, pt, L, 200_000)

    assert bytes(pt) == plaintext, (
        f"full-chip decrypt round-trip failed:\n"
        f"  pt ={plaintext.hex()}\n  got={bytes(pt).hex()}"
    )


def test_full_chip():
    """pytest entry point: build the full chip (small BAUD_DIV) and run the cocotb tests."""
    from cocotb_tools.runner import get_runner

    sim = os.getenv("SIM", "icarus")
    os.environ["FULL_CHIP_BAUD_DIV"] = str(BAUD_DIV)

    test_dir = Path(__file__).resolve().parent  # test/unit
    src = test_dir.parent.parent / "src"
    build_dir = test_dir.parent / "sim_build" / f"full_chip_{BAUD_DIV}"

    runner = get_runner(sim)
    runner.build(
        sources=[
            src / "tt_um_egurapha_chacha20.sv",
            src / "chacha20_controller.sv",
            src / "chacha20_core.sv",
            src / "quarter_round.sv",
            src / "adder32.sv",
            src / "uart_rx.sv",
            src / "uart_tx.sv",
            src / "parallel_io.sv",
        ],
        hdl_toplevel="tt_um_egurapha_chacha20",
        parameters={"BAUD_DIV": BAUD_DIV},
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    runner.test(
        hdl_toplevel="tt_um_egurapha_chacha20",
        test_module="test_full_chip",
        test_dir=test_dir,
        build_dir=build_dir,
        results_xml=str(build_dir / "results.xml"),
        timescale=("1ns", "1ps"),
    )
