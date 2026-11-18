"""CMVS PS2A (.ps3) 脚本容器编解码。

布局（小端）：

    +0   char[4]  "PS2A"
    +4   u32[11]  头部：48, version_raw, key, label_count, code_size,
                  unknown_size, text_size, entry_pc, compressed_size,
                  decoded_size, reserved
    +48  载荷：先做字节变换，`compressed_size != 0` 时再做 LZSS

载荷布局：labels(label_count * 4) | code | unknown | text

字节变换作用于**编码后**的字节：

    plain = ror8(((enc - 124) & 0xFF) ^ xor, shift)
    shift = (key >> 20) % 5 + 1
    xor   = ((key >> 3) + (key >> 24)) & 0xFF

密钥与各段长度全部从文件头读出，工具本身不含任何一部游戏的 key。
`compressed_size = 0` 时引擎完全跳过 LZSS，所以补丁脚本可以不压缩。
详见 docs/engines/cmvs/file-formats.md。
"""
from __future__ import annotations

import struct

HEADER_SIZE = 48
MAGIC = b"PS2A"
_FIELDS = 11


def ror8(value: int, shift: int) -> int:
    shift &= 7
    return ((value >> shift) | (value << (8 - shift))) & 0xFF if shift else value & 0xFF


def rol8(value: int, shift: int) -> int:
    shift &= 7
    return ((value << shift) | (value >> (8 - shift))) & 0xFF if shift else value & 0xFF


def lzss_decode(data: bytes, expected: int) -> bytes:
    ring = bytearray(2048)
    write = 0x7DF
    out = bytearray()
    flags = 0
    cur = 0
    while cur < len(data):
        flags >>= 1
        if flags & 0x100 == 0:
            if cur >= len(data):
                break
            flags = data[cur] | 0xFF00
            cur += 1
        if flags & 1:
            if cur >= len(data):
                break
            value = data[cur]
            cur += 1
            out.append(value)
            ring[write] = value
            write = (write + 1) & 0x7FF
        else:
            if cur + 1 >= len(data):
                break
            first, second = data[cur], data[cur + 1]
            cur += 2
            offset = first | ((second & 0xE0) << 3)
            length = (second & 0x1F) + 2
            for i in range(length):
                value = ring[(offset + i) & 0x7FF]
                out.append(value)
                ring[write] = value
                write = (write + 1) & 0x7FF
    if len(out) != expected:
        raise ValueError("LZSS decoded %d bytes, header declares %d" % (len(out), expected))
    return bytes(out)


class Script:
    """Decoded PS2A container."""

    def __init__(self, header, payload, trailing=b""):
        self.header = header
        self.payload = payload
        self.trailing = trailing

    # -- header accessors -------------------------------------------------
    @property
    def version_raw(self):
        return self.header[1]

    @property
    def key(self):
        return self.header[2]

    @property
    def label_count(self):
        return self.header[3]

    @property
    def code_size(self):
        return self.header[4]

    @property
    def unknown_size(self):
        return self.header[5]

    @property
    def text_size(self):
        return self.header[6]

    @property
    def entry_pc(self):
        return self.header[7]

    @property
    def reserved(self):
        return self.header[10]

    # -- segments ---------------------------------------------------------
    @property
    def code_start(self):
        return self.label_count * 4

    @property
    def labels(self):
        raw = self.payload[:self.code_start]
        return list(struct.unpack_from("<%dI" % self.label_count, raw)) if self.label_count else []

    @property
    def code(self):
        start = self.code_start
        return self.payload[start:start + self.code_size]

    @property
    def unknown(self):
        start = self.code_start + self.code_size
        return self.payload[start:start + self.unknown_size]

    @property
    def text(self):
        start = self.code_start + self.code_size + self.unknown_size
        return self.payload[start:]

    def strings(self):
        """(offset, bytes) for every NUL terminated entry, empty entries included."""
        out = []
        text = self.text
        offset = 0
        while offset < len(text):
            end = text.find(b"\0", offset)
            if end < 0:
                break
            out.append((offset, text[offset:end]))
            offset = end + 1
        return out

    def string_at(self, offset):
        text = self.text
        if offset >= len(text):
            return None
        end = text.find(b"\0", offset)
        return None if end < 0 else text[offset:end]

    # -- codec ------------------------------------------------------------
    @classmethod
    def decode(cls, raw: bytes) -> "Script":
        if len(raw) < HEADER_SIZE or raw[:4] != MAGIC:
            raise ValueError("not a PS2A container")
        header = struct.unpack_from("<%dI" % _FIELDS, raw, 4)
        if header[0] != HEADER_SIZE:
            raise ValueError("unexpected header length %d" % header[0])
        packed = header[8]
        length = packed if packed else len(raw) - HEADER_SIZE
        if HEADER_SIZE + length > len(raw):
            raise ValueError("truncated payload")
        key = header[2]
        shift = (key >> 20) % 5 + 1
        xor = ((key >> 3) + (key >> 24)) & 0xFF
        encoded = raw[HEADER_SIZE:HEADER_SIZE + length]
        plain = bytes(ror8(((b - 124) & 0xFF) ^ xor, shift) for b in encoded)
        payload = lzss_decode(plain, header[9]) if packed else plain
        total = header[3] * 4 + header[4] + header[5] + header[6]
        if len(payload) != total:
            raise ValueError("payload %d bytes, header declares %d" % (len(payload), total))
        return cls(list(header), payload, raw[HEADER_SIZE + length:])

    def encode(self, compress: bool = False) -> bytes:
        """Serialise with compressed_size = 0 (engine skips LZSS)."""
        labels = self.labels
        total = self.code_start + self.code_size + self.unknown_size + self.text_size
        if len(self.payload) != total:
            raise ValueError("payload does not match header sizes")
        key = self.key
        shift = (key >> 20) % 5 + 1
        xor = ((key >> 3) + (key >> 24)) & 0xFF
        body = bytes(((rol8(b, shift) ^ xor) + 124) & 0xFF for b in self.payload)
        header = [HEADER_SIZE, self.version_raw, key, self.label_count, self.code_size,
                  self.unknown_size, self.text_size, self.entry_pc, 0, total, self.reserved]
        return MAGIC + struct.pack("<%dI" % _FIELDS, *header) + body + self.trailing

    def with_text(self, text: bytes) -> "Script":
        """Return a copy whose text segment is replaced (offsets are caller's job)."""
        header = list(self.header)
        header[6] = len(text)
        header[9] = self.code_start + self.code_size + self.unknown_size + len(text)
        payload = self.payload[:self.code_start + self.code_size + self.unknown_size] + text
        return Script(header, payload, self.trailing)


def load(path: str) -> Script:
    with open(path, "rb") as stream:
        return Script.decode(stream.read())


def save(script: Script, path: str, compress: bool = False) -> None:
    with open(path, "wb") as stream:
        stream.write(script.encode(compress))
