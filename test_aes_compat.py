# -*- coding: utf-8 -*-
"""aes_compat 与 pycryptodome 的交叉验证测试。

用法（桌面环境装了 pycryptodome 时）：
    python test_aes_compat.py
没装 pycryptodome 时自动跳过比对，只做内部自洽性检查（AES-128 官方测试向量）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aes_compat import AES, pad

# FIPS-197 官方 AES-128 测试向量：key=000102...0f, plaintext=00112233...ff,
# 期望密文 69c4e0d86a7b0430d8cdb78070b4c55a
_OFFICIAL_KEY = bytes(range(16))
_OFFICIAL_PT = bytes.fromhex("00112233445566778899aabbccddeeff")
_OFFICIAL_CT = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")

fails = 0


def check(name, got, expect):
    global fails
    if got != expect:
        print(f"FAIL {name}: got {got.hex() if isinstance(got, bytes) else got!r}")
        fails += 1
    else:
        print(f"OK   {name}")


# ---- 1. 官方测试向量 ----
c = AES.new(_OFFICIAL_KEY, AES.MODE_ECB)
check("FIPS-197 AES-128 vector", c.encrypt(_OFFICIAL_PT), _OFFICIAL_CT)

# ---- 2. PKCS7 padding ----
check("pad 16B block", pad(b"", 16), b"\x10" * 16)
check("pad 15B", pad(b"A" * 15, 16), b"A" * 15 + b"\x01")
check("pad str", pad("hello", 16), b"hello" + b"\x0b" * 11)

# ---- 3. 与 pycryptodome 交叉验证（若已安装）----
try:
    from Crypto.Cipher import AES as RefAES
    from Crypto.Util.Padding import pad as ref_pad
except ImportError:
    print("SKIP pycryptodome 未安装，跳过交叉比对")
    sys.exit(1 if fails else 0)

import random
random.seed(20261022)
for trial in range(200):
    klen = random.choice([16, 24, 32])
    key = bytes(random.randrange(256) for _ in range(klen))
    dlen = random.randrange(0, 200)
    data = bytes(random.randrange(256) for _ in range(dlen))
    ref = RefAES.new(key, RefAES.MODE_ECB).encrypt(ref_pad(data, 16))
    mine = AES.new(key, AES.MODE_ECB).encrypt(pad(data, 16))
    check(f"random trial {trial} (klen={klen}, dlen={dlen})", mine, ref)

print(f"\n{'FAILED: %d' % fails if fails else 'ALL PASSED'}")
sys.exit(1 if fails else 0)
