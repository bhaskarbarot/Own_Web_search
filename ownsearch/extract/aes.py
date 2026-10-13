"""AES-128/192/256 (FIPS-197) in pure Python, CBC mode. Used only to read encrypted PDFs."""


def _xtime(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _gmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _build_sbox():
    inv = [0] * 256
    for a in range(1, 256):
        for b in range(1, 256):
            if _gmul(a, b) == 1:
                inv[a] = b
                break
    sbox = [0] * 256
    for a in range(256):
        x = inv[a]
        s = x
        for i in range(1, 5):
            s ^= ((x << i) | (x >> (8 - i))) & 0xFF
        sbox[a] = s ^ 0x63
    return sbox


SBOX = _build_sbox()
INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i
M2 = [_gmul(i, 2) for i in range(256)]
M3 = [_gmul(i, 3) for i in range(256)]
M9 = [_gmul(i, 9) for i in range(256)]
M11 = [_gmul(i, 11) for i in range(256)]
M13 = [_gmul(i, 13) for i in range(256)]
M14 = [_gmul(i, 14) for i in range(256)]
_SHIFT = [r + 4 * ((c + r) % 4) for c in range(4) for r in range(4)]
_INV_SHIFT = [r + 4 * ((c - r) % 4) for c in range(4) for r in range(4)]


def expand_key(key):
    nk = len(key) // 4
    if nk not in (4, 6, 8):
        raise ValueError("AES key must be 16, 24 or 32 bytes")
    nr = nk + 6
    words = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(words[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]
        words.append([a ^ b for a, b in zip(words[i - nk], t)])
    return [sum(words[4 * r:4 * r + 4], []) for r in range(nr + 1)]


def encrypt_block(block, rk):
    s = [b ^ k for b, k in zip(block, rk[0])]
    nr = len(rk) - 1
    for rnd in range(1, nr + 1):
        s = [SBOX[s[i]] for i in _SHIFT]
        if rnd != nr:
            out = []
            for c in range(0, 16, 4):
                a0, a1, a2, a3 = s[c:c + 4]
                out += [M2[a0] ^ M3[a1] ^ a2 ^ a3, a0 ^ M2[a1] ^ M3[a2] ^ a3,
                        a0 ^ a1 ^ M2[a2] ^ M3[a3], M3[a0] ^ a1 ^ a2 ^ M2[a3]]
            s = out
        s = [b ^ k for b, k in zip(s, rk[rnd])]
    return s


def decrypt_block(block, rk):
    nr = len(rk) - 1
    s = [b ^ k for b, k in zip(block, rk[nr])]
    for rnd in range(nr - 1, -1, -1):
        s = [INV_SBOX[s[i]] for i in _INV_SHIFT]
        s = [b ^ k for b, k in zip(s, rk[rnd])]
        if rnd:
            out = []
            for c in range(0, 16, 4):
                a0, a1, a2, a3 = s[c:c + 4]
                out += [M14[a0] ^ M11[a1] ^ M13[a2] ^ M9[a3], M9[a0] ^ M14[a1] ^ M11[a2] ^ M13[a3],
                        M13[a0] ^ M9[a1] ^ M14[a2] ^ M11[a3], M11[a0] ^ M13[a1] ^ M9[a2] ^ M14[a3]]
            s = out
    return s


def aes_cbc_decrypt(key, data, unpad=True):
    """data = IV (16 bytes) + ciphertext. PKCS#7 padding removed when ``unpad``."""
    rk = expand_key(key)
    iv = list(data[:16])
    out = bytearray()
    for i in range(16, len(data) - len(data) % 16, 16):
        block = list(data[i:i + 16])
        dec = decrypt_block(block, rk)
        out.extend(a ^ b for a, b in zip(dec, iv))
        iv = block
    if unpad and out and 1 <= out[-1] <= 16 and out.endswith(bytes([out[-1]]) * out[-1]):
        del out[-out[-1]:]
    return bytes(out)


def aes_cbc_encrypt(key, iv, data):
    """No padding: ``data`` must be a multiple of 16 bytes."""
    rk = expand_key(key)
    prev = list(iv)
    out = bytearray()
    for i in range(0, len(data), 16):
        block = [a ^ b for a, b in zip(data[i:i + 16], prev)]
        prev = encrypt_block(block, rk)
        out.extend(prev)
    return bytes(out)
