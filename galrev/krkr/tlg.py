"""KiriKiri/MDF 的 TLG 贴图编解码（TLG5 / TLG6，含 `TLG0.0\\0sds` 外壳）。

来源：GARbro `ArcFormats/KiriKiri/ImageTLG.cs`（W.Dee 原始实现的 C# 移植），本文件是逐语义的 Python 移植。

TLG 是 krkr **引擎级**格式，不是任何一部游戏专属。同一份实现存在于两处：补丁项目的 `tool/tlg.py` 与本机知识库的 `galrev/krkr/tlg.py`（除本节文字外逐字节相同）；改一处必须同步另一处，并同步知识库的 `file-formats` 卷。游戏专属的标定值（哪张 pimg 是哪个版本）不写在这里。

## 两种变体与外壳

```
裸 TLG5:  "TLG5.0\\0raw" (10) | 0x1a | colors | w u32 | h u32 | blockheight u32 | ...
裸 TLG6:  "TLG6.0\\0raw" (10) | 0x1a | colors | 0 | 0 | 0 | ...
带外壳:   "TLG0.0\\0sds" (10) | 0x1a | 0xe5 0x9e size-ish (5 B) | <上面任一形态，从 +15 起>
```

外壳那 15 字节是 `TLG0.0\\0sds\\x1a` + 5 字节（第 1 字节在本作样本里恒为 `0xe5`，
其余 4 字节是原图长度的变体编码，解码不用它）。`decode()` 自动跳过外壳。

## TLG5 平面编码（行差分 + 颜色相关）

    g 平面：acc1 += g                       -> out_G = (acc1 + prev_G)
    b 平面：c0 = b + g；acc0 += c0           -> out_B = (acc0 + prev_B)
    r 平面：c2 = r + g；acc2 += c2           -> out_R = (acc2 + prev_R)
    a 平面：acc3 += a                        -> out_A = (acc3 + prev_A)

acc* 每行从 0 开始累加，prev_* 是上一行还原后的同列值（首行按 0 处理）。LZSS 的
4096 字节滑窗在整张图的所有块、所有平面之间**连续**复用。

已知怪癖：GARbro 的首行分支把 alpha 直接写成 0xff（忽略 a 平面），这里照搬，
encode 时也会生成与之自洽的数据（首行 alpha 值不回读）。

## TLG6 编码（Golomb + 30 种 MED/AVG 预测器）

TLG6 按 8×8 块切分：先逐块读「色度过滤类型」表（本身又是 TLG5 的 LZSS 流），再逐
8 行组、逐平面读 Golomb 编码的残差，最后按过滤类型选预测器（偶数 = MED 中值边缘检
测，奇数 = AVG）逐像素还原。两个易错点（`doc/lessons-learned.md` 有留档）：

* 色度过滤表的 LZSS **初始字典**是 `for i in 32: for j in 16: [i,i,i,i,j,j,j,j]`
  （`i`/`j` 各占 4 个相同字节，不是 `[i,0,0,0]`）。填错时首块过滤类型全错，图像呈
  块状色斑。
* 过滤类型的作用是**先把 v 按通道相关式展开**（`r±g`/`b±g` 等）**再**喂给 MED/AVG，
  只照抄表会漏掉这一步。

## 接口：解码两版，编码只有 TLG5

**这个不对称是显式的，不藏在返回类型里**：

```python
img   = tlg.decode(data)        # -> tlg.Image，带 .kind（"TLG5" / "TLG6"）
data2 = tlg.encode(img.width, img.height, img.rgba, kind=img.kind)
```

* `decode()` 两种变体与外壳都吃，返回的 `Image` **带着 `kind`**，所以「手上这张原来是什么
  格式」不会因为一次解码就丢掉，也不需要再解析一遍头部去问。
* `encode(kind="TLG6")` **抛 `TlgError`**，而不是静默降级成 TLG5。要原样换掉某张 TLG6，
  请直接复用原字节，不要解码再编码（那会改变编码格式）。
* 为什么不做 TLG6 编码：需要 Golomb 编码器 + 30 种预测器的**选取搜索**（编码侧没有唯一解，
  是个启发式搜索问题），成本远大于收益；而引擎两个变体都读，写入端统一成 TLG5 完全可行
  （官方打包的 v3 `pimg` 本身就是 TLG5，实测改写后的产物引擎能正常显示）。
  **这是有意的接口边界，不是漏做。**
"""

from __future__ import annotations

import struct

# 裸 TLG5 头
TLG5_SIG = b"TLG5.0\x00raw\x1a"       # 裸 TLG5 头
TLG6_SIG = b"TLG6.0\x00raw\x1a"       # 裸 TLG6 头
SDS_SIG = b"TLG0.0\x00sds\x1a"        # TLG0 外壳（15 字节，其后是裸 TLG5 或 TLG6）
SDS_LEN = 15

KIND_TLG5 = "TLG5"
KIND_TLG6 = "TLG6"


class TlgError(Exception):
    pass


class Image:
    """解码结果：像素 + 它的来源格式。

    `kind` 跟着像素走，所以「解出来的是什么格式」不需要再解析一次头部去问。
    注意 `encode()` 不能把它变回 TLG6（见模块 docstring「接口」）。
    """

    __slots__ = ("kind", "width", "height", "colors", "rgba")

    def __init__(self, kind: str, width: int, height: int, colors: int, rgba: bytes):
        self.kind = kind
        self.width = width
        self.height = height
        self.colors = colors      # 源文件通道数（3 = 无 alpha 面，解码时补满 0xFF）
        self.rgba = rgba

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def encode(self) -> bytes:
        """按 `kind` 重新编码。TLG6 会抛 `TlgError`（见 `encode()`）。"""
        return encode(self.width, self.height, self.rgba, kind=self.kind)

    def __repr__(self) -> str:
        return f"<Image {self.kind} {self.width}x{self.height} colors={self.colors}>"


# --------------------------------------------------------------------- LZSS
def decompress_slide(inbuf: bytes, text: bytearray, r: int, out_size: int) -> tuple[bytes, int]:
    """TVP 的 4096 字节滑窗 LZSS 解压。TLG5 的平面与 TLG6 的过滤类型表都用它。"""
    out = bytearray(out_size)
    o = 0
    flags = 0
    i = 0
    n = len(inbuf)
    while i < n and o < out_size:
        flags >>= 1
        if not (flags & 256):
            flags = inbuf[i] | 0xFF00
            i += 1
        if flags & 1:
            mpos = inbuf[i] | ((inbuf[i + 1] & 0x0F) << 8)
            mlen = (inbuf[i + 1] & 0xF0) >> 4
            i += 2
            mlen += 3
            if mlen == 18:
                mlen += inbuf[i]
                i += 1
            while mlen:
                c = text[mpos]
                text[r] = c
                mpos = (mpos + 1) & 0xFFF
                r = (r + 1) & 0xFFF
                if o < out_size:
                    out[o] = c
                    o += 1
                mlen -= 1
        else:
            c = inbuf[i]
            i += 1
            text[r] = c
            r = (r + 1) & 0xFFF
            if o < out_size:
                out[o] = c
                o += 1
    return bytes(out), r


# ------------------------------------------------------------------ 判型/头部
class Header:
    """解析出的 TLG 头部（不包含位图）。"""

    __slots__ = ("kind", "colors", "width", "height", "data_offset", "wrapped")

    def __init__(self, kind: str, colors: int, width: int, height: int,
                 data_offset: int, wrapped: bool):
        self.kind = kind
        self.colors = colors
        self.width = width
        self.height = height
        self.data_offset = data_offset   # 位图数据（TLG5 的 blocksize 表 / TLG6 的 max_bit_length）
        self.wrapped = wrapped           # 是否套了 `TLG0.0\0sds` 外壳

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def __repr__(self) -> str:
        wrap = " +外壳" if self.wrapped else ""
        return (f"<Header {self.kind}{wrap} {self.width}x{self.height} "
                f"colors={self.colors}>")


def header(data: bytes) -> Header:
    """只看头，不解析位图。判型、拿尺寸/偏移都用它。"""
    head = data[:0x26 + SDS_LEN]
    off = 0
    wrapped = head[:len(SDS_SIG)] == SDS_SIG
    if wrapped:
        off = SDS_LEN
    tag = head[off:off + 11]
    if tag == TLG5_SIG:
        kind = KIND_TLG5
    elif tag == TLG6_SIG:
        kind = KIND_TLG6
    else:
        raise TlgError(f"不是 TLG raw（外壳={head[:len(SDS_SIG)]!r} 头={tag!r}）")
    colors = head[off + 11]
    if kind == KIND_TLG6:
        if colors not in (1, 3, 4):
            raise TlgError(f"TLG6 颜色数 {colors}")
        if head[off + 12] or head[off + 13] or head[off + 14]:
            raise TlgError("TLG6 头部 12/13/14 应为 0")
        off += 15
    else:
        if colors not in (3, 4):
            raise TlgError(f"TLG5 颜色数 {colors}")
        off += 12
    width, height = struct.unpack_from("<II", head, off)
    return Header(kind, colors, width, height, off + 8, wrapped)


# ---------------------------------------------------------------- TLG5 decode
def _decode5(data: bytes) -> "Image":
    hdr = header(data)
    if hdr.kind != KIND_TLG5:
        raise TlgError(f"不是 TLG5（头部判型为 {hdr.kind}）")
    colors, width, height, pos = hdr.colors, hdr.width, hdr.height, hdr.data_offset
    blockheight = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    nblocks = (height - 1) // blockheight + 1
    sizes = struct.unpack_from("<" + "I" * nblocks, data, pos)
    pos += 4 * nblocks

    stride = width * 4
    image = bytearray(height * stride)
    text = bytearray(4096)
    r = 0
    planes = [bytearray(blockheight * width + 10) for _ in range(colors)]
    prev_off = None          # 上一行的行首偏移（跨块保留；首行按 0 基准）
    y_blk = 0
    for b in range(nblocks):
        start = pos
        rows = min(blockheight, height - y_blk)
        for c in range(colors):
            mark = data[pos]
            (size,) = struct.unpack_from("<I", data, pos + 1)
            pos += 5
            buf = data[pos: pos + size]
            if len(buf) != size:
                raise TlgError(f"TLG5 平面数据截断：偏移 {pos:#x} 起需 {size} 字节，实际只剩 {len(buf)}")
            pos += size
            if mark == 0:
                out, r = decompress_slide(buf, text, r, rows * width)
            else:
                out = bytes(buf)
            planes[c][:rows * width] = out
        if pos - start != sizes[b]:
            raise TlgError(f"TLG5 块 {b} 长度 {pos - start} != 表里 {sizes[b]}")
        for y in range(rows):
            row_off = (y_blk + y) * stride
            o = y * width
            acc_b = acc_g = acc_r = acc_a = 0
            for x in range(width):
                g = planes[1][o + x]
                b_ = planes[0][o + x] + g
                r_ = planes[2][o + x] + g
                acc_b = (acc_b + b_) & 0xFF
                acc_g = (acc_g + g) & 0xFF
                acc_r = (acc_r + r_) & 0xFF
                if colors == 4:
                    acc_a = (acc_a + planes[3][o + x]) & 0xFF
                if prev_off is None:
                    image[row_off + x * 4 + 0] = acc_r
                    image[row_off + x * 4 + 1] = acc_g
                    image[row_off + x * 4 + 2] = acc_b
                    image[row_off + x * 4 + 3] = acc_a if colors == 4 else 0xFF
                else:
                    p = prev_off + x * 4
                    image[row_off + x * 4 + 0] = (acc_r + image[p + 0]) & 0xFF
                    image[row_off + x * 4 + 1] = (acc_g + image[p + 1]) & 0xFF
                    image[row_off + x * 4 + 2] = (acc_b + image[p + 2]) & 0xFF
                    image[row_off + x * 4 + 3] = ((acc_a if colors == 4 else 0) + image[p + 3]) & 0xFF
            prev_off = row_off
        y_blk += rows
    return Image(KIND_TLG5, width, height, colors, bytes(image))


# ------------------------------------------------ TLG6 常量与预测器（GARbro 表）
H_BLK = 8           # TVP_TLG6_H_BLOCK_SIZE
W_BLK = 8           # TVP_TLG6_W_BLOCK_SIZE
_GOLOMB_N = 4       # TVP_TLG6_GOLOMB_N_COUNT
_LZ_BITS = 12       # TVP_TLG6_LeadingZeroTable_BITS
_LZ_SIZE = 1 << _LZ_BITS
_M32 = 0xFFFFFFFF

# TVPTLG6GolombCompressed（W.Dee, 2004/03/25 调参）
_GOLOMB_COMPRESSED = (
    (3, 7, 15, 27, 63, 108, 223, 448, 130),
    (3, 5, 13, 24, 51, 95, 192, 384, 257),
    (2, 5, 12, 21, 39, 86, 155, 320, 384),
    (2, 3, 9, 18, 33, 61, 129, 258, 511),
)


def _init_leading_zero() -> list[int]:
    """TVPTLG6LeadingZeroTable：首个置位位的位号 + 1，全 0 给 0。"""
    tbl = [0] * _LZ_SIZE
    for i in range(_LZ_SIZE):
        cnt = 0
        j = 1
        while j != _LZ_SIZE and (i & j) == 0:
            j <<= 1
            cnt += 1
        cnt += 1
        if j == _LZ_SIZE:
            cnt = 0
        tbl[i] = cnt
    return tbl


def _init_golomb() -> list[list[int]]:
    """TVPTLG6GolombBitLengthTable：`[a][n]` → 该上下文下 Golomb 的 k 位长。"""
    tbl = [[0] * _GOLOMB_N for _ in range(_GOLOMB_N * 2 * 128)]
    for n in range(_GOLOMB_N):
        a = 0
        for i in range(9):
            for _ in range(_GOLOMB_COMPRESSED[n][i]):
                tbl[a][n] = i
                a += 1
        if a != _GOLOMB_N * 2 * 128:
            raise TlgError("Golomb 位长表初始化失败")
    return tbl


_LZ_TABLE = _init_leading_zero()
_GOLOMB_TABLE = _init_golomb()


def _gt_mask(a: int, b: int) -> int:
    """tvp_make_gt_mask：逐字节 a > b 的 0xFF 掩码。"""
    tmp2 = (~b) & _M32
    tmp = ((a & tmp2) + (((a ^ tmp2) >> 1) & 0x7F7F7F7F)) & 0x80808080
    return (((tmp >> 7) + 0x7F7F7F7F) ^ 0x7F7F7F7F) & _M32


def _packed_add(a: int, b: int) -> int:
    """tvp_packed_bytes_add：逐字节加法（不回卷到相邻字节）。"""
    tmp = (((a & b) << 1) + ((a ^ b) & 0xFEFEFEFE)) & 0x01010100
    return (a + b - tmp) & _M32


def _med2(a: int, b: int, c: int) -> int:
    """中值边缘检测（MED），thx Mr. sugi at kirikiri.info。"""
    aa_gt_bb = _gt_mask(a, b)
    x = (a ^ b) & aa_gt_bb
    aa = x ^ a
    bb = x ^ b
    n = _gt_mask(c, bb)
    nn = _gt_mask(aa, c)
    m = (~(n | nn)) & _M32
    return ((n & aa) | (nn & bb) | ((bb & m) - (c & m) + (aa & m))) & _M32


def _med(a: int, b: int, c: int, v: int) -> int:
    return _packed_add(_med2(a, b, c), v)


def _avg(a: int, b: int, c: int, v: int) -> int:
    avg = (((a & b) + (((a ^ b) & 0xFEFEFEFE) >> 1)) + ((a ^ b) & 0x01010101)) & _M32
    return _packed_add(avg, v)


# 色度过滤的颜色分解变换（GARbro `TVPTLG6DecodeLineGeneric` 的 case 表）。
# 偶数 = MED、奇数 = AVG，两者共用同一组变换（`ft & ~1`）。
_TRANSFORM = {
    0:  lambda r, g, b: (r, g, b),
    2:  lambda r, g, b: (r + g, g, b + g),
    4:  lambda r, g, b: (r + b + g, g + b, b),
    6:  lambda r, g, b: (r, g + r, b + r + g),
    8:  lambda r, g, b: (r + b + r + g, g + b + r, b + r),
    10: lambda r, g, b: (r, g + b + r, b + r),
    12: lambda r, g, b: (r, g, b + g),
    14: lambda r, g, b: (r, g + b, b),
    16: lambda r, g, b: (r + g, g, b),
    18: lambda r, g, b: (r + b, g + r + b, b + g + r + b),
    20: lambda r, g, b: (r, g + r, b + r),
    22: lambda r, g, b: (r + b, g + b, b),
    24: lambda r, g, b: (r + b, g + r + b, b),
    26: lambda r, g, b: (r + b + g, g + r + b + g, b + g),
    28: lambda r, g, b: (r + b + g + r, g + r, b + g + r),
    30: lambda r, g, b: (r + 2 * b, g + 2 * b, b),
}


def _make_decoder(ft: int):
    """按过滤类型造一个 `(a, b, c, v) -> u32` 的解码函数。

    `v` 先按该类型的通道相关式展开（只保留低 8 位），再喂 MED/AVG —— 这两步顺序
    不能颠倒，否则色度一塌糊涂。
    """
    base = _med if (ft % 2 == 0) else _avg
    tf = _TRANSFORM[ft & ~1]

    def dec(a: int, b: int, c: int, v: int) -> int:
        r, g, bb = (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
        tr, tg, tb = tf(r, g, bb)
        out = (v & 0xFF000000) | ((tr & 0xFF) << 16) | ((tg & 0xFF) << 8) | (tb & 0xFF)
        return base(a, b, c, out)

    return dec


# 32 种过滤类型各建一次，逐块查表取用（原实现在每 8 像素块 × 每行都重建一次闭包，
# 1280×720 一张图要建 6 万次，纯浪费）。表是模块级不可变数据，与解码状态无关。
_DECODERS = tuple(_make_decoder(ft) for ft in range(32))


def _lzss_text() -> bytearray:
    """TLG6 色度过滤表解 LZSS 时用的初始字典（32×16 个 8 字节槽）。"""
    text = bytearray(4096)
    p = 0
    for i in range(32):
        for j in range(16):
            text[p:p + 8] = bytes((i, i, i, i, j, j, j, j))
            p += 8
    return text


def _decode_golomb(pixelbuf: list[int], offset: int, pixel_count: int,
                   bit_pool: bytes, first: bool) -> None:
    """TLG6 的 Golomb 解码（`first` = 本块第一个平面，ubuf 只写最低字节）。"""
    mask = _M32 if first else (~(0xFF << offset)) & _M32
    bpi = 0

    def u32(idx: int) -> int:
        return int.from_bytes(bit_pool[idx:idx + 4], "little")

    n = _GOLOMB_N - 1
    a = 0
    bit_pos = 1
    zero = (bit_pool[0] & 1) == 0
    pixel = 0

    while pixel < pixel_count:
        # 取「连续段长度」的 Golomb-Rice 前缀
        t = u32(bpi) >> bit_pos
        b = _LZ_TABLE[t & (_LZ_SIZE - 1)]
        bit_count = b
        while b == 0:
            bit_count += _LZ_BITS
            bit_pos += _LZ_BITS
            bpi += bit_pos >> 3
            bit_pos &= 7
            t = u32(bpi) >> bit_pos
            b = _LZ_TABLE[t & (_LZ_SIZE - 1)]
            bit_count += b
        bit_pos += b
        bpi += bit_pos >> 3
        bit_pos &= 7

        bit_count -= 1
        count = 1 << bit_count
        count += (u32(bpi) >> bit_pos) & (count - 1)
        bit_pos += bit_count
        bpi += bit_pos >> 3
        bit_pos &= 7

        if zero:
            for _ in range(count):
                pixelbuf[pixel] = 0 if first else (pixelbuf[pixel] & mask)
                pixel += 1
            zero = False
        else:
            for _ in range(count):
                k = _GOLOMB_TABLE[a][n]
                t = u32(bpi) >> bit_pos
                if t != 0:
                    b = _LZ_TABLE[t & (_LZ_SIZE - 1)]
                    bit_count = b
                    while b == 0:
                        bit_count += _LZ_BITS
                        bit_pos += _LZ_BITS
                        bpi += bit_pos >> 3
                        bit_pos &= 7
                        t = u32(bpi) >> bit_pos
                        b = _LZ_TABLE[t & (_LZ_SIZE - 1)]
                        bit_count += b
                    bit_count -= 1
                else:
                    bpi += 5
                    bit_count = bit_pool[bpi - 1]
                    bit_pos = 0
                    t = u32(bpi)
                    b = 0

                v = (bit_count << k) + ((t >> b) & ((1 << k) - 1))
                sign = (v & 1) - 1
                v >>= 1
                a += v
                val = ((v ^ sign) + sign + 1) & 0xFF
                pixelbuf[pixel] = val if first else ((pixelbuf[pixel] & mask) | (val << offset))
                pixel += 1

                bit_pos += b
                bit_pos += k
                bpi += bit_pos >> 3
                bit_pos &= 7

                n -= 1
                if n < 0:
                    a >>= 1
                    n = _GOLOMB_N - 1
            zero = True


class _RowCtx:
    """解一行（含蛇形扫描）所需的**全部可变状态**。

    这是一个纯粹的局部工作区：三组 `(数组, 下标)` 配对与几个行级偏移量原先作为 15 个
    位置参数传入 `_decode_line`，靠位置对齐、顺序错了就静默解错。收进对象后调用点变成
    `_decode_line(ctx, start_block, block_limit, width)`，配对关系由字段名保证。

    **不要跨行复用**：`curline`/`cl_idx` 每行都要换，`ib_idx` 也按行推进。
    """

    __slots__ = ("prevline", "pl_idx", "curline", "cl_idx",
                 "ftypes", "ft_idx", "skipblock", "inbuf", "ib_base",
                 "oddskip", "direction")

    def __init__(self, prevline: list[int], pl_idx: int,
                 curline: list[int], cl_idx: int,
                 ftypes: bytes, ft_idx: int, skipblock: int,
                 inbuf: list[int], ib_base: int, oddskip: int, direction: int):
        self.prevline = prevline          # 上一行的 u32 数组（首行为全 zero 的虚拟行）
        self.pl_idx = pl_idx              # 在 prevline 里的当前行首下标
        self.curline = curline            # 当前输出行（同一个 image 数组内的行首下标）
        self.cl_idx = cl_idx
        self.ftypes = ftypes              # 色度过滤类型表（每 8×8 块一个字节）
        self.ft_idx = ft_idx              # 本行所属行组在 ftypes 里的起点
        self.skipblock = skipblock        # (行组内行数) × 8，块间跨行的跨度
        self.inbuf = inbuf                # Golomb 解出的残差（pixelbuf）
        self.ib_base = ib_base            # 本行在 inbuf 里的起点（行组内第几行 × 8 或零头宽）
        self.oddskip = oddskip            # 蛇形扫描的对齐补偿
        self.direction = direction        # 1 = 正向，0 = 反向


def _decode_line(ctx: _RowCtx, start_block: int, block_limit: int, width: int,
                 initialp: int) -> None:
    """解一行里的 `[start_block, block_limit)` 这些 8 像素块（含蛇形扫描）。"""
    pl_idx, cl_idx = ctx.pl_idx, ctx.cl_idx
    ib_idx = ctx.ib_base
    prevline, curline = ctx.prevline, ctx.curline
    if start_block != 0:
        pl_idx += start_block * W_BLK
        cl_idx += start_block * W_BLK
        p = curline[cl_idx - 1]
        up = prevline[pl_idx - 1]
    else:
        p = up = initialp

    skipblock = ctx.skipblock
    ib_idx += skipblock * start_block
    step = 1 if (ctx.direction & 1) else -1
    oddskip = ctx.oddskip
    ftypes, ft_idx = ctx.ftypes, ctx.ft_idx
    inbuf = ctx.inbuf

    for i in range(start_block, block_limit):
        w = width - i * W_BLK
        if w > W_BLK:
            w = W_BLK
        ww = w
        if step == -1:
            ib_idx += ww - 1
        if i & 1:
            ib_idx += oddskip * ww

        ft = ftypes[ft_idx + i]
        if ft > 31:
            raise TlgError(f"未知色度过滤类型 {ft}（块 {i}，ftypes 下标 {ft_idx + i}）")
        dec = _DECODERS[ft]

        for _ in range(w):
            u = prevline[pl_idx]
            p = dec(p, u, up, inbuf[ib_idx])
            up = u
            curline[cl_idx] = p
            cl_idx += 1
            pl_idx += 1
            ib_idx += step

        if step == 1:
            ib_idx += skipblock - ww
        else:
            ib_idx += skipblock + 1
        if i & 1:
            ib_idx -= oddskip * ww


def _decode6(data: bytes) -> "Image":
    hdr = header(data)
    if hdr.kind != KIND_TLG6:
        raise TlgError(f"不是 TLG6（头部判型为 {hdr.kind}）")
    colors, width, height, p = hdr.colors, hdr.width, hdr.height, hdr.data_offset
    max_bit_length = struct.unpack_from("<I", data, p)[0]
    p += 4

    xbc = (width - 1) // W_BLK + 1
    ybc = (height - 1) // H_BLK + 1
    main_count = width // W_BLK
    fraction = width - main_count * W_BLK

    image = [0] * (height * width)
    bit_pool = bytearray(max_bit_length // 8 + 16)
    pixelbuf = [0] * (width * H_BLK + 1)
    ftypes = bytearray(xbc * ybc)
    zerocolor = 0xFF000000 if colors == 3 else 0x00000000
    zeroline = [zerocolor] * width

    inbuf_size = struct.unpack_from("<I", data, p)[0]
    p += 4
    inbuf = data[p:p + inbuf_size]
    p += inbuf_size
    ftypes[:] = decompress_slide(inbuf, _lzss_text(), 0, len(ftypes))[0]

    prevline = zeroline
    pl_idx = 0

    for y in range(0, height, H_BLK):
        ylim = min(y + H_BLK, height)
        pixel_count = (ylim - y) * width
        for c in range(colors):
            bit_length = struct.unpack_from("<I", data, p)[0]
            p += 4
            method = (bit_length >> 30) & 3
            bit_length &= 0x3FFFFFFF
            if method != 0:
                raise TlgError(f"TLG6 熵编码方法 {method}（只实现了 Golomb）")
            byte_length = (bit_length + 7) // 8
            bit_pool[:byte_length] = data[p:p + byte_length]
            p += byte_length
            _decode_golomb(pixelbuf, 0 if (c == 0 and colors != 1) else c * 8,
                           pixel_count, bit_pool,
                           first=(c == 0 and colors != 1))

        ft = (y // H_BLK) * xbc
        skipbytes = (ylim - y) * W_BLK
        for yy in range(y, ylim):
            curline_off = yy * width
            direction = (yy & 1) ^ 1
            oddskip = (ylim - yy - 1) - (yy - y)
            # 「整块」段与「行尾零头块」是同一行的两段：除 inbuf 起点（ib_base）外完全共用 ctx
            base_main = min(width, W_BLK) * (yy - y)
            ctx = _RowCtx(prevline, pl_idx, image, curline_off,
                          ftypes, ft, skipbytes, pixelbuf, base_main, oddskip, direction)
            if main_count:
                _decode_line(ctx, 0, main_count, width, zerocolor)
            if main_count != xbc:
                ww = min(fraction, W_BLK)
                ctx.ib_base = ww * (yy - y)
                _decode_line(ctx, main_count, xbc, width, zerocolor)
            prevline = image
            pl_idx = curline_off

    # 打包的 u32 里 byte0=b, byte1=g, byte2=r, byte3=a
    out = bytearray(width * height * 4)
    if colors == 1:
        # 灰度：只解出了蓝通道，三个通道同值（**未经 GARbro 交叉验证**，本作样本里没有）
        for i, v in enumerate(image):
            g = v & 0xFF
            out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = g
            out[i * 4 + 3] = 0xFF
    else:
        alpha_full = colors == 3
        for i, v in enumerate(image):
            out[i * 4] = (v >> 16) & 0xFF
            out[i * 4 + 1] = (v >> 8) & 0xFF
            out[i * 4 + 2] = v & 0xFF
            out[i * 4 + 3] = 0xFF if alpha_full else (v >> 24) & 0xFF
    return Image(KIND_TLG6, width, height, colors, bytes(out))


# ------------------------------------------------------------------- 公开入口
def decode(data: bytes) -> Image:
    """任意 TLG（裸 TLG5 / 裸 TLG6 / `TLG0.0\0sds` 外壳包着的任一版）-> `Image`。"""
    return _decode5(data) if header(data).kind == KIND_TLG5 else _decode6(data)


# ------------------------------------------------------------------- encode
def encode(width: int, height: int, rgba: bytes, *, kind: str = KIND_TLG5,
           blockheight: int = 4) -> bytes:
    """RGBA8 -> TLG 字节。**`kind` 只接受 "TLG5"**（见模块 docstring「接口」）。

    * `kind="TLG5"`：平面用 TLG5 自带的 LZSS 压缩，`blockheight` 可调。
    * `kind="TLG6"`：抛 `TlgError` —— 不做 TLG6 编码器，理由是引擎两个变体都读，而编码侧
      需要 Golomb 编码器 + 30 种预测器的**选取搜索**，成本远大于收益。要原样替换某张
      TLG6，请直接复用原字节（解码再编码会改变格式）。

    **注意**：解码端把图像首行的 alpha 固定成 0xff（GARbro/TVP 的实现），所以首行的
    alpha 目标值必须给 0xff，否则往返不成立。
    """
    if kind != KIND_TLG5:
        raise TlgError(
            f"不支持编码 {kind}：本库只出 TLG5。引擎两个变体都读，写入端统一 TLG5 即可；"
            f"要原样替换 {kind} 请直接复用原字节（见本模块 docstring「接口」）")
    if len(rgba) != width * height * 4:
        raise TlgError(f"像素长度与尺寸不符：{width}x{height} 需 {width*height*4} 字节，传了 {len(rgba)}")
    colors = 4
    nblocks = (height - 1) // blockheight + 1
    stride = width * 4
    bodies = bytearray()
    sizes = []
    text = bytearray(4096)
    r = 0
    y_blk = 0
    for _ in range(nblocks):
        start = len(bodies)
        rows = min(blockheight, height - y_blk)
        planes = [bytearray(rows * width) for _ in range(colors)]
        for y in range(rows):
            row_off = (y_blk + y) * stride
            o = y * width
            first = (y_blk + y) == 0
            prev = None if first else row_off - stride
            acc_b = acc_g = acc_r = acc_a = 0
            for x in range(width):
                p = row_off + x * 4
                R, G, B, A = rgba[p], rgba[p + 1], rgba[p + 2], rgba[p + 3]
                if first:
                    # 解码端首行：B/G/R 从 0 累加，alpha 硬写 0xff
                    pr = pg = pb = 0
                else:
                    q = prev + x * 4
                    pr, pg, pb = rgba[q], rgba[q + 1], rgba[q + 2]
                c_b = (B - pb) & 0xFF
                c_g = (G - pg) & 0xFF
                c_r = (R - pr) & 0xFF
                i_b = (c_b - acc_b) & 0xFF
                i_g = (c_g - acc_g) & 0xFF
                i_r = (c_r - acc_r) & 0xFF
                acc_b, acc_g, acc_r = c_b, c_g, c_r
                planes[0][o + x] = (i_b - i_g) & 0xFF   # B 平面（TLG 内部 BGRA）
                planes[1][o + x] = i_g                  # G 平面
                planes[2][o + x] = (i_r - i_g) & 0xFF   # R 平面
                if first:
                    c_a = A & 0xFF                      # 首行 alpha 基准是 0
                else:
                    c_a = (A - rgba[prev + x * 4 + 3]) & 0xFF
                i_a = (c_a - acc_a) & 0xFF
                acc_a = c_a
                planes[3][o + x] = i_a
        for c in range(colors):
            payload, r = compress_slide_simple(bytes(planes[c]), text, r)
            bodies += bytes([0]) + struct.pack("<I", len(payload)) + payload
        sizes.append(len(bodies) - start)
        y_blk += rows

    head = bytearray(TLG5_SIG)
    head.append(colors)
    head += struct.pack("<III", width, height, blockheight)
    head += b"".join(struct.pack("<I", s) for s in sizes)
    return bytes(head) + bytes(bodies)


def compress_slide_simple(plane: bytes, text: bytearray, r: int) -> tuple[bytes, int]:
    """把一段平面数据编成 TLG5 的 LZSS 流（贪心，3..273 字节匹配）。

    `text`/`r` 是跨平面、跨块复用的 4096 字节滑窗状态，调用方负责传回。
    匹配允许与自己重叠（解码端是逐字节复制，天然支持 run-length）。
    """
    n = len(plane)
    out = bytearray()
    index: dict[int, list[int]] = {}
    flags = 0
    flagpos = -1
    bit = 0
    i = 0
    while i < n:
        if bit == 0:
            flagpos = len(out)
            out.append(0)
        best_len = 0
        best_dist = 0
        if i + 3 <= n:
            key = plane[i] | (plane[i + 1] << 8) | (plane[i + 2] << 16)
            cands = index.get(key)
            if cands:
                for cand in reversed(cands[-48:]):
                    dist = i - cand
                    if dist <= 0 or dist > 4095:
                        continue
                    maxlen = min(18 + 255, n - i)
                    ln = 0
                    while ln < maxlen and plane[cand + ln] == plane[i + ln]:
                        ln += 1
                        if cand + ln > i:      # 重叠部分：解码端逐字节复制仍然成立
                            continue
                    if ln > best_len:
                        best_len = ln
                        best_dist = dist
                        if ln >= maxlen:
                            break
        if best_len >= 3:
            mpos = (r - best_dist) & 0xFFF
            if best_len >= 18:          # nibble 15 是「扩展长度」标记，真实长度-18 另存 1 字节
                nib = 15
                extra = best_len - 18
            else:
                nib = best_len - 3
                extra = None
            out.append(mpos & 0xFF)
            out.append(((mpos >> 8) & 0x0F) | (nib << 4))
            if extra is not None:
                out.append(extra)
            flags |= 1 << bit
            for k in range(best_len):
                text[r] = plane[i + k]
                r = (r + 1) & 0xFFF
                j = i + k
                if j + 3 <= n:
                    kk = plane[j] | (plane[j + 1] << 8) | (plane[j + 2] << 16)
                    index.setdefault(kk, []).append(j)
            i += best_len
        else:
            out.append(plane[i])
            text[r] = plane[i]
            r = (r + 1) & 0xFFF
            if i + 3 <= n:
                kk = plane[i] | (plane[i + 1] << 8) | (plane[i + 2] << 16)
                index.setdefault(kk, []).append(i)
            i += 1
        bit += 1
        if bit == 8:
            out[flagpos] = flags
            flags = 0
            bit = 0
    if bit:
        out[flagpos] = flags
    return bytes(out), r
