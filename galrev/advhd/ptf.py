"""AdvHD PTF 字体容器（Fonts.arc 内 .PTF 成员）编解码。

格式由 `sub_4591E0`（字体加载器）的反汇编 + 实机验证得出：

- 文件前 4 字节 = 解压后大小（LE u32），后接 LZSS 字节流：
  - flag 字节按 **bit0 先出** 消费 8 位；bit=1 → 1 字节 literal；
    bit=0 → 2 字节 match token：距离源 = `(b1>>4) + 16*b0`（12-bit 环形窗
    0x1000），长度 = `(b1 & 0xF) + 2`；
  - **环形窗内存的是 XOR 后的字节**；写指针从 1 起（某明文样本 `0x4593CD`：mov esi,1，
    **跨作需重验**）；
- 解压输出逐字节与 xor_key 异或得到标准字体文件（OpenType OTTO / TrueType glyf 均可）；
- 字体随后交给 GDI `AddFontMemResourceEx` 注册到**进程字体表**，引擎经
  `CreateFontIndirectW` + `lfCharSet=GB2312_CHARSET` 按 Lua 传入的族名匹配；族名匹配
  只面向进程内已注册字体，与系统字体表无关（字体自包含）。

**XOR 密钥与 lng 的密钥同一来源**（该作 `GameInfo.lua`，`getHostInfo` 数字字段）；
观测值：某作语料为 0x2C，同引擎另一作为 0xCE —— **拿到新游戏先查 GameInfo.lua**。

字体文件熵高，LZSS 压缩无实际收益：原版 M 位 15.6 MiB 明文打出 17.6 MiB PTF
（同样膨胀）。通用压缩包装器无收益、match token 的环形坐标是错排高发的根源，
因此本模块的打包端只生成 **纯字面量 LZSS**（flag=0xFF、每 8 字节前 1 flag、零
match），膨胀固定 ~12.5% 且与解压端语义严格一致；由调用方自行做往返校验。
"""
import struct

DEFAULT_XOR_KEY = 0x2C
WINDOW = 0x1000

__all__ = ['lzss_decode', 'lzss_encode_literal', 'pack_ptf', 'unpack_ptf']


def lzss_decode(data, out_len, xor_key=DEFAULT_XOR_KEY):
    """按引擎语义解压 LZSS 字节流（不含前 4 字节大小头，out_len 给出输出长度）。"""
    out = bytearray(out_len)
    ring = bytearray(WINDOW)
    w = 1
    flag = 0
    mask = 0
    it = 0
    o = 0
    while o < out_len and it < len(data):
        if mask == 0:
            flag = data[it]
            it += 1
            mask = 8
        bit = flag & 1
        flag >>= 1
        mask -= 1
        if bit:
            b = data[it]
            it += 1
            if o < out_len:
                out[o] = b ^ xor_key
                o += 1
            ring[w] = b
            w = (w + 1) & (WINDOW - 1)
        else:
            b0 = data[it]
            b1 = data[it + 1]
            it += 2
            src = (b1 >> 4) + 16 * b0
            length = (b1 & 0xF) + 2
            for _ in range(length):
                c = ring[src & (WINDOW - 1)]
                if o < out_len:
                    out[o] = c ^ xor_key
                    o += 1
                ring[w] = c
                w = (w + 1) & (WINDOW - 1)
                src = (src + 1) & (WINDOW - 1)
    return bytes(out)


def lzss_encode_literal(data, xor_key=DEFAULT_XOR_KEY):
    """纯字面量 LZSS 打包：先逐字节 XOR，再每 8 字节前插 1 字节 flag=0xFF。

    与 lzss_decode 严格互逆（literal 路径），不产生任何 match token —— 无
    坐标错位风险，膨胀固定 ~12.5%。"""
    payload = bytes(b ^ xor_key for b in data)
    out = bytearray()
    i = 0
    while i < len(payload):
        out.append(0xFF)
        out.extend(payload[i:i + 8])
        i += 8
    return bytes(out)


def pack_ptf(plain_font, xor_key=DEFAULT_XOR_KEY):
    """明文字体 → PTF blob（[u32 大小][literal LZSS（xor 结果)]），内含往返自检。

    往返校验**不树立假设**：同一个解码端由引擎次序定义；literal 路径几乎
    不可能错位，此处仍做一次 self-check 以便日后改码时立刻暴露。"""
    blob = struct.pack('<I', len(plain_font)) + lzss_encode_literal(plain_font, xor_key)
    deco = unpack_ptf(blob, xor_key)
    if deco != plain_font:
        raise AssertionError('PTF round-trip mismatch')
    return blob


def unpack_ptf(ptf, xor_key=DEFAULT_XOR_KEY):
    """PTF blob → 明文字体。"""
    (decl,) = struct.unpack_from('<I', ptf, 0)
    return lzss_decode(ptf[4:], decl, xor_key)
