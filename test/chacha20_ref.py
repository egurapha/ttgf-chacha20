"""
ChaCha20 Stream Cipher — Reference Implementation
Based on RFC 8439 (https://datatracker.ietf.org/doc/html/rfc8439)

This implementation is meant as a learning tool and reference
for validating a hardware (Verilog) implementation on Tiny Tapeout.
"""

import struct

# ── Utility ──────────────────────────────────────────────────────────


def rotl32(v, n):
    """32-bit left rotate."""
    # shift bits left with wrapping to the right side.
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF


def add32(a, b):
    """32-bit addition (mod 2^32)."""
    # Perform 32 bit addition with wrapping.
    return (a + b) & 0xFFFFFFFF


# ── Quarter Round ────────────────────────────────────────────────────


def quarter_round(state, a, b, c, d):
    """
    The core mixing function of ChaCha20.
    Operates on four 32-bit words in-place within the state array.

    Each quarter round performs:
        a += b;  d ^= a;  d <<<= 16
        c += d;  b ^= c;  b <<<= 12
        a += b;  d ^= a;  d <<<= 8
        c += d;  b ^= c;  b <<<= 7
    """
    # update a.
    state[a] = add32(state[a], state[b])
    state[d] ^= state[a]
    state[d] = rotl32(state[d], 16)

    # update c.
    state[c] = add32(state[c], state[d])
    state[b] ^= state[c]  # b updated.
    state[b] = rotl32(state[b], 12)

    # update a again.
    state[a] = add32(state[a], state[b])
    state[d] ^= state[a]  # d updated.
    state[d] = rotl32(state[d], 8)

    # update c again.
    state[c] = add32(state[c], state[d])
    state[b] ^= state[c]
    state[b] = rotl32(state[b], 7)


# ── ChaCha20 Block Function ─────────────────────────────────────────


def chacha20_block(key, counter, nonce):
    """
    Generate one 64-byte keystream block.

    Args:
        key:     32 bytes (256-bit key)
        counter: integer (32-bit block counter)
        nonce:   12 bytes (96-bit nonce)

    Returns:
        64 bytes of keystream

    The initial state matrix (4x4 of 32-bit words, hexadecimal notation):
        cccccccc  cccccccc  cccccccc  cccccccc
        kkkkkkkk  kkkkkkkk  kkkkkkkk  kkkkkkkk
        kkkkkkkk  kkkkkkkk  kkkkkkkk  kkkkkkkk
        bbbbbbbb  nnnnnnnn  nnnnnnnn  nnnnnnnn

        c = constant ("expand 32-byte k")
        k = key
        b = block counter
        n = nonce
    """
    # Constants: ASCII for "expand 32-byte k" as four little-endian 32-bit words
    constants = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]  # fixed for chacha20.

    # Key: 8 little-endian 32-bit words
    key_words = list(struct.unpack("<8I", key))

    # Nonce: 3 little-endian 32-bit words
    nonce_words = list(struct.unpack("<3I", nonce))

    # Assemble initial state
    state = constants + key_words + [counter] + nonce_words

    # Save the initial state (needed for final addition)
    initial_state = list(state)

    # ── 20 rounds (10 double-rounds) ──
    for _ in range(10):
        # Column rounds
        quarter_round(state, 0, 4, 8, 12)
        quarter_round(state, 1, 5, 9, 13)
        quarter_round(state, 2, 6, 10, 14)
        quarter_round(state, 3, 7, 11, 15)
        # Diagonal rounds
        quarter_round(state, 0, 5, 10, 15)
        quarter_round(state, 1, 6, 11, 12)
        quarter_round(state, 2, 7, 8, 13)
        quarter_round(state, 3, 4, 9, 14)

    # Add initial state to result (mod 2^32 per word)
    # This step makes the algorithm irreversible.
    state = [add32(state[i], initial_state[i]) for i in range(16)]

    # Serialize to 64 bytes (little-endian)
    return struct.pack("<16I", *state)


# ── ChaCha20 Encrypt/Decrypt ────────────────────────────────────────


def chacha20_crypt(key, counter, nonce, data):
    """
    Encrypt or decrypt data using ChaCha20.
    (Encryption and decryption are the same XOR operation.)

    Args:
        key:     32 bytes
        counter: initial block counter (usually 0 or 1)
        nonce:   12 bytes
        data:    plaintext or ciphertext (arbitrary length)

    Returns:
        ciphertext or plaintext (same length as input)
    """
    output = b""
    for i in range(0, len(data), 64):
        # generate pseudorandom bytes.
        keystream = chacha20_block(key, counter + (i // 64), nonce)
        block = data[i : i + 64]
        # XOR each byte of the block with the corresponding keystream byte
        # this operation is still bitwise.
        output += bytes(a ^ b for a, b in zip(block, keystream))
    return output


# ── Pretty Printing ─────────────────────────────────────────────────


def print_state(label, state_bytes):
    """Print a 512-bit state as a 4x4 matrix of hex words."""
    words = struct.unpack("<16I", state_bytes)
    print(f"\n{label}:")
    for row in range(4):
        print("  ", end="")
        for col in range(4):
            print(f"  {words[row*4 + col]:08x}", end="")
        print()


def print_hex(label, data):
    """Print bytes as hex string."""
    print(f"{label}:")
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        print(f"  {hex_str}")


# ── RFC 8439 Test Vectors ───────────────────────────────────────────


def test_quarter_round():
    """RFC 8439 Section 2.1.1 — Quarter Round test."""
    print("=" * 60)
    print("TEST: Quarter Round (RFC 8439 section 2.1.1)")
    print("=" * 60)

    state = [
        0x879531E0,
        0xC5ECF37D,
        0x516461B1,
        0xC9A62F8A,
        0x44C20EF3,
        0x3390AF7F,
        0xD9FC690B,
        0x2A5F714C,
        0x53372767,
        0xB00A5631,
        0x974C541A,
        0x359E9963,
        0x5C971061,
        0x3D631689,
        0x2098D9D6,
        0x91DBD320,
    ]

    quarter_round(state, 2, 7, 8, 13)

    expected = [
        0x879531E0,
        0xC5ECF37D,
        0xBDB886DC,
        0xC9A62F8A,
        0x44C20EF3,
        0x3390AF7F,
        0xD9FC690B,
        0xCFACAFD2,
        0xE46BEA80,
        0xB00A5631,
        0x974C541A,
        0x359E9963,
        0x5C971061,
        0xCCC07C79,
        0x2098D9D6,
        0x91DBD320,
    ]

    if state == expected:
        print("  PASSED ✓")
    else:
        print("  FAILED ✗")
        print(f"  Got:      {[f'{x:08x}' for x in state]}")
        print(f"  Expected: {[f'{x:08x}' for x in expected]}")


def test_chacha20_block():
    """RFC 8439 Section 2.3.2 — Block function test."""
    print("\n" + "=" * 60)
    print("TEST: ChaCha20 Block (RFC 8439 section 2.3.2)")
    print("=" * 60)

    # list of 32 ints, enforced to be 8 bits each = 256 bits for key.
    key = bytes(
        [
            0x00,
            0x01,
            0x02,
            0x03,
            0x04,
            0x05,
            0x06,
            0x07,
            0x08,
            0x09,
            0x0A,
            0x0B,
            0x0C,
            0x0D,
            0x0E,
            0x0F,
            0x10,
            0x11,
            0x12,
            0x13,
            0x14,
            0x15,
            0x16,
            0x17,
            0x18,
            0x19,
            0x1A,
            0x1B,
            0x1C,
            0x1D,
            0x1E,
            0x1F,
        ]
    )
    # 12 bytes = 96 bits.
    nonce = bytes(
        [
            0x00,
            0x00,
            0x00,
            0x09,
            0x00,
            0x00,
            0x00,
            0x4A,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )
    counter = 1

    result = chacha20_block(key, counter, nonce)

    # 64 bytes keystream.
    expected = bytes(
        [
            0x10,
            0xF1,
            0xE7,
            0xE4,
            0xD1,
            0x3B,
            0x59,
            0x15,
            0x50,
            0x0F,
            0xDD,
            0x1F,
            0xA3,
            0x20,
            0x71,
            0xC4,
            0xC7,
            0xD1,
            0xF4,
            0xC7,
            0x33,
            0xC0,
            0x68,
            0x03,
            0x04,
            0x22,
            0xAA,
            0x9A,
            0xC3,
            0xD4,
            0x6C,
            0x4E,
            0xD2,
            0x82,
            0x64,
            0x46,
            0x07,
            0x9F,
            0xAA,
            0x09,
            0x14,
            0xC2,
            0xD7,
            0x05,
            0xD9,
            0x8B,
            0x02,
            0xA2,
            0xB5,
            0x12,
            0x9C,
            0xD1,
            0xDE,
            0x16,
            0x4E,
            0xB9,
            0xCB,
            0xD0,
            0x83,
            0xE8,
            0xA2,
            0x50,
            0x3C,
            0x4E,
        ]
    )

    print_state("Output keystream block", result)

    if result == expected:
        print("\n  PASSED ✓")
    else:
        print("\n  FAILED ✗")
        print_hex("  Got", result)
        print_hex("  Expected", expected)


def test_chacha20_encryption():
    """RFC 8439 Section 2.4.2 — Encryption test."""
    print("\n" + "=" * 60)
    print("TEST: ChaCha20 Encryption (RFC 8439 section 2.4.2)")
    print("=" * 60)

    # 32 bytes.
    key = bytes(
        [
            0x00,
            0x01,
            0x02,
            0x03,
            0x04,
            0x05,
            0x06,
            0x07,
            0x08,
            0x09,
            0x0A,
            0x0B,
            0x0C,
            0x0D,
            0x0E,
            0x0F,
            0x10,
            0x11,
            0x12,
            0x13,
            0x14,
            0x15,
            0x16,
            0x17,
            0x18,
            0x19,
            0x1A,
            0x1B,
            0x1C,
            0x1D,
            0x1E,
            0x1F,
        ]
    )

    # 12 bytes.
    nonce = bytes(
        [
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x4A,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )
    counter = 1

    plaintext = (
        b"Ladies and Gentlemen of the class of '99: "
        b"If I could offer you only one tip for the future, "
        b"sunscreen would be it."
    )

    # output length is the same length as the input.
    expected_ciphertext = bytes(
        [
            0x6E,
            0x2E,
            0x35,
            0x9A,
            0x25,
            0x68,
            0xF9,
            0x80,
            0x41,
            0xBA,
            0x07,
            0x28,
            0xDD,
            0x0D,
            0x69,
            0x81,
            0xE9,
            0x7E,
            0x7A,
            0xEC,
            0x1D,
            0x43,
            0x60,
            0xC2,
            0x0A,
            0x27,
            0xAF,
            0xCC,
            0xFD,
            0x9F,
            0xAE,
            0x0B,
            0xF9,
            0x1B,
            0x65,
            0xC5,
            0x52,
            0x47,
            0x33,
            0xAB,
            0x8F,
            0x59,
            0x3D,
            0xAB,
            0xCD,
            0x62,
            0xB3,
            0x57,
            0x16,
            0x39,
            0xD6,
            0x24,
            0xE6,
            0x51,
            0x52,
            0xAB,
            0x8F,
            0x53,
            0x0C,
            0x35,
            0x9F,
            0x08,
            0x61,
            0xD8,
            0x07,
            0xCA,
            0x0D,
            0xBF,
            0x50,
            0x0D,
            0x6A,
            0x61,
            0x56,
            0xA3,
            0x8E,
            0x08,
            0x8A,
            0x22,
            0xB6,
            0x5E,
            0x52,
            0xBC,
            0x51,
            0x4D,
            0x16,
            0xCC,
            0xF8,
            0x06,
            0x81,
            0x8C,
            0xE9,
            0x1A,
            0xB7,
            0x79,
            0x37,
            0x36,
            0x5A,
            0xF9,
            0x0B,
            0xBF,
            0x74,
            0xA3,
            0x5B,
            0xE6,
            0xB4,
            0x0B,
            0x8E,
            0xED,
            0xF2,
            0x78,
            0x5E,
            0x42,
            0x87,
            0x4D,
        ]
    )

    ciphertext = chacha20_crypt(key, counter, nonce, plaintext)

    print(f'\n  Plaintext:  "{plaintext.decode()}"')
    print_hex("\n  Ciphertext", ciphertext)

    if ciphertext == expected_ciphertext:
        print("\n  PASSED ✓")
    else:
        print("\n  FAILED ✗")

    # Verify decryption (same operation)
    decrypted = chacha20_crypt(key, counter, nonce, ciphertext)
    if decrypted == plaintext:
        print("  Decrypt:  PASSED ✓")
    else:
        print("  Decrypt:  FAILED ✗")


# ── Run Everything ──────────────────────────────────────────────────

if __name__ == "__main__":
    test_quarter_round()
    test_chacha20_block()
    test_chacha20_encryption()

    print("\n" + "=" * 60)
    print("All RFC 8439 test vectors validated.")
    print("=" * 60)
