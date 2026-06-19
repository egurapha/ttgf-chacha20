# fpga_test_suite.py -- full functional suite for the ChaCha20 design on the TT FPGA
# breakout (FabricFox iCE40). Runs ON the demoboard RP2350 via `mpremote run`.
#
# Tests BOTH host interfaces (parallel byte bus and UART) with the SAME set of
# protocol-level cases, all checked against the repo's reference model
# (chacha20_ref.py, copied to the board by fpga_test.sh) -- one source of truth,
# shared with the cocotb suite.
#
# Everything is driven by single-stepping the project clock, so both interfaces
# are fully deterministic (a UART bit is just "hold the line for BAUD_DIV ticks").
#
# Vector (matches test/test.py): key=00..1f, nonce=00..0b, counter=1.

import sys
sys.path.insert(0, '/lib')
sys.path.insert(0, '/')
import chacha20_ref

from ttboard.boot.demoboard_detect import DemoboardDetect, DemoboardCarrier
from ttboard.demoboard import DemoBoard
from ttboard.globals import Globals
from ttboard.pins.gpio_map_dbv3 import GPIOMapTTDBv3 as G
from ttboard.pins.upython import Pin

NAME    = 'tt_um_egurapha_chacha20'
KEY     = bytes(range(32))
NONCE   = bytes(range(12))
COUNTER = 1
CTR_LE  = (COUNTER).to_bytes(4, 'little')
BAUD_DIV = 200            # must match the design's top BAUD_DIV (clock/200)

# ---- Bring the board up in FPGA mode and program the bitstream ----
DemoboardDetect.probe()
DemoBoard._DemoBoardSingleton_Instance = None
Globals.Pins_Singleton = None
Globals.ProjectMux_Singleton = None
tt = DemoBoard.get()
getattr(tt.shuttle, NAME).enable()
tt.clock_project_stop()
print('programmed:', tt.shuttle.enabled, ' carrier:', DemoboardDetect.CarrierVersion)

# ---- Raw pins, explicit directions (drive inputs, read outputs) ----
ui   = [G.get_raw_pin('ui_in%d'  % i, Pin.OUT) for i in range(8)]
uo   = [G.get_raw_pin('uo_out%d' % i, Pin.IN)  for i in range(8)]
wr   = G.get_raw_pin('uio0', Pin.OUT)   # parallel WR
modep= G.get_raw_pin('uio3', Pin.OUT)   # MODE (0=UART, 1=parallel)
h0   = G.get_raw_pin('uio4', Pin.OUT)   # HOLD_SEL[0]
h1   = G.get_raw_pin('uio5', Pin.OUT)   # HOLD_SEL[1]
pvld = G.get_raw_pin('uio1', Pin.IN)    # parallel VALID
pbsy = G.get_raw_pin('uio2', Pin.IN)    # parallel BUSY
perr = G.get_raw_pin('uio6', Pin.IN)    # parallel ERR
clk  = G.get_raw_pin('rp_projclk',  Pin.OUT)
rstn = G.get_raw_pin('nprojectrst', Pin.OUT)
clk(0); rstn(1)

def tick():
    clk(1); clk(0)

def step(n):
    for _ in range(n):
        clk(1); clk(0)

def drive_ui(b):
    for i in range(8):
        ui[i]((b >> i) & 1)

def read_uo():
    v = 0
    for i in range(8):
        v |= (uo[i]() & 1) << i
    return v

# ---- Two transports, same interface to the protocol layer ----
class ParallelLink:
    name = 'PAR'
    TO = 20000
    def reset(self):
        modep(1); h0(0); h1(0); wr(0); drive_ui(0)
        rstn(0); step(6); rstn(1); step(3)
    def busy(self): return pbsy()
    def err(self):  return perr()
    def send_byte(self, b):
        drive_ui(b)
        wr(1); tick()      # WR high one cycle -> byte latched
        wr(0); tick()      # rx_valid pulses -> controller consumes
    def recv_byte(self, timeout):
        c = 0
        while not pvld():           # wait for VALID
            tick(); c += 1
            if c > timeout: return None
        b = read_uo()
        c = 0
        while pvld():               # consume the hold window
            tick(); c += 1
            if c > timeout: return None
        return b

class UartLink:
    name = 'UART'
    TO = 200000
    def reset(self):
        modep(0); wr(0); drive_ui(0); ui[3](1)   # RX (ui[3]) idle high
        rstn(0); step(6); rstn(1); step(3)
    def busy(self): return uo[0]()    # UART mode: BUSY = uo_out[0]
    def err(self):  return uo[1]()    # UART mode: ERR  = uo_out[1]
    def send_byte(self, b):
        ui[3](0); step(BAUD_DIV)                  # start bit
        for i in range(8):
            ui[3]((b >> i) & 1); step(BAUD_DIV)   # 8 data bits, LSB first
        ui[3](1); step(BAUD_DIV)                  # stop bit (idle high)
    def recv_byte(self, timeout):
        c = 0
        while uo[4]():                # wait for TX (uo[4]) start bit (line low)
            tick(); c += 1
            if c > timeout: return None
        step(BAUD_DIV // 2)           # center in the start bit
        b = 0
        for i in range(8):
            step(BAUD_DIV)
            b |= (uo[4]() & 1) << i
        step(BAUD_DIV)               # stop bit
        return b

# ---- Protocol layer (transport-agnostic) ----
def send_frame(link, cmd, payload=b''):
    link.send_byte(cmd)
    for x in payload:
        link.send_byte(x)

def settle(link):
    for _ in range(link.TO):
        if not link.busy():
            return
        tick()

def load_all(link):
    send_frame(link, 0x01, KEY);    settle(link)
    send_frame(link, 0x02, NONCE);  settle(link)
    send_frame(link, 0x03, CTR_LE); settle(link)

def do_gen(link, nblocks):
    load_all(link)
    send_frame(link, 0x04, bytes([nblocks]))
    out = bytearray()
    for _ in range(nblocks * 64):
        b = link.recv_byte(link.TO)
        if b is None:
            break
        out.append(b)
    exp = b''.join(chacha20_ref.chacha20_block(KEY, COUNTER + i, NONCE) for i in range(nblocks))
    return bytes(out), exp

def do_crypt(link, pt):
    load_all(link)
    L = len(pt)
    link.send_byte(0x05)
    link.send_byte(L & 0xff)
    link.send_byte((L >> 8) & 0xff)
    ct = bytearray()
    for p in pt:                         # send one plaintext byte, read one out
        link.send_byte(p)
        b = link.recv_byte(link.TO)
        if b is None:
            break
        ct.append(b)
    exp = chacha20_ref.chacha20_crypt(KEY, COUNTER, NONCE, pt)
    return bytes(ct), exp

# ---- Runner ----
PASS = 0
FAIL = 0
def check(iface, name, got, exp):
    global PASS, FAIL
    ok = got == exp
    PASS += ok
    FAIL += (not ok)
    print('  [%-4s] %-26s %s' % (iface, name, 'PASS' if ok else 'FAIL'))
    if not ok:
        g = got.hex() if isinstance(got, (bytes, bytearray)) else got
        e = exp.hex() if isinstance(exp, (bytes, bytearray)) else exp
        print('         got:', g)
        print('         exp:', e)

PT40  = bytes((i * 7 + 3) & 0xff for i in range(40))
PT100 = bytes((i * 5 + 1) & 0xff for i in range(100))

for link in (ParallelLink(), UartLink()):
    n = link.name
    print('==== interface:', n, '====')

    link.reset(); g, e = do_gen(link, 1); check(n, 'GEN x1', g, e)
    link.reset(); g, e = do_gen(link, 2); check(n, 'GEN x2 (multiblock)', g, e)
    link.reset(); g, e = do_crypt(link, PT40); check(n, 'CRYPT 40B', g, e)

    link.reset(); ct, _ = do_crypt(link, PT40)
    link.reset(); rt, _ = do_crypt(link, ct)
    check(n, 'CRYPT roundtrip 40B', rt, PT40)

    link.reset(); link.send_byte(0xEE); step(40)
    check(n, 'ERR on bad command', link.err(), 1)

    if n == 'PAR':   # bigger multiblock CRYPT (kept off UART for runtime)
        link.reset(); g, e = do_crypt(link, PT100); check(n, 'CRYPT 100B (multiblock)', g, e)

print()
print('SUITE RESULT: %s   (%d passed, %d failed)' % ('PASS' if FAIL == 0 else 'FAIL', PASS, FAIL))
