"""最小 TTF/OTF `name` 表读取（纯标准库，不依赖 fontTools）。

用途：核对"Lua 请求的族名"与"字体内部族名"是否一致 —— AdvHD 系引擎按 GDI 族名选面，
两者不一致就掉兜底字体（表现是字体"没换成功"）。见 docs/engines/advhd/localization.md「字体」。

只解析 name 表，返回 {(platformID, langID): {nameID: str}}；`family_key()` 取
platformID=3 的常用记录（id1 族名 / id2 子族 / id4 全名 / id6 PostScript 名 /
id16 排版族名 / id17 排版子族）。
"""
import struct


class TtfError(ValueError):
    pass


def _tables(blob):
    if len(blob) < 12:
        raise TtfError('文件过短')
    if blob[:4] == b'ttcf':
        raise TtfError('TrueType Collection（TTC）不支持，请先取出单个字体')
    if blob[:4] not in (b'\x00\x01\x00\x00', b'OTTO', b'true'):
        raise TtfError('不是 TTF/OTF（magic=%r）' % blob[:4])
    num = struct.unpack_from('>H', blob, 4)[0]
    out = {}
    off = 12
    for _ in range(num):
        tag, _sum, offset, length = struct.unpack_from('>4sIII', blob, off)
        off += 16
        out[tag] = (offset, length)
    return out


def names(blob):
    """→ {(platformID, langID): {nameID: str}}"""
    tabs = _tables(blob)
    if b'name' not in tabs:
        raise TtfError('没有 name 表')
    base, _ = tabs[b'name']
    _fmt, count, str_off = struct.unpack_from('>HHH', blob, base)
    out = {}
    for i in range(count):
        pid, eid, lid, nid, length, off = struct.unpack_from('>HHHHHH', blob, base + 6 + i * 12)
        raw = blob[base + str_off + off: base + str_off + off + length]
        try:
            text = raw.decode('utf-16-be') if pid in (0, 3) else raw.decode('latin-1')
        except UnicodeDecodeError:
            continue
        out.setdefault((pid, lid), {})[nid] = text
    return out


def family_key(blob, ids=(1, 2, 4, 6, 16, 17), lang=0x411):
    """取 platformID=3 的关键 name 记录；没有该语言时退回 0x409，再退回第一条。"""
    grouped = {k: v for k, v in names(blob).items() if k[0] == 3}
    pick = grouped.get((3, lang)) or grouped.get((3, 0x409)) or (next(iter(grouped.values())) if grouped else {})
    return {i: pick[i] for i in ids if i in pick}


def families(blob):
    """字体可能被 GDI 认作族名的全部候选（id1 / id4 / id16 去重）。"""
    key = family_key(blob)
    out = []
    for i in (1, 4, 16):
        v = key.get(i)
        if v and v not in out:
            out.append(v)
    return out


def matches_requested(blob, requested):
    """`requested`（Lua 里写的族名）能否被该字体命中（任一候选逐字相等）。"""
    return requested in families(blob)
