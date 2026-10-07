"""WillPlus 老式归档（旧引擎 Arc）读取。

与 AdvHD（Steam 系）的 Arc 格式完全不同：条目为 **21 字节定长**（13 字节文件名 + u32
大小 + u32 绝对偏移），名字按类型表分组、**不含扩展名**（扩展名即类型名），名字编码是
**ASCII/Shift-JIS** 而非 UTF-16LE。两代格式不可互读，见 docs/engines/willplus/file-formats.md。
"""
import struct
from pathlib import Path


def read_old_arc(path):
    """读取 WillPlus 老式归档，返回 [(name_bytes, data)]。

    结构（类型表 + 21 字节定长条目区）：

        [u32 类型数]
        n × [4B 类型名][u32 该类文件数][u32 条目区起始偏移]
        条目: 13B 文件名 + u32 大小 + u32 绝对偏移（绝对偏移，直接指向文件内数据）

    返回 [(name_bytes, data)]，名字形如 b'CCC0000.WSC'（原名 + '.' + 类型名）。

    ⚠️ 名字是 **ASCII**（部分游戏允许 Shift-JIS 字符），要用 `.decode('shift_jis')` 或
    `ascii` 解。**不要用 `utf-16-le`** —— 它会**静默**把偶数长度的名字解成乱码
    （`b'ABCD0001.OGG'` → 成对汉字乱码），**不抛异常**；实测语料中上千条目会因此
    "看不见"（偶数长度名字全部静默解坏，且越长的名字越难被人工抽查发现）。
    """
    blob = Path(path).read_bytes()
    n_types, = struct.unpack_from('<I', blob, 0)
    off = 4
    types = []
    for _ in range(n_types):
        tname = blob[off:off + 4].rstrip(b'\x00')
        cnt, start = struct.unpack_from('<II', blob, off + 4)
        types.append((tname, cnt, start))
        off += 12
    out = []
    for tname, cnt, start in types:
        p = start
        for _ in range(cnt):
            name = blob[p:p + 13].split(b'\x00')[0]
            size, foff = struct.unpack_from('<II', blob, p + 13)
            data = blob[foff:foff + size]
            if len(data) != size:
                raise ValueError('truncated member %r in %s' % (name, path))
            out.append((name + b'.' + tname, data))
            p += 21
    return out
