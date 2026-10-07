"""AdvHD（MoeNovel 系）存档读取器：CCST 快照链（只读）。

存档文件位于 `%USERPROFILE%\\Saved Games\\MoeNovel\\<英文标题>\\`，命名形如
`Save093.<标题>Save-MoeNovel`。文件本身**没有文件头**，从头到尾是一串首尾相接的
`CCST` 块，每块是引擎运行时对象图的一份完整快照。本模块只读不写。
机制细节见 docs/engines/advhd/save-system.md。

记录布局（全部小端序，逆向 + 数据验证）：

    +0x00  char[4]  "CCST"                      块魔数（由 GameInfo.lua 的 getAppInfo 提供）
    +0x04  u16      tick 低位
    +0x06  u16      tick 高位                    → (高位<<16)|低位，见下「tick」
    +0x08  8 字节   恒 0
    +0x10  u32      恒 0
    +0x14  u32      对白长度（UTF-16 码元数）
    +0x18  ...      UTF-16LE 对白文本
    之后    引擎对象图（约 3.5–6.6 KB，定长部分 + 变长对象串）

对象图里所有字符串都是 `[u32 长度][UTF-16LE 内容]`。可辨认的对象/频道名有
`%Message%`、`%Select%`、`%LC<人名>`、`bg01`、`bg02_ANIME`、`bgm01`、`st03`、
`system` / `Name01`、`@ANIMATION_KEY`、`@STQUAKE_KEY` 等。资源以「归档名 + 成员名」
成对出现（`Chip1.arc`+`BG*.PNG`、`Graphic.arc`+`T*.PNA`、`Bgm.arc`+`BGM*.OGG`）。

块的组织（实测确认）：

    第 0 块       保存时的当前状态
    第 1..N-1 块  回溯历史，按时间从旧到新

N 上限 251（1 当前 + 250 历史）。物理顺序**不等于**时间顺序：只有按环序
`1,2,…,N-1,0` 读，`tick` 才严格单调递增 —— 即文件是一个环形缓冲，第 0 块是最后
写入（最新）的那一格。

`tick`：32 位单调递增字段，单位未确证；**跨游戏进程会归零**，不能当全局时间轴，
也**不要**把它当文件偏移用。

⚠️ 跨作需重验的构造参数（默认值是 CROSS†CHANNEL 语料的观测值）：
`script_re`（脚本名判别正则）与 `category_prefixes`（资源前缀 → 类别）——
脚本命名与资源命名规则每部游戏都不同，换游戏时必须按该作语料重新标定。

用法：

    from galrev.advhd import saveadv
    recs = saveadv.read(r'.../Save093.<标题>Save-MoeNovel')
    recs[0]['text'], recs[0]['script'], recs[0]['cg']
    saveadv.name_label(recs[0])            # 名字框文本
    for r in saveadv.chronological(recs):  # 按时间顺序（旧→新）
        print(r['script'], r['speaker'], r['text'])

命令行：`python -m galrev.advhd.saveadv <存档路径> [--limit N]`
按时间顺序打印全部条目，`--limit` 只打印最新的 N 条。
"""
import re
import struct
import sys

MAGIC = b'CCST'
TEXT_OFF = 0x14                 # 对白长度字段的块内偏移
TEXT_DATA_OFF = 0x18
MAX_STR = 300                   # 单条对象字符串的码元数上限（防御性）

NAME_PREFIX = '%LC'             # 说话人标记前缀（与 NameTable.txt 的键前缀一致；跨作需重验）
LABEL_OBJ = 'Name01'            # 名字框对象名，其后的字符串即显示文本

# ⚠️ 以下默认值全部是 CROSS†CHANNEL 语料的观测值，跨作需重验。
DEFAULT_SCRIPT_RE = re.compile(r'CC[A-Z0-9]{4,7}_[A-Za-z]{2}\Z')
# 资源成员名前缀 → saveadv 记录里的类别（.PNG/.OGG 按前缀归类；.PNA 一律 sprite）。
# .OGG 不命中任何前缀时归 voice；.PNG 不命中任何前缀时不归类。
DEFAULT_CATEGORY_PREFIXES = {'EVCC': 'cg', 'BGCC': 'bg', 'BGM': 'bgm'}


class SaveReader:
    """CCST 存档链解析器。

    `script_re`：匹配"脚本名"对象串的正则（默认为 CROSS†CHANNEL 观测值）。
    `category_prefixes`：{资源名前缀大写: 类别}（默认为 CROSS†CHANNEL 观测值）。
    `name_prefix`：说话人标记前缀（如 '%LC'；不同游戏可能用不同字母，跨作需重验）。
    """

    def __init__(self, script_re=DEFAULT_SCRIPT_RE,
                 category_prefixes=None, name_prefix=NAME_PREFIX):
        self.script_re = script_re
        self.category_prefixes = dict(
            DEFAULT_CATEGORY_PREFIXES if category_prefixes is None else category_prefixes)
        self.name_prefix = name_prefix

    def strings(self, blob, lo, hi):
        """扫描 [lo, hi) 内所有 `[u32 长度][UTF-16LE]` 字符串，返回 [(偏移, 文本)]。

        逐字节滑动匹配：只接受长度合法、内容全为可打印字符、且含至少一个字母数字或
        CJK 的串。对象图里混有大量二进制，滑窗比按结构解析更省事也更耐格式漂移。
        """
        out = []
        off = lo
        while off < hi - 4:
            n = struct.unpack_from('<I', blob, off)[0]
            if 0 < n <= MAX_STR and off + 4 + n * 2 <= len(blob):
                try:
                    text = blob[off + 4:off + 4 + n * 2].decode('utf-16-le')
                except UnicodeDecodeError:
                    text = None
                if text and all(ord(c) >= 0x20 for c in text) \
                        and any(c.isalnum() or ord(c) > 0x2000 for c in text):
                    out.append((off, text))
                    off += 4 + n * 2
                    continue
            off += 1
        return out

    def _classify(self, tokens):
        """按前缀约定把对象串分到脚本 / 语音 / 背景 / CG / 立绘 / BGM。"""
        prefs = self.category_prefixes
        out = {'script': '', 'voice': [], 'bg': [], 'cg': [], 'sprite': [], 'bgm': []}
        for _, t in tokens:
            if not out['script'] and self.script_re.match(t):
                out['script'] = t
            up = t.upper()
            if up.endswith('.OGG'):
                cat = next((c for p, c in prefs.items() if up.startswith(p)), 'voice')
                out[cat].append(t)
            elif up.endswith('.PNA'):
                out['sprite'].append(t)
            elif up.endswith('.PNG'):
                cat = next((c for p, c in prefs.items() if up.startswith(p)), None)
                if cat:
                    out[cat].append(t)
        for k in ('voice', 'bg', 'cg', 'sprite', 'bgm'):
            out[k] = sorted(set(out[k]))
        return out

    def _speaker(self, tokens, text):
        """说话人 = 紧跟「脚本名 + 以对白开头的正文」的那个 `<前缀><名>`。

        对象图里说话人标记会出现多次（正文对象、待播的下一句等），用「后两格是脚本名
        与正文」这条内容锚定，比取第一个更稳。旁白句没有正文对象，返回 ''。
        """
        for i, (_, t) in enumerate(tokens):
            if not t.startswith(self.name_prefix):
                continue
            if i + 2 < len(tokens):
                mid, body = tokens[i + 1][1], tokens[i + 2][1]
                if self.script_re.match(mid) and body.startswith(text) and body != text:
                    return t[len(self.name_prefix):]
        return ''

    def read(self, path):
        """解析存档，返回按**物理顺序**排列的记录列表（第 0 条 = 当前状态）。

        每条记录是一个 dict：idx/offset/size/tick/text/speaker/script/
        voice/bg/cg/sprite/bgm/tokens（tokens 为原始 [(偏移, 文本)]，供深入挖掘）。
        """
        with open(path, 'rb') as fh:
            blob = fh.read()
        offs = [m.start() for m in re.finditer(MAGIC, blob)]
        if not offs:
            raise ValueError('%s: 找不到 CCST 块' % path)

        recs = []
        for idx, off in enumerate(offs):
            end = offs[idx + 1] if idx + 1 < len(offs) else len(blob)
            low, high = struct.unpack_from('<HH', blob, off + 4)
            n = struct.unpack_from('<I', blob, off + TEXT_OFF)[0]
            text = ''
            if 0 < n <= MAX_STR * 10 and off + TEXT_DATA_OFF + n * 2 <= len(blob):
                text = blob[off + TEXT_DATA_OFF:off + TEXT_DATA_OFF + n * 2] \
                    .decode('utf-16-le', 'replace')
            tokens = self.strings(blob, off, end)
            rec = {'idx': idx, 'offset': off, 'size': end - off,
                   'tick': (high << 16) | low, 'text': text,
                   'speaker': self._speaker(tokens, text), 'tokens': tokens}
            rec.update(self._classify(tokens))
            recs.append(rec)
        return recs


def read(path, **kwargs):
    """便捷函数：用默认（CROSS†CHANNEL 观测值）参数构造 SaveReader 并解析。"""
    return SaveReader(**kwargs).read(path)


def name_label(rec):
    """取名字框对象的显示文本（`Name01` 之后的那条串），没有则返回 ''。"""
    toks = [t for _, t in rec['tokens']]
    if LABEL_OBJ in toks:
        j = toks.index(LABEL_OBJ)
        if j + 1 < len(toks):
            return toks[j + 1]
    return ''


def chronological(recs):
    """按时间顺序（旧→新）重排记录，即环序 1,2,…,N-1,0。"""
    return recs[1:] + recs[:1] if len(recs) > 1 else list(recs)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    limit, path = 0, ''
    it = iter(argv)
    for a in it:
        if a == '--limit':
            limit = int(next(it))
        else:
            path = a
    recs = read(path)
    cur = recs[0]
    print('文件      : %s' % path)
    print('块数      : %d（第 0 块为当前状态，其余为回溯历史）' % len(recs))
    print('当前状态  : %s | %s | 名字框 %r' % (cur['script'], cur['text'], name_label(cur)))
    print('当前资源  : bg=%s cg=%s sprite=%s bgm=%s'
          % (cur['bg'], cur['cg'], cur['sprite'], cur['bgm']))
    print()
    rows = chronological(recs)
    if limit:
        rows = rows[-limit:]
    for r in rows:
        print('%3d %10d %-14s %-6s %s' % (r['idx'], r['tick'], r['script'],
                                          r['speaker'], r['text']))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main(sys.argv[1:]))
