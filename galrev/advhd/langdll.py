"""语言包 DLL（`AdvHDLang.dll`）的通用构建与校验。

引擎把"游戏根下以 locale 命名的目录 + 其中的 `AdvHDLang.dll`"识别为语言包，并由
`LoadLibraryW` 主动加载、用 `FindResourceW`/`LoadStringW` 读它的字符串资源（设置界面与语言名）。
因此这张 DLL 是**可被替换的代码+资源载体**，且只在选中该语言时生效。

本模块做三件事（全部只依赖标准库 + 外部 32 位 MinGW 工具链）：

1. **资源重建**：从原件解析 `RT_STRING`（按块）+ `RT_MANIFEST`，生成 `.rc` 与 manifest 文件。
   （`AdvHDLang.dll` 是**纯资源** DLL：只为它重建资源就够了。）
   ⚠️ **不能手工搬 `.rsrc` 节**到别的 RVA —— 节内偏移会失效，`LoadStringW` 直接访问违例，
   外在表现是"设置界面文字全空"。必须让资源编译器重新生成整棵树。
2. **编译**：`windres` 编 `.rc` → `gcc -m32` 链接出 i386 DLL（如确需自己的代码，用 `extra_sources` 传入）。
3. **校验**：i386 / `IMAGE_FILE_DLL` / 资源键集合与原件一致 / **`LoadStringW` 与原件逐条相同**。

工具链：设环境变量 `MINGW32_BIN` 指向含 `i686-w64-mingw32-gcc.exe`、`windres.exe` 的目录
（或把该目录放进 PATH）。本模块不内嵌任何一部游戏的路径。
"""
import ctypes
import os
import struct
import subprocess
from pathlib import Path

RT_STRING = 6
RT_MANIFEST = 24
HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- PE
def _pe(data):
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    opt = pe + 24
    magic = struct.unpack_from('<H', data, opt)[0]
    dd = opt + (96 if magic == 0x10b else 112)
    so = opt + struct.unpack_from('<H', data, pe + 20)[0]
    secs = []
    for i in range(nsec):
        name, vsize, vaddr, rsize, raddr = struct.unpack_from('<8sIIII', data, so + i * 40)
        secs.append({'name': name.rstrip(b'\0').decode('latin-1'), 'vsize': vsize,
                     'vaddr': vaddr, 'rsize': rsize, 'raddr': raddr})
    return {'pe': pe, 'nsec': nsec, 'opt': opt, 'dd': dd, 'secs': secs}


def resources(dll):
    """→ {(type, name, lang): bytes}。

    资源树里的偏移有两种约定：标准 PE 用**相对映像基址的 RVA**，个别工具的产物用**节内相对**。
    这里先按标准解析，取不到该 RVA 时退回"相对资源节起点"，两种都覆盖到。
    """
    data = Path(dll).read_bytes()
    info = _pe(data)
    res_rva, _sz = struct.unpack_from('<II', data, info['dd'] + 16)

    def off_of(rva):
        for s in info['secs']:
            if s['vaddr'] <= rva < s['vaddr'] + max(s['vsize'], s['rsize']):
                return s['raddr'] + (rva - s['vaddr'])
        return None

    def resolve(target):
        o = off_of(res_rva + target)
        if o is None:
            o = off_of(res_rva) + target
        return o

    base = off_of(res_rva)
    out = {}

    def walk(offset, path):
        nname, nid = struct.unpack_from('<HH', data, offset + 12)
        for i in range(nname + nid):
            nm, tgt = struct.unpack_from('<II', data, offset + 16 + i * 8)
            if nm & 0x80000000:
                so = resolve(nm & 0x7FFFFFFF)
                ln = struct.unpack_from('<H', data, so)[0]
                label = data[so + 2:so + 2 + ln * 2].decode('utf-16-le', 'replace')
            else:
                label = nm & 0xFFFF
            if tgt & 0x80000000:
                walk(resolve(tgt & 0x7FFFFFFF), path + (label,))
            else:
                drva, dsize = struct.unpack_from('<II', data, resolve(tgt))
                o = off_of(drva) or resolve(drva)
                out[path + (label,)] = data[o:o + dsize]
    walk(base, ())
    return out


def extract_strings(res):
    """→ ({lang: {string_id: text}}, manifest_bytes)。

    块号 N 覆盖 `(N-1)*16 … N*16-1` 的连续 id（Windows 的 `LoadStringW` 按 `id>>4` 找块、
    按 `id & 0xF` 取槽），块内为 16 个 `[u16 长度][UTF-16LE]` 顺序排列。
    """
    per_lang, manifest = {}, None
    for (typ, name, lang), blob in res.items():
        if typ == RT_STRING:
            pos, slot = 0, 0
            while pos + 2 <= len(blob):
                ln = struct.unpack_from('<H', blob, pos)[0]
                pos += 2
                text = blob[pos:pos + ln * 2].decode('utf-16-le', 'replace')
                pos += ln * 2
                sid = (name - 1) * 16 + slot
                slot += 1
                if text:
                    per_lang.setdefault(lang, {})[sid] = text
        elif typ == RT_MANIFEST:
            manifest = blob
    return per_lang, manifest


def _rc_escape(s):
    return (s.replace('\\', '\\\\').replace('"', '\\"').replace('\r', '\\r')
             .replace('\n', '\\n').replace('\t', '\\t'))


def gen_rc(per_lang, manifest, rc_path, man_path):
    lines = ['#include <winres.h>', '']
    for lang in sorted(per_lang):
        lines.append('LANGUAGE 0x%04X, 1' % lang)
        lines.append('STRINGTABLE')
        lines.append('BEGIN')
        for sid in sorted(per_lang[lang]):
            lines.append('  %d "%s"' % (sid, _rc_escape(per_lang[lang][sid])))
        lines.append('END')
        lines.append('')
    if manifest:
        Path(man_path).write_bytes(manifest)
        lines.append('LANGUAGE 0x0409, 1')
        lines.append('2 24 "%s"' % Path(man_path).name)
    Path(rc_path).write_text('\n'.join(lines), encoding='utf-8')
    return rc_path


# --------------------------------------------------------------------------- 工具链
def _tool(*names):
    env = os.environ.get('MINGW32_BIN')
    for name in names:
        for cand in ([Path(env) / name] if env else []) + [Path(name)]:
            p = str(cand)
            if os.path.sep in p or p.endswith('.exe'):
                if Path(p).exists():
                    return Path(p)
        found = _which(name)
        if found:
            return found
    raise SystemExit('[ERR] 找不到 %s：设 MINGW32_BIN 指向 32 位 MinGW 的 bin 目录' % (names[0],))


def _which(name):
    from shutil import which
    p = which(name)
    return Path(p) if p else None


def _run(cmd, what):
    env = dict(os.environ)
    env['PATH'] = str(Path(cmd[0]).parent) + os.pathsep + env.get('PATH', '')
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise SystemExit('[ERR] %s 失败：\n%s\n%s' % (what, r.stdout, r.stderr))
    return r


# --------------------------------------------------------------------------- 构建
def build(out_dll, orig_dll, extra_sources=None, extra_flags=None, workdir=None):
    """用**原件的资源** + 可选的自有源文件，编译出语言包 DLL。返回输出路径。

    本函数只负责"语言包 DLL 本身"：重建资源树、按 i386 链接、保留原资源语义。
    需要附带自己的 C 代码（例如在 DllMain 里做点什么）时，用 `extra_sources` / `extra_flags`
    传入即可 —— 本库不为此提供任何专用模板或标定配置。
    """
    out_dll, orig_dll = Path(out_dll), Path(orig_dll)
    work = Path(workdir or out_dll.parent) / (out_dll.stem + '_build')
    work.mkdir(parents=True, exist_ok=True)
    strings, manifest = extract_strings(resources(orig_dll))
    rc = gen_rc(strings, manifest, work / 'res.rc', work / 'app.manifest')
    res_o = work / 'res.o'
    _run([_tool('windres.exe', 'i686-w64-mingw32-windres.exe'), rc, '-O', 'coff', '-o', res_o], 'windres')

    cmd = [_tool('i686-w64-mingw32-gcc.exe'), '-O2', '-s', '-shared', '-Wall']
    if extra_flags:
        cmd += [str(f) for f in extra_flags]
    srcs = [Path(x) for x in (extra_sources or [])] + [res_o]
    cmd += ['-o', out_dll] + [str(x) for x in srcs] + ['-lkernel32']
    _run(cmd, 'gcc')
    return out_dll


# --------------------------------------------------------------------------- 校验
def load_strings(dll, ids, datafile=True):
    """用 Win32 API 读字符串（`LoadLibraryExW(LOAD_LIBRARY_AS_DATAFILE)` + `LoadStringW`）。

    → {id: text}；加载失败返回 None。这是"资源树是否合法"的**唯一可靠判据**
    （PE 解析通过不代表 `LoadStringW` 能用）。
    """
    if os.name != 'nt':
        return None
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    u32 = ctypes.WinDLL('user32')
    k32.LoadLibraryExW.restype = ctypes.c_void_p
    u32.LoadStringW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_int]
    u32.LoadStringW.restype = ctypes.c_int
    flags = 0x2 if datafile else 0
    h = k32.LoadLibraryExW(str(Path(dll).resolve()), None, flags)
    if not h:
        return None
    try:
        out = {}
        for sid in ids:
            buf = ctypes.create_unicode_buffer(1024)
            n = u32.LoadStringW(ctypes.c_void_p(h), sid, buf, 1024)
            out[sid] = buf.value if n else None
        return out
    finally:
        k32.FreeLibrary(ctypes.c_void_p(h))


def verify(dll, orig_dll):
    """→ 问题列表（空 = 通过）：i386 / DLL 标志 / 资源键一致 / `LoadStringW` 值一致。"""
    data = Path(dll).read_bytes()
    info = _pe(data)
    machine = struct.unpack_from('<H', data, info['pe'] + 4)[0]
    chars = struct.unpack_from('<H', data, info['pe'] + 22)[0]
    bad = []
    if machine != 0x14c:
        bad.append('machine=0x%04x 不是 i386' % machine)
    if not (chars & 0x2000):
        bad.append('缺 IMAGE_FILE_DLL 标志')
    got, want = resources(dll), resources(orig_dll)
    if sorted(got) != sorted(want):
        bad.append('资源键集合与原件不同：新 %d / 原 %d' % (len(got), len(want)))
    ids = sorted({sid for d in extract_strings(want)[0].values() for sid in d})
    if ids:
        a, b = load_strings(orig_dll, ids), load_strings(dll, ids)
        if b is None:
            bad.append('LoadLibraryExW(DATAFILE) 失败')
        elif a != b:
            diff = [k for k in ids if a.get(k) != b.get(k)]
            bad.append('LoadStringW 与原件不同 %d 条（例 id=%s：%r vs %r）'
                       % (len(diff), diff[0], a.get(diff[0]), b.get(diff[0])))
    return bad
