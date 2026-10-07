"""AdvHD .lng 本地化文本容器编解码。

布局（逐字节验证可往返）：

    u32                 count
    u16 * count         每条的字节长（含结尾 NUL 对 00 00）
    bytes               count 条字符串背靠背，无对齐填充

每条字符串是 UTF-16LE 编码后再**逐字节 XOR** 的产物；容器本身不做 rot6。

⚠️ **XOR 密钥不是引擎常量，必须参数化**：密钥由各游戏的 `Script.arc`/`GameInfo.lua`
提供（读档路径上引擎从 `getHostInfo` 的数字字段取一字节作为密钥）。实测观测值：
CROSS†CHANNEL 语料 = **0x2C**，A Sky Full of Stars 语料（同引擎另一部游戏）=
**0xCE**。拿到新游戏时先从 `GameInfo.lua` 确认密钥，再调用本模块。

与同名 .ws2 的配对是**按位置**的：引擎把播放序第 N 条文本型指令（0x14 对话与
0x0f 选项的每个条目各占一槽）的文本替换为 lng 的第 N 条。格式里没有 id 字段，
因此在 ws2 里增删对话会使其后所有条目错位（详见 docs/engines/advhd/localization.md）。
"""
import struct

__all__ = ['parse_lng', 'encode_lng']


def parse_lng(raw, xor_key):
    """解码 lng 载荷，返回字符串列表（尾部 NUL 已剥去）。

    xor_key: 单字节 XOR 密钥（来自该游戏的 GameInfo.lua；观测值见模块 docstring）。
    """
    tab = bytes(c ^ xor_key for c in range(256))
    count = struct.unpack_from('<I', raw, 0)[0]
    lens = struct.unpack_from('<%dH' % count, raw, 4)
    off = 4 + 2 * count
    if off + sum(lens) != len(raw):
        raise ValueError('lng length table does not cover payload')
    out = []
    for length in lens:
        chunk = raw[off:off + length]
        off += length
        out.append(chunk.translate(tab).decode('utf-16le').rstrip('\0'))
    return out


def encode_lng(strings, xor_key):
    """`parse_lng` 的逆变换：把字符串列表编码为 lng 载荷字节。"""
    tab = bytes(c ^ xor_key for c in range(256))
    blobs = [(s + '\0').encode('utf-16le').translate(tab) for s in strings]
    out = bytearray(struct.pack('<I', len(blobs)))
    for blob in blobs:
        if len(blob) > 0xffff:
            raise ValueError('string exceeds u16 length field')
        out += struct.pack('<H', len(blob))
    for blob in blobs:
        out += blob
    return bytes(out)
