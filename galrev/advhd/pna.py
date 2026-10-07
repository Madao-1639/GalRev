"""PNA（AdvHD 分层图像，PNAP 容器）读写器。

文件布局（全部小端序，经两部 AdvHD 游戏语料 550+ 文件、3962 条记录全量验证：
box_w/h 与内嵌 PNG IHDR 逐条一致、非哨兵记录的 `double 1.0` 标记逐条一致、
数据区恰好覆盖到文件尾）：

    +0x00  char[4]  "PNAP"
    +0x04  i32      表大小字段 = 44 * layer_count + 12（仅校验用，不是文件偏移）
    +0x08  i32      画布宽
    +0x0c  i32      画布高
    +0x10  i32      记录条数 layer_count
    +0x14  记录区   layer_count × 40 字节
    之后    数据区（起点 = 0x14 + 40 * layer_count），按记录顺序紧邻排列，
            每个非空数据块都是一张**完整的 PNG**（含签名与 IEND）

每条记录 10 × i32：

    +0x00  i32      u0：0 = 真实图层；1/2 = 动画帧组边界哨兵（无数据块）
    +0x04  i32      layer_id：0x34/0x39 引用的位置量 = layer_count-1-index；哨兵为 -1
    +0x08  i32      box_x（图层左上角，画布坐标）
    +0x0c  i32      box_y
    +0x10  i32      box_w（== 内嵌 PNG 的宽，写回硬不变量）
    +0x14  i32      box_h（== 内嵌 PNG 的高）
    +0x18  i32      reserved（观测样本恒 0）
    +0x1c  i32      `double 1.0` 标记低 32 位（真实图层恒 0）
    +0x20  i32      `double 1.0` 标记高 32 位（0x3FF00000）；哨兵两条全 0
    +0x24  i32      数据块字节数（0 = 该图层无数据）

⚠️ 引擎按**记录下标**取图层（0x39 的帧号就是下标）；脚本引用的 layer_id 是
**纯位置量**（= layer_count-1-index），不要用记录里存的 layer_id 字段集合去查
（个别文件不符，命中率非 100%）。`u0` 决定图层是"叠加层"还是"动画帧"：动画类
PNA 的图层是同一位置的帧序列，**不要把所有图层叠成一张图看**。

写回（`serialize`）的硬不变量：
- 记录表的 box_w/box_h 必须与该图层 `data` 内嵌 PNG 的 IHDR 一致（原档即如此，换图后必须维持）；
- 记录条数不变；
- `serialize(parse(blob)) == blob` 逐字节往返一致是第一道闸。
`scanned=True`（记录表未覆盖全文件）的 PNA **不支持**重序列化：数据区尾部的未解释
字节机制未查明，重排数据区可能破坏它 —— 报 `PnaError`，不猜。

少数 PNA（如系统界面的 `SYS_GalleryBrowser.pna`、`Sys_Msw.pna`）在记录表描述的
最后一个数据块之后还有一段既非 PNG 也无表结构的字节，随后才是若干张 PNG（数量比
记录表多）。对这些文件回退为 PNG 签名扫描（`png_spans`），额外图层按出现顺序全部
取出，跳过的字节区间记在 `Pna.holes` 里，不静默丢弃。

── 与两个来源实现的关系 ─────────────────────────────────────────────
本模块合并自两个补丁项目的两版 PNA 工具，两版对**同一段字节**给出两种切法：
一版把头部当 36 字节、记录从 0x24 起按 40 字节对齐、并声称"最后一条记录只有
24 字节"；另一版把头部当 20 字节、记录从 0x14 起按 40 字节对齐。两种切法都恰好
逐字节往返一致（覆盖的字节区间相同），但**只有 0x14 起的切法语义自洽**：0x24 切法
把每条记录的 box_x/y 读到了**下一条记录**头上、把 `double 1.0` 标记的高 32 位当成
"f32 1.875 不透明度"、并虚构出"最后一条记录缺尾随 16 字节"的结论（实测单图层
PNA 的贴图位置就存在头部第 3、4 个未知字段里，0x24 切法对此无解释）。本模块采用
0x14 切法为唯一布局，一版的健壮性（PNG 校验、签名扫描回退、holes、严格报错）与
另一版的图层操作 API（find_by_layer_id/get_box/replace_layer）都落在这个布局上；
旧"0x24 头 + 末条 24 字节"的 parse/load 实现不再保留。
"""
import struct
from pathlib import Path

MAGIC = b'PNAP'
PNG_SIG = b'\x89PNG\r\n\x1a\n'

HEADER_SIZE = 0x14
ENTRY_SIZE = 40

ENTRY = struct.Struct('<10i')

U0_SENTINELS = (1, 2)


class PnaError(ValueError):
    pass


class Layer(object):
    """一条图层记录。`data` 为 None 表示该图层无数据块（空图层/哨兵）。

    `reserved` / `marker_lo` / `marker_hi` 是记录 +0x18/+0x1c/+0x20 的原始字段
    （serialize 逐字段重建记录表，必须带着它们才能逐字节保真）。"""

    __slots__ = ('index', 'u0', 'layer_id', 'x', 'y', 'width', 'height',
                 'reserved', 'marker_lo', 'marker_hi', 'size', 'offset', 'data')

    def __init__(self, index, u0, layer_id, x, y, width, height,
                 reserved, marker_lo, marker_hi, size, offset, data):
        self.index = index
        self.u0 = u0
        self.layer_id = layer_id
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.reserved = reserved
        self.marker_lo = marker_lo
        self.marker_hi = marker_hi
        self.size = size
        self.offset = offset
        self.data = data

    @property
    def is_sentinel(self):
        return self.u0 in U0_SENTINELS

    def __repr__(self):
        return '<Layer %d lid=%d %dx%d @(%d,%d) size=%d%s>' % (
            self.index, self.layer_id, self.width, self.height, self.x, self.y,
            self.size, ' sentinel' if self.is_sentinel else
            ('' if self.data else ' empty'))


class Pna(object):
    __slots__ = ('path', 'width', 'height', 'count', 'layers', 'data_start',
                 'scanned', 'holes', 'table_size_field')

    def __init__(self, path, width, height, count, layers, data_start, scanned,
                 holes=(), table_size_field=None):
        self.path = path
        self.width = width            # 画布宽
        self.height = height          # 画布高
        self.count = count            # 记录表条目数
        self.layers = layers
        self.data_start = data_start
        self.scanned = scanned        # True = 记录表未覆盖全文件，图层由签名扫描得出
        self.holes = holes            # 数据区中不含 PNG 的字节区间 [(start, size), ...]
        self.table_size_field = table_size_field   # +0x04 的原始 i32（= 44*count+12）

    @property
    def png_layers(self):
        return [l for l in self.layers if l.data is not None]


def _png_span_size(blob, start):
    """从签名处走 PNG chunk 链到 IEND，返回整块长度；结构不合法返回 None。"""
    p = start + 8
    while p + 8 <= len(blob):
        length, = struct.unpack_from('>I', blob, p)
        ctype = blob[p + 4:p + 8]
        p += 12 + length
        if p > len(blob):
            return None
        if ctype == b'IEND':
            return p - start
    return None


def png_spans(blob, start=0):
    """扫描内嵌 PNG 的 (offset, size)，按出现顺序。size 含签名与 IEND。"""
    spans = []
    pos = start
    while True:
        i = blob.find(PNG_SIG, pos)
        if i < 0:
            break
        size = _png_span_size(blob, i)
        if size is None:
            pos = i + 8
            continue
        spans.append((i, size))
        pos = i + size
    return spans


def _scanned_layers(blob, data_start, path):
    """记录表覆盖不全时的回退：图层全部由签名扫描得出。

    少数 PNA 在记录表描述的最后一个数据块之后还有一段既非 PNG 也无表结构的字节，
    随后才是若干张 PNG（数量比记录表多）。这些额外图层的来源机制未查明，这里按
    出现顺序全部取出，并把跳过的字节区间记在 `Pna.holes` 里，不静默丢弃。
    """
    spans = png_spans(blob, data_start)
    if not spans:
        raise PnaError('%s: 数据区未找到任何 PNG' % path)
    if spans[0][0] != data_start:
        raise PnaError('%s: 数据区起点 0x%x 处不是 PNG' % (path, data_start))
    holes = []
    layers = []
    end = data_start
    for k, (off, size) in enumerate(spans):
        if off > end:
            holes.append((end, off - end))
        end = off + size
        w, h = struct.unpack_from('>II', blob, off + 16)
        layers.append(Layer(k, None, None, None, None, w, h,
                            None, None, None, size, off, blob[off:off + size]))
    if end < len(blob):
        holes.append((end, len(blob) - end))
    return layers, holes


def read(path):
    """解析 PNA 文件，返回 Pna。"""
    return parse(Path(path).read_bytes(), path=str(path))


def parse(blob, path='<bytes>'):
    if blob[:4] != MAGIC:
        raise PnaError('%s: 不是 PNA 文件（magic=%r）' % (path, blob[:4]))
    table_size_field, width, height, count = struct.unpack_from('<iiii', blob, 4)
    if table_size_field != 44 * count + 12:
        raise PnaError('%s: 表大小字段 %d != 44*layer_count+12 = %d'
                       '（引擎版本差异？不要盲目录取）' % (path, table_size_field, 44 * count + 12))
    data_start = HEADER_SIZE + ENTRY_SIZE * count
    if count <= 0 or data_start > len(blob):
        raise PnaError('%s: 记录表越界（layer_count=%d）' % (path, count))

    layers = []
    off = data_start
    for k in range(count):
        u0, lid, x, y, w, h, res, mlo, mhi, size = ENTRY.unpack_from(blob, HEADER_SIZE + ENTRY_SIZE * k)
        data = None
        if size:
            if off + size > len(blob):
                raise PnaError('%s: 图层 %d 数据越界（%d+%d > %d）'
                               % (path, k, off, size, len(blob)))
            data = blob[off:off + size]
            if data[:8] != PNG_SIG:
                raise PnaError('%s: 图层 %d 的数据块不是 PNG' % (path, k))
            off += size
        layers.append(Layer(k, u0, lid, x, y, w, h, res, mlo, mhi,
                            size, off - size if size else None, data))

    if off != len(blob):
        # 记录表没覆盖到文件尾：改用签名扫描，保证不丢图层。
        layers, holes = _scanned_layers(blob, data_start, path)
        return Pna(path, width, height, count, layers, data_start, True, holes)

    return Pna(path, width, height, count, layers, data_start, False,
               table_size_field=table_size_field)


def serialize(p):
    """把 `parse` 出的 Pna 重序列化为字节。头部与记录表逐字段重建、数据区按记录
    顺序拼接非空图层的 PNG —— 对未改动的 PNA 逐字节保真。

    替换图层时由调用方改 `Layer` 的 `data` / `size` / `width` / `height`（或用
    `replace_layer`）；**记录表的 box_w/box_h 必须与 data 内嵌 PNG 的 IHDR 一致**
    （写回的硬不变量，见模块 docstring）。`scanned=True` 的 PNA 报 `PnaError` ——
    数据区尾部未解释字节机制未查明，不猜。"""
    if p.scanned:
        raise PnaError('%s: 记录表未覆盖全文件（签名扫描件），不支持重序列化' % p.path)
    out = bytearray()
    out += MAGIC
    out += struct.pack('<iiii', p.table_size_field, p.width, p.height, p.count)
    for l in p.layers:
        out += ENTRY.pack(l.u0, l.layer_id, l.x, l.y, l.width, l.height,
                          l.reserved, l.marker_lo, l.marker_hi, l.size)
    for l in p.layers:
        if l.data is not None:
            out += l.data
    return bytes(out)


def png_dimensions(data):
    """校验 `data` 是一张**完整**的 PNG（签名 + chunk 链到 IEND 且无尾随字节），
    返回 (宽, 高)；否则抛 `PnaError`。供换图前验证替换图。"""
    if data[:8] != PNG_SIG:
        raise PnaError('不是 PNG（签名=%r）' % data[:8])
    size = _png_span_size(data, 0)
    if size is None:
        raise PnaError('PNG chunk 链结构不合法（走不到 IEND）')
    if size != len(data):
        raise PnaError('PNG 不完整或有尾随字节（IEND 在 %d / 共 %d 字节）' % (size, len(data)))
    w, h = struct.unpack_from('>II', data, 16)
    return w, h


def find_by_layer_id(p, layer_id):
    """返回 layer_id 对应、且有图像数据的图层（Layer）。

    引擎引用的 layer_id 是**纯位置量**（= layer_count-1-index），因此按位置规则
    取记录；命中哨兵（layer_id 存 -1、无数据）或越界时报 `PnaError`。个别文件的
    存储 layer_id 字段与位置规则不符，故**不按存储字段查**。
    """
    idx = p.count - 1 - layer_id
    if not 0 <= idx < p.count:
        raise PnaError('%s: layer_id %d 越界（layer_count=%d）' % (p.path, layer_id, p.count))
    l = p.layers[idx]
    if l.data is None:
        raise PnaError('%s: layer_id %d（记录下标 %d）无图像数据'
                       % (p.path, layer_id, idx))
    return l


def get_box(p, idx):
    """第 idx 条记录的贴图矩形 (x, y, w, h)。"""
    l = p.layers[idx]
    return (l.x, l.y, l.width, l.height)


def replace_layer(p, layer_id, png_bytes, box=None):
    """把 `layer_id` 的图像替换为 `png_bytes`（就地改 Layer，随后由调用方 serialize）。

    `png_bytes` 必须是一张完整 PNG（`png_dimensions` 校验）；记录表的 box_w/box_h
    随新图的 IHDR 更新（硬不变量）。`box` 为 (x, y) 时更新图层左上角锚点；
    不传则保持原锚点。
    """
    l = find_by_layer_id(p, layer_id)
    w, h = png_dimensions(png_bytes)
    l.data = png_bytes
    l.size = len(png_bytes)
    l.width = w
    l.height = h
    if box is not None:
        l.x, l.y = box
    return l
