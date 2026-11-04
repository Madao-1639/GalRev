"""AdvHD ≥1.9 语言包：选择（注册表）、发现（目录 + AdvHDLang.dll）与按成员覆盖视图。

引擎行为（实测）：
- 语言包 = 游戏根下的一个子目录，**判据是目录里存在 `AdvHDLang.dll`**；目录名即语言标识。
- 读某个归档时**优先取包内同名成员**，缺失的成员回落根目录 ⇒ 包内归档只需放"差异成员"。
- 包内归档**必须与根目录同名**（主剧本归档若不是 `Rio.arc` 而是 `RIO1`，包里也要用 `RIO1`）。
- 所选语言存注册表 `HKCU\\Software\\WillPlus\\AdvHD\\LanguageSettings`：
  **值名 = 游戏安装路径**（经系统 ANSI 代码页转换，路径里的 `†` 之类会变 `?`），值为语言目录名；
  **值为空 = 默认（英文）**，语言包整体不生效。

只依赖标准库。本模块不内嵌任何一部游戏的路径与语言名，全部由调用方传入。
"""
import os
from pathlib import Path

DEFAULT_KEY = r'Software\WillPlus\AdvHD\LanguageSettings'
DLL_NAME = 'AdvHDLang.dll'


# --------------------------------------------------------------------------- 值名
def value_name_for(game_dir):
    """注册表值名 = 游戏目录经**系统 ANSI 代码页**转换（编不出的字符变 `?`）。

    例：路径里的 `†`（U+2020）在 GBK 系统上落成 `?`。
    **不要**用 cp932 代替：CP932 能编 `†`（0x8181），与引擎实际写入的值名不一致。
    """
    s = str(game_dir)
    for enc in ('mbcs', 'ascii', 'utf-8'):
        try:
            return s.encode(enc, errors='replace').decode(enc, errors='replace')
        except (LookupError, UnicodeError):
            continue
    return s


def _winreg():
    if os.name != 'nt':
        return None
    try:
        import winreg
    except ImportError:
        return None
    return winreg


def read_selected(game_dir, key=DEFAULT_KEY):
    """读该游戏当前选择的语言目录名；**空串/缺失都返回 ''**（= 默认语言）。

    非 Windows 或无注册表时返回 ''（此机制仅在 Windows 有效）。
    """
    winreg = _winreg()
    if winreg is None:
        return ''
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            got, _ = winreg.QueryValueEx(k, value_name_for(game_dir))
            return got
    except OSError:
        return ''


def write_selected(game_dir, lang, key=DEFAULT_KEY):
    """写所选语言（`lang=''` 表示恢复默认/英文）。返回写后回读到的值。

    只在 Windows 生效；其它平台返回 `None` 并**不做任何事**（语言留给游戏内设置界面）。
    """
    winreg = _winreg()
    if winreg is None:
        return None
    name = value_name_for(game_dir)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, lang)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
        got, _ = winreg.QueryValueEx(k, name)
    return got


# --------------------------------------------------------------------------- 发现
def find_packs(game_dir):
    """→ {语言目录名: AdvHDLang.dll 路径}（判据：子目录里存在该 DLL）。"""
    root = Path(game_dir)
    out = {}
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return out
    for p in entries:
        dll = p / DLL_NAME
        if p.is_dir() and dll.exists():
            out[p.name] = dll
    return out


def pack_dir(game_dir, lang):
    """语言包目录路径（不校验存在）。"""
    return Path(game_dir) / lang


# --------------------------------------------------------------------------- 覆盖视图
def override_view(pack_arc, root_arc):
    """按成员合并两层归档 → [(name_bytes, data)]，**镜像引擎的读取顺序**。

    `pack_arc` 缺失或读不了时等价于只有根目录。返回顺序：根目录成员顺序在前，
    包内**新增**成员追加在后（引擎按名查，顺序不影响读取；这里固定顺序便于对账）。
    """
    from . import arc

    root = list(arc.read_raw(root_arc)) if Path(root_arc).exists() else []
    if pack_arc is None or not Path(pack_arc).exists():
        return root
    pack = {name.upper(): data for name, data in arc.read_raw(pack_arc)}
    merged = [(name, pack.get(name.upper(), data)) for name, data in root]
    root_keys = {name.upper() for name, _ in root}
    for name, data in arc.read_raw(pack_arc):
        if name.upper() not in root_keys:
            merged.append((name, data))
    return merged


def pack_only_members(pack_arc, root_arc):
    """→ 包内**真正覆盖或新增**的成员名（与根目录逐字节相同的不算）。"""
    from . import arc

    root = {name.upper(): data for name, data in arc.read_raw(root_arc)}
    out = []
    for name, data in arc.read_raw(pack_arc):
        if root.get(name.upper()) != data:
            out.append(name.decode('utf-16-le', 'replace'))
    return out
