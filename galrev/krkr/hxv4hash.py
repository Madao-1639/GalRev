"""Hxv4 名字层：``file_hash`` / ``domain_hash``（纯标准库，SipHash-2-4 + BLAKE2s）。

    file_hash(name, salt)       = BLAKE2s-256( UTF16LE(小写名字) + UTF16LE(盐) )
    domain_hash(directory,salt) = SipHash-2-4( UTF16LE(小写目录 + 盐), key = 16 个 0 字节 )

目录必须**小写、带结尾 "/"**；根目录传空串（此时只哈希盐）。
盐不是固定值，来自映射表里的 ``HashDomain`` 字段；``DEFAULT_SALT`` 只是语料观测值，
换作必须由调用方注入（见 docs/engines/krkr/hxv4-crypto.md §7）。
"""
DEFAULT_SALT = "xp3hnp"   # 语料观测值，【跨作需重验】
MASK = (1 << 64) - 1

def _rotl(x, b):
    return ((x << b) | (x >> (64 - b))) & MASK

class SipHash24:
    def __init__(self, key: bytes, c_rounds=2, d_rounds=4):
        assert len(key) == 16
        k0 = int.from_bytes(key[0:8], "little")
        k1 = int.from_bytes(key[8:16], "little")
        self.v0 = 0x736f6d6570736575 ^ k0
        self.v1 = 0x646f72616e646f6d ^ k1
        self.v2 = 0x6c7967656e657261 ^ k0
        self.v3 = 0x7465646279746573 ^ k1
        self.buf = b""
        self.length = 0
        self.c, self.d = c_rounds, d_rounds

    def _round(self):
        v0, v1, v2, v3 = self.v0, self.v1, self.v2, self.v3
        v0 = (v0 + v1) & MASK; v1 = _rotl(v1, 13); v1 ^= v0; v0 = _rotl(v0, 32)
        v2 = (v2 + v3) & MASK; v3 = _rotl(v3, 16); v3 ^= v2
        v0 = (v0 + v3) & MASK; v3 = _rotl(v3, 21); v3 ^= v0
        v2 = (v2 + v1) & MASK; v1 = _rotl(v1, 17); v1 ^= v2; v2 = _rotl(v2, 32)
        self.v0, self.v1, self.v2, self.v3 = v0, v1, v2, v3

    def _block(self, m):
        self.v3 ^= m
        for _ in range(self.c):
            self._round()
        self.v0 ^= m

    def update(self, data: bytes):
        data = self.buf + data
        self.length += len(data) - len(self.buf)
        self.buf = b""
        i = 0
        while i + 8 <= len(data):
            self._block(int.from_bytes(data[i:i + 8], "little"))
            i += 8
        self.buf = data[i:]
        return self

    def digest(self):
        b = (self.length & 0xFF) << 56
        tail = self.buf + b"\x00" * (8 - len(self.buf))
        b |= int.from_bytes(tail[:8], "little") & 0x00FFFFFFFFFFFFFF
        self._block(b)
        self.v2 ^= 0xFF
        for _ in range(self.d):
            self._round()
        return (self.v0 ^ self.v1 ^ self.v2 ^ self.v3).to_bytes(8, "little")

    def hexdigest(self):
        return self.digest().hex()


def domain_hash(directory: str, salt: str = DEFAULT_SALT) -> bytes:
    """目录哈希：directory 必须小写并带结尾 "/"；根目录传 ""。"""
    h = SipHash24(b"\x00" * 16)
    h.update(directory.encode("utf-16-le"))
    h.update(salt.encode("utf-16-le"))
    return h.digest()


def file_hash(name: str, salt: str = DEFAULT_SALT) -> bytes:
    """名字哈希：name 为小写逻辑文件名（不含目录）。"""
    from hashlib import blake2s
    h = blake2s(digest_size=32)
    h.update(name.encode("utf-16-le"))
    h.update(salt.encode("utf-16-le"))
    return h.digest()
