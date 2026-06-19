# chacha20_board.py -- runs ON the demoboard RP2350. Drives the ChaCha20 FPGA
# over the UART interface (MODE = 0) with single-step clocking: each bit is held
# for BAUD_DIV clock ticks, so it is fully deterministic (no real-time baud, no
# timing tuning -- correct on any board).
#
#   prepare()                      -- program the iCE40 bitstream (once; persists)
#   gen(key, nonce, ctr, nbytes)   -> keystream bytes
#   crypt(key, nonce, ctr, data)   -> ciphertext / plaintext bytes (XOR keystream)
#
# gen()/crypt() only drive raw GPIO (no DemoBoard), so they are fast and assume
# prepare() already loaded the design. Driven by the host class in chacha20_fpga.py.

from ttboard.pins.gpio_map_dbv3 import GPIOMapTTDBv3 as G
from ttboard.pins.upython import Pin

NAME = "tt_um_egurapha_chacha20"
BAUD_DIV = 200  # design's top BAUD_DIV (chip baud = project clock / 200)
_P = None  # pin handles, created lazily


def _pins():
    global _P
    p = {}
    p["rx"] = G.get_raw_pin("ui_in3", Pin.OUT)  # chip UART RX (host drives)
    p["tx"] = G.get_raw_pin("uo_out4", Pin.IN)  # chip UART TX (host reads)
    p["busy"] = G.get_raw_pin("uo_out0", Pin.IN)  # BUSY
    p["err"] = G.get_raw_pin("uo_out1", Pin.IN)  # ERR
    p["mode"] = G.get_raw_pin("uio3", Pin.OUT)  # MODE = 0 -> UART
    p["clk"] = G.get_raw_pin("rp_projclk", Pin.OUT)
    p["rst"] = G.get_raw_pin("nprojectrst", Pin.OUT)
    p["mode"](0)
    p["rx"](1)
    p["clk"](0)
    p["rst"](1)
    _P = p


def prepare():
    # Program the iCE40 with our bitstream; it persists in the FPGA after we
    # disconnect, so gen()/crypt() can then run without re-programming.
    from ttboard.boot.demoboard_detect import DemoboardDetect
    from ttboard.demoboard import DemoBoard
    from ttboard.globals import Globals

    DemoboardDetect.probe()
    DemoBoard._DemoBoardSingleton_Instance = None
    Globals.Pins_Singleton = None
    Globals.ProjectMux_Singleton = None
    tt = DemoBoard.get()
    getattr(tt.shuttle, NAME).enable()
    tt.clock_project_stop()
    _pins()
    return "prepared"


def _tick():
    _P["clk"](1)
    _P["clk"](0)


def _step(n):
    c = _P["clk"]
    for _ in range(n):
        c(1)
        c(0)


def _send(b):
    # 8N1 frame: start (0), 8 data bits LSB-first, stop (1); each bit held BAUD_DIV ticks.
    rx = _P["rx"]
    rx(0)
    _step(BAUD_DIV)
    for i in range(8):
        rx((b >> i) & 1)
        _step(BAUD_DIV)
    rx(1)
    _step(BAUD_DIV)


def _recv(timeout=300000):
    tx = _P["tx"]
    c = 0
    while tx():  # wait for start bit (line goes low)
        _tick()
        c += 1
        if c > timeout:
            return None
    _step(BAUD_DIV // 2)  # center in the start bit
    b = 0
    for i in range(8):
        _step(BAUD_DIV)
        b |= (tx() & 1) << i
    _step(BAUD_DIV)  # stop bit
    return b


def _reset():
    _P["mode"](0)
    _P["rx"](1)
    _P["rst"](0)
    _step(6)
    _P["rst"](1)
    _step(3)


def _settle():
    for _ in range(4000):
        if not _P["busy"]():
            return
        _tick()


def _frame(cmd, payload):
    _send(cmd)
    for x in payload:
        _send(x)


def _load(key, nonce, ctr):
    _frame(0x01, key)
    _settle()
    _frame(0x02, nonce)
    _settle()
    _frame(
        0x03,
        bytes([ctr & 0xFF, (ctr >> 8) & 0xFF, (ctr >> 16) & 0xFF, (ctr >> 24) & 0xFF]),
    )
    _settle()


def gen(key, nonce, ctr, nbytes):
    if _P is None:
        _pins()
    nblocks = (nbytes + 63) // 64
    if nblocks > 255:
        raise ValueError("gen: max 255 blocks (16320 bytes) per call")
    _reset()
    _load(key, nonce, ctr)
    _frame(0x04, bytes([nblocks]))
    out = bytearray()
    for _ in range(nblocks * 64):
        v = _recv()
        if v is None:
            break
        out.append(v)
    return bytes(out[:nbytes])


def crypt(key, nonce, ctr, data):
    if _P is None:
        _pins()
    L = len(data)
    if L > 0xFFFF:
        raise ValueError("crypt: max 65535 bytes per call")
    _reset()
    _load(key, nonce, ctr)
    _frame(0x05, bytes([L & 0xFF, (L >> 8) & 0xFF]))
    out = bytearray()
    for p in data:
        _send(p)
        v = _recv()
        if v is None:
            break
        out.append(v)
    return bytes(out)
