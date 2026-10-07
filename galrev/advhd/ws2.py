"""AdvHD .ws2 script codec: rot6 de/obfuscation, reference extractors and
achievement-id primitives.

Obfuscation is a per-byte rotate-left-6 (verified: round-trips byte-exactly,
and exposes ASCII opcode operands such as script names and CG filenames).

Relevant opcodes (operand forms confirmed against story-script corpora of
AdvHD-engine games):

    0x34  <slot>\\0 <FILE.PNA>\\0 0x01 0x01     display a CG into a layer slot
    0x33  <slot>\\0 <FILE.PNG>\\0 0x01 0x01     hard-load resource (background)
    0x66  ...                                  effect mask (tolerates missing)
    0x0b  <u16 var> 0x01                       push/set a variable
    0x04  <NAME>\\0                             call another script by name
    0x07  <NAME>\\0                             jump to another script (no return)

A CG display (0x34) is always followed by two 0x0b variable-set ops carrying
the CG's gallery id and differential id. Those two ops exist in BOTH the Steam
and the original scripts -- they are intrinsic to displaying a CG, not part of
the achievement feature. Byte-diffing the same scene in both versions shows the
Steam build adds exactly 16 bytes after the pair:

    ...0101  0b <u16 A> 04 01  0b <u16 B> 04 01  [04 "CG_ACHIEVEMENT" 00]  39...
             |<------- present in both versions ------->|  |<- Steam only ->|

So achievement injection means inserting only the 16-byte call after the
existing variable pair -- never re-emitting the pair, whose operands must be
left untouched.

⚠️ **id 对挂在哪种显示指令上是语料前提，换语料先核**：`DISPLAY` 认的是
「`0x34` PNA 显示 + 紧随的 id 对」，这在该显示方式为「事件 CG 走 PNA 进 ev 槽」的
语料上成立；在事件 CG 以 `0x33` 压 PNG 显示的语料（如 CROSS†CHANNEL，实测 id 对
紧随 `0x33` PNG 显示、`0x34` 后 0 例）上，`DISPLAY`/`find_display_sites` 会返回
空 —— 此时把同样的模式对准 `0x33`（`DISPLAY_PNG` 后接 id 对）即可。

⚠️ **本模块的正则只认 ASCII 资源名**：`DISPLAY`/`DISPLAY_PNA`/`DISPLAY_PNG` 的资源名字符集
是 `[A-Za-z0-9_]`，含 Shift-JIS 日文名的 PNA（如 `Dころな_01L.PNA`、`Aひかり_01M.PNA`）
**匹配不到**。全量、与编码无关的资源引用/指令扫描请用 galrev.advhd.ws2disasm。
同理 `CALL`/`JUMP` 只认大写 ASCII 脚本名（引擎原生如此）。

⚠️ **本模块刻意不提供 inject()**：裸字节拼接插入成就调用而不重定位
`0x01`/`0x02`/`0x06` 的文件内绝对偏移，在含条件/跳转的脚本上已被证明不安全
（跳转目标落到指令中间）。注入的完整工程要求（偏移重定位 + 四条强不变式自检）
见 docs/engines/advhd/steam-achievements.md；偏移重写原语见 galrev.advhd.ws2patch。
"""
import re
import struct

ACH_NAME = b'CG_ACHIEVEMENT'
ACH_CALL = b'\x04' + ACH_NAME + b'\x00'

# 0x34 <slot> 00 <STEM>.PNA 00 01 01 followed by the intrinsic id pair.
# Each set op is four bytes: 0b <u16 le> 01  (e.g. 0b 60 04 01 -> var 1120).
DISPLAY = re.compile(
    rb'\x34([A-Za-z0-9_]{2,12})\x00([A-Za-z0-9_]+)\.PNA\x00\x01\x01'
    rb'\x0b(..)\x01\x0b(..)\x01', re.S)

# 0x34 <slot> 00 <STEM>.PNA 00 01 01
DISPLAY_PNA = re.compile(
    rb'\x34([A-Za-z0-9_]{1,12})\x00([A-Za-z0-9_]+)\.PNA\x00\x01\x01', re.I)

# 0x33 <slot> 00 <FILE>.PNG 00 01 01
DISPLAY_PNG = re.compile(
    rb'\x33([A-Za-z0-9_]{1,12})\x00([A-Za-z0-9_]+)\.PNG\x00\x01\x01', re.I)

# 0x04 <NAME> 00 (call)
CALL = re.compile(rb'\x04([A-Z0-9_]+)\x00')

# 0x07 <NAME> 00 (jump)
JUMP = re.compile(rb'\x07([A-Z0-9_]+)\x00')

SIZE_SUFFIX = re.compile(r'[LSMWX]$')


def decode(raw):
    """Deobfuscate a .ws2 member (rotate left 6)."""
    return bytes(((c << 6) | (c >> 2)) & 0xff for c in raw)


def encode(data):
    """Re-obfuscate a .ws2 member (inverse: rotate right 6 == left 2)."""
    return bytes(((c << 2) | (c >> 6)) & 0xff for c in data)


def extract_pna_refs(decoded_data):
    """Extract all PNA file stems referenced in decoded script (ASCII names only)."""
    return [m.group(2).decode('ascii') for m in DISPLAY_PNA.finditer(decoded_data)]


def extract_png_refs(decoded_data):
    """Extract all PNG file names referenced in decoded script (ASCII names only)."""
    return [m.group(2).decode('ascii') for m in DISPLAY_PNG.finditer(decoded_data)]


def extract_calls(decoded_data):
    """Extract all script names called via 0x04 (call)."""
    return [m.group(1).decode('ascii') for m in CALL.finditer(decoded_data)]


def extract_jumps(decoded_data):
    """Extract all script names jumped to via 0x07 (jump)."""
    return [m.group(1).decode('ascii') for m in JUMP.finditer(decoded_data)]


def extract_all_jumps(decoded_data):
    """Extract all script jumps (both call and jump)."""
    return extract_calls(decoded_data) + extract_jumps(decoded_data)


def cg_base(stem):
    """COM_04L -> COM_04 (strip the size-variant suffix)."""
    return SIZE_SUFFIX.sub('', stem)


def read_id_map(members):
    """Extract {cg_base: (A, {B...})} from the intrinsic id pair of each display.

    members: iterable of (name, raw_ws2_bytes). Read from the original scripts
    as readily as from Steam's: the pair is present in both, so no achievement
    ids ever need to be invented.
    """
    a_of = {}
    b_of = {}
    for name, raw in members:
        data = decode(raw)
        for m in DISPLAY.finditer(data):
            base = cg_base(m.group(2).decode('ascii'))
            a_of[base] = struct.unpack('<H', m.group(3))[0]
            b_of.setdefault(base, set()).add(
                struct.unpack('<H', m.group(4))[0])
    return a_of, b_of


def find_display_sites(data):
    """Yield (end_offset, cg_base, has_call) for every CG display op.

    end_offset points just past the intrinsic id pair, which is exactly where
    the achievement call belongs.
    """
    for m in DISPLAY.finditer(data):
        has_call = data[m.end():m.end() + len(ACH_CALL)] == ACH_CALL
        yield m.end(), cg_base(m.group(2).decode('ascii')), has_call
