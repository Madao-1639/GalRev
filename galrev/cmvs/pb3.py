"""CMVS PB3B (type 1) 编解码。

布局（详见 docs/engines/cmvs/file-formats.md）：
  +0   "PB3B"
  +8   ..+52 共 44 字节，加密后才是真实头部：
         plain[8+i] = (enc[8+i] ^ raw[len-3+i%2]) - raw[len-47+i]
  +24 u32 分块边长（16）
  +28 u16 codec 类型（1）
  +30 u16 宽 / +32 u16 高 / +34 u16 位深（24/32）
  +44 u32 flags 区起点 / +48 u32 data 区起点

两个区都先放「每通道一个 u32 长度」表，再按通道顺序 B,G,R(,A) 连续存放。
flags 区每通道块：u32 分块标记字节数、u32 常量块数、u32 字面像素数，
接着分块标记（高位先，1=整块同值）、常量块值、LZSS 位流；
data 区每通道块：字面像素字节。位流 1=引用、0=字面，8 个 token 一个字节。

编码策略：全部走「字面」，即分块标记全 0、常量块 0 个、位流全 0 字节。
体积约为原图的 1.8 倍，换来的是「不写 LZSS 匹配器也能正确产出」；
引擎不校验 checksum，所以这条路径可以安全使用。

只实现 type 1。type 2/3 为 JBP1 差分编码、type 5 为预测器+累加、
type 6 为外部底图引用，见文档。
"""
from __future__ import annotations

import struct

HEADER = 52
TYPE1 = 1


def _plain_header(raw: bytes) -> bytes:
    if len(raw) < HEADER + 47 or raw[:4] != b"PB3B":
        raise ValueError("not a PB3B container")
    header = bytearray(raw[:HEADER])
    for i in range(44):
        header[8 + i] = ((header[8 + i] ^ raw[len(raw) - 3 + (i % 2)]) - raw[len(raw) - 47 + i]) & 0xFF
    return bytes(header)


def _chunks(raw: bytes, base: int, count: int):
    lengths = struct.unpack_from("<%dI" % count, raw, base)
    at = base + count * 4
    out = []
    for n in lengths:
        out.append((at, at + n))
        at += n
    return out


def _lzss_decode(flags: bytes, data: bytes, expected: int) -> bytes:
    out = bytearray(expected)
    at = 0
    token = 0
    length = 0
    while length < expected:
        flag = flags[token // 8]
        if flag == 0 and token % 8 == 0 and expected - length >= 8:
            out[length:length + 8] = data[at:at + 8]
            at += 8
            token += 8
            length += 8
            continue
        if flag & (0x80 >> (token % 8)):
            word = data[at] | (data[at + 1] << 8)
            at += 2
            offset = word >> 5
            count = (word & 31) + 3
            for i in range(count):
                out[length] = out[length - offset] if length >= offset else 0
                length += 1
        else:
            out[length] = data[at]
            at += 1
            length += 1
        token += 1
    if at != len(data):
        raise ValueError("PB3: %d unused literal bytes" % (len(data) - at))
    if (token + 7) // 8 != len(flags):
        raise ValueError("PB3: flag stream length mismatch")
    return bytes(out)


def decode(raw: bytes):
    """返回 (width, height, bpp, 逐像素 RGBA 字节串)。"""
    header = _plain_header(raw)
    kind = struct.unpack_from("<H", header, 28)[0]
    if kind != TYPE1:
        raise ValueError("只支持 type 1，本文件是 type %d" % kind)
    width, height, bpp = struct.unpack_from("<HHH", header, 30)
    block = struct.unpack_from("<I", header, 24)[0]
    flags_at, data_at = struct.unpack_from("<II", header, 44)
    channels = bpp // 8
    count = width * height
    tiles = ((width + block - 1) // block) * ((height + block - 1) // block)
    flags = _chunks(raw, flags_at, channels)
    data = _chunks(raw, data_at, channels)
    planes = []
    for channel in range(channels):
        f = raw[flags[channel][0]:flags[channel][1]]
        c = raw[data[channel][0]:data[channel][1]]
        flag_bytes, solid_bytes, literal_count = struct.unpack_from("<III", f, 0)
        if flag_bytes != (tiles + 7) // 8:
            raise ValueError("PB3: 分块标记字节数不符")
        solid_at = 12 + flag_bytes
        lzss_at = solid_at + solid_bytes
        literals = _lzss_decode(f[lzss_at:], c, literal_count)
        plane = bytearray(count)
        literal = 0
        solid = 0
        tile = 0
        for y in range(0, height, block):
            for x in range(0, width, block):
                is_solid = f[12 + tile // 8] & (128 >> (tile % 8))
                tile += 1
                columns = min(width, x + block) - x
                for yy in range(y, min(height, y + block)):
                    row = yy * width + x
                    if is_solid:
                        value = f[solid_at + solid]
                        plane[row:row + columns] = bytes([value]) * columns
                    else:
                        plane[row:row + columns] = literals[literal:literal + columns]
                        literal += columns
                if is_solid:
                    solid += 1
        planes.append(plane)
    pixels = bytearray()
    for i in range(count):
        for channel in range(channels):
            pixels.append(planes[channel][i])
        if channels == 3:
            pixels.append(255)
    return width, height, bpp, bytes(pixels)


def encode(width: int, height: int, bpp: int, rgba: bytes, block: int = 16,
           field08: int = 0x01000000) -> bytes:
    """把逐像素 RGBA（顶向下）编成 PB3B type 1，全字面编码。"""
    channels = bpp // 8
    count = width * height
    if len(rgba) != count * 4:
        raise ValueError("像素字节数与尺寸不符")
    tiles = ((width + block - 1) // block) * ((height + block - 1) // block)
    flag_bytes = (tiles + 7) // 8

    planes = [bytearray(count) for _ in range(channels)]
    for i in range(count):
        for channel in range(channels):
            planes[channel][i] = rgba[i * 4 + channel]

    def tile_order(plane):
        """解码端按「分块优先、块内行优先」消费字面像素，编码必须同序。"""
        out = bytearray()
        for y in range(0, height, block):
            for x in range(0, width, block):
                columns = min(width, x + block) - x
                for yy in range(y, min(height, y + block)):
                    row = yy * width + x
                    out += plane[row:row + columns]
        return bytes(out)

    flag_chunks = []
    data_chunks = []
    for channel in range(channels):
        literal = tile_order(planes[channel])
        flags = bytes((count + 7) // 8)          # 全 0：全部按字面
        flag_chunks.append(struct.pack("<III", flag_bytes, 0, count)
                           + bytes(flag_bytes) + flags)
        data_chunks.append(literal)

    flags_region = struct.pack("<%dI" % channels, *[len(c) for c in flag_chunks]) + b"".join(flag_chunks)
    data_region = struct.pack("<%dI" % channels, *[len(c) for c in data_chunks]) + b"".join(data_chunks)
    flags_at = HEADER
    data_at = HEADER + len(flags_region)

    header = bytearray(HEADER)
    header[0:4] = b"PB3B"
    struct.pack_into("<I", header, 8, field08)
    struct.pack_into("<I", header, 24, block)
    struct.pack_into("<H", header, 28, TYPE1)
    struct.pack_into("<H", header, 30, width)
    struct.pack_into("<H", header, 32, height)
    struct.pack_into("<H", header, 34, bpp)
    struct.pack_into("<I", header, 44, flags_at)
    struct.pack_into("<I", header, 48, data_at)
    body = bytes(header) + flags_region + data_region

    # 头部 8..52 与文件末尾 -47/-3/-2 字节互相加密
    tail47 = body[-47:]
    out = bytearray(body)
    for i in range(44):
        out[8 + i] = ((header[8 + i] + tail47[i]) ^ tail47[44 + (i % 2)]) & 0xFF
    return bytes(out)
