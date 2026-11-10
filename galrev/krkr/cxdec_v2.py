"""KiriKiri「Cxdec V2」内容解密层（新版 `cxdec` 插件，M2 第 5 作起）。

与 `galrev.krkr.cx`（初代 Cx）是**同一套内容加密的二代**：

* 容器仍是不变（XP3 的 Cx 变体：`0x17` 处 `0x80`、真索引偏移在 `0x20`、索引明文、条目内容加密）；
* 密钥输入仍是条目 `adlr`（= 明文 adler32），密钥形状仍是 `(key64_a, key64_b, base_offset)`；
* **XOR 算式完全一样** —— 直接用 `galrev.krkr.cx.crypt_stream`，本模块不重复实现。

变的是**密钥怎么算**：

    exe 的 .rdata 里内嵌一个 PE（插件），V2Link 里用 TVPSetXP3ArchiveExtractionFilter
    注册 XP3 内容过滤器；参数（PARAMS / TABLE）就存在这个模块镜像里，程序则是运行时生成的
    （128 条 lane，seed = lane 索引，LCG），所以静态复现代价很高。

本模块因此把「取密钥」外包给插件本体：

1. `extract_embedded_module(exe)` —— 把内嵌 PE 解出来；
2. `Scheme.from_module(...)` / `Scheme.from_json(...)` —— 读 PARAMS/TABLE 与插件内部地址；
3. `derive_keys(scheme, module, adlrs)` —— 在 32 位宿主进程里加载模块，调它的求值函数，
   一次性得到每条目 `(key64_a, key64_b, base_offset)`；
4. `decrypt(keys, adlr, data)` —— 纯 Python 走 `cx.crypt_stream`。

密钥只与 `adlr` 有关，可以缓存成 JSON（`save_keys` / `load_keys`）；缓存命中后整个流程是纯 Python。

**不内嵌任何一部游戏的标定值**：mask/offset/orders/control_block 与插件内部 RVA 都必须由调用方
以 profile 注入（见 `docs/engines/krkr/cx-crypto.md` §7）。RVA 随构建变化，换版本要重新标定。
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import zlib

from . import cx

M32 = 0xFFFFFFFF

# ------------------------------------------------------------------ PE / 模块


def _pe_sections(buf: bytes):
    """返回 `(image_base, [(名字, vaddr, vsize, raddr, rsize), ...])`。"""
    if buf[:2] != b"MZ":
        raise ValueError("不是 PE 文件")
    pe = struct.unpack_from("<I", buf, 0x3C)[0]
    if buf[pe:pe + 4] != b"PE\0\0":
        raise ValueError("PE 签名不符")
    nsec = struct.unpack_from("<H", buf, pe + 6)[0]
    optsz = struct.unpack_from("<H", buf, pe + 20)[0]
    image_base = struct.unpack_from("<I", buf, pe + 24 + 28)[0]
    base = pe + 24 + optsz
    secs = []
    for i in range(nsec):
        o = base + i * 40
        name = buf[o:o + 8].rstrip(b"\0").decode("latin-1")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", buf, o + 8)
        secs.append((name, vaddr, vsize, raddr, rsize))
    return image_base, secs


def _image_bytes(module: bytes) -> bytes:
    """按节表把 PE 摊成内存镜像（RVA 地址空间），便于按 RVA 定位数据。"""
    _image_base, secs = _pe_sections(module)
    size = max(vaddr + vsize for _n, vaddr, vsize, _r, _rs in secs)
    img = bytearray(size)
    for _n, vaddr, _vsize, raddr, rsize in secs:
        img[vaddr:vaddr + rsize] = module[raddr:raddr + rsize]
    return bytes(img)


def extract_embedded_module(exe_path: str) -> bytes:
    """从游戏 exe 的 `.rdata` 里解出内嵌插件模块（32 位 PE）。

    M2 packer 的布局：`"module\\0"` 起 16 字节名字槽 + u16(解压后长度/256) + 1 字节 0 +
    u32(zlib 长度) + zlib 流；解出来以 `MZ` 开头。
    """
    with open(exe_path, "rb") as fp:
        buf = fp.read()
    _image_base, secs = _pe_sections(buf)
    for name, _vaddr, _vsize, raddr, rsize in secs:
        if name != ".rdata":
            continue
        seg = buf[raddr:raddr + rsize]
        pos = seg.find(b"module\0")
        while pos >= 0:
            for z in range(pos + 16, min(pos + 34, len(seg) - 4)):
                if seg[z] == 0x78 and seg[z + 1] in (0x01, 0x5E, 0x9C, 0xDA):
                    zsize = struct.unpack_from("<I", seg, z - 4)[0]
                    if not 0x100 < zsize <= len(seg) - z:
                        continue
                    try:
                        raw = zlib.decompress(seg[z:z + zsize])
                    except zlib.error:
                        continue
                    if raw[:2] == b"MZ":
                        return raw
            pos = seg.find(b"module\0", pos + 1)
    raise ValueError(f"{exe_path} 的 .rdata 里没有内嵌插件模块")


# -------------------------------------------------------------------- 参数


class Scheme:
    """一份 Cxdec V2 方案：PARAMS + TABLE + 插件内部地址（每作/每构建一组，由调用方注入）。"""

    def __init__(self, mask: int, offset: int, flags: int,
                 even_branch_order, odd_branch_order, prolog_order, control_block,
                 module_name: str = "cxdec.tpm.dll", filter_rvas: dict | None = None,
                 game: str = "", notes: str = "", source: str = ""):
        self.mask = mask & M32
        self.offset = offset & M32
        self.flags = flags
        self.even_branch_order = list(even_branch_order)
        self.odd_branch_order = list(odd_branch_order)
        self.prolog_order = list(prolog_order)
        self.control_block = list(control_block)
        self.module_name = module_name
        self.filter_rvas = dict(filter_rvas or {})
        self.game = game
        self.notes = notes
        self.source = source
        self._check()

    def _check(self) -> None:
        for name, n in (("even_branch_order", 8), ("odd_branch_order", 6), ("prolog_order", 3)):
            vals = getattr(self, name)
            if sorted(vals) != list(range(n)):
                raise ValueError(f"{name} 不是 0..{n - 1} 的排列: {vals}")
        if len(self.control_block) < 1024:
            raise ValueError(f"control_block 太短: {len(self.control_block)} < 1024")

    # ---- JSON
    @classmethod
    def from_json(cls, path: str) -> "Scheme":
        with open(path, encoding="utf-8") as fp:
            prof = json.load(fp)
        return cls(
            mask=prof["mask"], offset=prof["offset"], flags=prof.get("flags", 0),
            even_branch_order=prof["even_branch_order"],
            odd_branch_order=prof["odd_branch_order"],
            prolog_order=prof["prolog_order"],
            control_block=prof["control_block"],
            module_name=prof.get("module", {}).get("name", "cxdec.tpm.dll"),
            filter_rvas={k: int(v, 16) if isinstance(v, str) else int(v)
                         for k, v in prof.get("module", {}).get("filter_rvas", {}).items()},
            game=prof.get("game", ""), notes=prof.get("notes", ""),
            source=prof.get("source", ""),
        )

    def to_json(self) -> dict:
        return {
            "game": self.game,
            "notes": self.notes,
            "mask": self.mask,
            "offset": self.offset,
            "flags": self.flags,
            "even_branch_order": self.even_branch_order,
            "odd_branch_order": self.odd_branch_order,
            "prolog_order": self.prolog_order,
            "control_block": self.control_block,
            "module": {
                "name": self.module_name,
                "filter_rvas": {k: f"{v:#x}" for k, v in self.filter_rvas.items()},
            },
            "source": self.source,
        }

    # ---- 从模块镜像自描述解析
    @classmethod
    def from_module(cls, module: bytes, module_name: str | None = None,
                    filter_rvas: dict | None = None, game: str = "",
                    notes: str = "", source: str = "") -> "Scheme":
        """读模块自带的 `--data--PARAMS`（22 B）与 `TABLE`（4096 B）。

        PARAMS 布局：`[0:8]` even / `[8:14]` odd / `[14:17]` prolog（三者都是「按 form 索引」的
        排列）、`[17]` flags（bit7 = 用 MT19937 而非 LCG）、`[18:20]` mask、`[20:22]` offset。
        `TABLE` 是控制块**原表**（1024 × u32）。
        """
        img = _image_bytes(module)
        p = img.find(b"--data--PARAMS")
        if p < 0:
            raise ValueError("模块里找不到 --data--PARAMS")
        n = struct.unpack_from("<H", img, p + 15)[0]
        payload = img[p + 17:p + 17 + n]
        t = img.find(b"TABLE\0", p + 17 + n)
        if t < 0:
            raise ValueError("模块里找不到 TABLE")
        tlen = struct.unpack_from("<H", img, t + 6)[0]
        table = img[t + 8:t + 8 + tlen]
        if len(table) < 0x1000:
            raise ValueError(f"TABLE 长度异常: {tlen}")
        if len(payload) < 22:
            raise ValueError(f"PARAMS 长度异常: {n}")
        mask, offset = struct.unpack_from("<HH", payload, 18)
        return cls(
            mask=mask, offset=offset, flags=payload[17],
            even_branch_order=payload[0:8],
            odd_branch_order=payload[8:14],
            prolog_order=payload[14:17],
            control_block=struct.unpack_from("<1024I", table, 0),
            module_name=module_name or "cxdec.tpm.dll",
            filter_rvas=filter_rvas, game=game, notes=notes, source=source,
        )

    def __repr__(self) -> str:
        return (f"Scheme(mask={self.mask:#x}, offset={self.offset:#x}, flags={self.flags:#04x}, "
                f"even={self.even_branch_order}, odd={self.odd_branch_order}, "
                f"prolog={self.prolog_order})")


# ------------------------------------------------- 调插件本体求每条目的密钥

_PS_TEMPLATE = r"""
param([string]$Dll, [string]$Out, [string]$HashFile)
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class K32 {
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Ansi)]
    public static extern IntPtr LoadLibraryA(string path);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern IntPtr VirtualAlloc(IntPtr addr, UIntPtr size, uint allocType, uint protect);
}
[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
public delegate int F2(int a, int b);
[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
public delegate int F3(int a, int b, int c);
"@
$h = [K32]::LoadLibraryA($Dll)
if ($h -eq [IntPtr]::Zero) { throw ("LoadLibrary failed: " + [Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
$base = $h.ToInt64()

$e = [Runtime.InteropServices.Marshal]::ReadInt32([IntPtr]($base + 0x3C))
$sizeOfImage = [Runtime.InteropServices.Marshal]::ReadInt32([IntPtr]($base + $e + 24 + 56))
$mem = [byte[]]::new($sizeOfImage)
[Runtime.InteropServices.Marshal]::Copy([IntPtr]$base, $mem, 0, $sizeOfImage)

function Find-Marker([byte[]]$needle, [int]$from) {
    for ($i = $from; $i -le $mem.Length - $needle.Length; $i++) {
        if ($mem[$i] -eq $needle[0]) {
            $ok = $true
            for ($j = 1; $j -lt $needle.Length; $j++) { if ($mem[$i+$j] -ne $needle[$j]) { $ok = $false; break } }
            if ($ok) { return $i }
        }
    }
    return -1
}

$p = Find-Marker ([System.Text.Encoding]::ASCII.GetBytes("--data--PARAMS")) 0
if ($p -lt 0) { throw "PARAMS marker not found" }
$plen = [BitConverter]::ToUInt16($mem, $p + 15)
$poff = $p + 17
$t = Find-Marker ([System.Text.Encoding]::ASCII.GetBytes("TABLE`0")) ($poff + $plen)
if ($t -lt 0) { throw "TABLE marker not found" }
$tlen = [BitConverter]::ToUInt16($mem, $t + 6)
$toff = $t + 8

$gParams = $base + __G_PARAMS__
$gFlag   = $base + __G_FLAG__
$gTable  = $base + __G_TABLE__
[Runtime.InteropServices.Marshal]::Copy($mem, $poff, [IntPtr]$gParams, 17)
[Runtime.InteropServices.Marshal]::WriteByte([IntPtr]$gFlag, [byte]($mem[$poff + 17] -shr 7))
$mask   = [BitConverter]::ToUInt16($mem, $poff + 18)
$offset = [BitConverter]::ToUInt16($mem, $poff + 20)
[Runtime.InteropServices.Marshal]::Copy($mem, $toff, [IntPtr]$gTable, $tlen)

$fnMask  = [Runtime.InteropServices.Marshal]::GetDelegateForFunctionPointer([IntPtr]($base + __SET_MASK__), [F2])
$fnBuild = [Runtime.InteropServices.Marshal]::GetDelegateForFunctionPointer([IntPtr]($base + __BUILD__), [F3])
$fnGen   = [Runtime.InteropServices.Marshal]::GetDelegateForFunctionPointer([IntPtr]($base + __GEN__), [F2])
[void]$fnMask.Invoke([int]$mask, [int]$offset)
$rc = $fnBuild.Invoke([int]$gTable, [int]$gParams, 0)
if ($rc -ne 0) { throw ("lane build failed: " + $rc) }

$buf = [K32]::VirtualAlloc([IntPtr]::Zero, [UIntPtr]::new(64), 0x3000, 0x04)
$sb = New-Object System.Text.StringBuilder
foreach ($line in Get-Content $HashFile) {
    $s = $line.Trim()
    if ($s -eq "") { continue }
    $hh = [BitConverter]::ToInt32([BitConverter]::GetBytes([Convert]::ToUInt32($s)), 0)
    [void]$fnGen.Invoke([int]$buf, $hh)
    $b = [byte[]]::new(40)
    [Runtime.InteropServices.Marshal]::Copy($buf, $b, 0, 40)
    [void]$sb.AppendLine(("{0} {1} {2} {3}" -f [BitConverter]::ToUInt32([BitConverter]::GetBytes([int32]$hh), 0),
        [BitConverter]::ToUInt64($b, 8), [BitConverter]::ToUInt64($b, 16), [BitConverter]::ToUInt32($b, 24)))
}
[IO.File]::WriteAllText($Out, $sb.ToString())
"""

_REQUIRED_RVAS = ("set_mask", "build", "gen", "g_params", "g_flag", "g_table")


def ps32_path() -> str:
    """Windows 自带的 32 位 PowerShell（插件是 32 位 PE，必须在 32 位进程里加载）。"""
    path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                        "SysWOW64", "WindowsPowerShell", "v1.0", "powershell.exe")
    if not os.path.exists(path):
        raise RuntimeError(f"找不到 32 位 PowerShell: {path}")
    return path


def derive_keys(scheme: Scheme, module: bytes, adlrs, workdir: str | None = None) -> dict:
    """调插件本体，为给定 `adlr` 集合求 `(key64_a, key64_b, base_offset)`。

    返回 `{adlr: (key64_a, key64_b, base_offset)}`。`scheme.filter_rvas` 必须齐备，
    且**随构建变化**（见 docs §7）。
    """
    missing = [k for k in _REQUIRED_RVAS if k not in scheme.filter_rvas]
    if missing:
        raise ValueError(f"filter_rvas 缺字段: {missing}")
    own_dir = workdir is None
    workdir = workdir or tempfile.mkdtemp(prefix="cxdec_v2_")
    try:
        dll_path = os.path.join(workdir, scheme.module_name)
        with open(dll_path, "wb") as fp:
            fp.write(module)
        hashes = sorted({int(h) & M32 for h in adlrs})
        hash_path = os.path.join(workdir, "hashes.txt")
        with open(hash_path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(str(h) for h in hashes) + "\n")
        out_path = os.path.join(workdir, "keys_raw.txt")
        ps_path = os.path.join(workdir, "dump_keys.ps1")
        src = _PS_TEMPLATE
        for key, rva in scheme.filter_rvas.items():
            src = src.replace(f"__{key.upper()}__", f"{rva:#x}")
        with open(ps_path, "w", encoding="utf-8") as fp:
            fp.write(src)
        res = subprocess.run([ps32_path(), "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", ps_path, "-Dll", dll_path,
                              "-Out", out_path, "-HashFile", hash_path],
                             capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"调插件取密钥失败（{res.returncode}）:\n{res.stdout}\n{res.stderr}")
        keys = {}
        with open(out_path, encoding="utf-8") as fp:
            for line in fp:
                t = line.split()
                if len(t) == 4:
                    h, k1, k2, base = (int(x) for x in t)
                    keys[h & M32] = (k1, k2, base)
        lack = [h for h in hashes if h not in keys]
        if lack:
            raise RuntimeError(f"{len(lack)} 条 adlr 没求到密钥，例: {[hex(h) for h in lack[:5]]}")
        return keys
    finally:
        if own_dir:
            shutil.rmtree(workdir, ignore_errors=True)


# ------------------------------------------------------------------ 密钥表


def load_keys(path: str) -> dict:
    """读密钥缓存：`{"0x...": (key64_a, key64_b, base_offset), ...}`。"""
    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)
    return {int(k, 16) & M32: tuple(int(x) for x in v) for k, v in raw.items()}


def save_keys(path: str, keys: dict) -> None:
    data = {f"{k:#010x}": list(v) for k, v in sorted(keys.items())}
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=0)
        fp.write("\n")


# ---------------------------------------------------------------- 解密本体


def adler32(data: bytes) -> int:
    """条目 `adlr`：**明文** adler32，既是校验哈希也是密钥输入。"""
    return zlib.adler32(data) & M32


def decrypt(keys: dict, adlr: int, data: bytes) -> bytes:
    """对一条目的完整明文流（已 zlib 解压、跨段已拼接）解密。

    密钥表给的是 `key64 = ret1 | (ret2 << 32)`；XOR 层与 Cx 完全一致，直接复用
    `cx.crypt_stream`（`[0, base_offset)` 用 a 段、其余用 b 段）。
    """
    key = adlr & M32
    if key not in keys:
        raise KeyError(f"密钥表里没有 adlr {key:#010x}")
    k1, k2, base = keys[key]
    return cx.crypt_stream(bytearray(data), base, (k1 & M32, k1 >> 32), (k2 & M32, k2 >> 32))


def encrypt(keys: dict, adlr: int, data: bytes) -> bytes:
    """加密与解密同一算式（XOR），单独留个名字让调用处可读。"""
    return decrypt(keys, adlr, data)


class KeyCrypt:
    """写端适配器：`crypt(adlr, data)`，可喂给归档写入器（`encrypt` 的同一算式）。

    密钥只能来自插件（见 `derive_keys`），所以这里只查表：缺 key 直接抛错，
    不做隐式补算 —— 打包端应先把所有 `adler32(明文)` 收齐、一次性取密钥再写包。
    """

    def __init__(self, keys: dict):
        self.keys = keys

    def crypt(self, adlr: int, data: bytes) -> bytes:
        return decrypt(self.keys, adlr, data)


# ---------------------------------------------------------------- 归档读取


def read_entry(mm, entry) -> bytes:
    """条目明文流：逐段 zlib 解压后拼接。

    解密偏移按**明文累计**（跨段连续），所以必须先拼接再解密。
    """
    parts = []
    for segm in entry.segms:
        raw = bytes(mm[segm.offset:segm.offset + segm.zsize])
        if (segm.flags & 7) == 1:
            raw = zlib.decompress(raw)
        parts.append(raw)
    return b"".join(parts)
