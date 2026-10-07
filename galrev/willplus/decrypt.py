"""WSC 字节混淆还原。

WillPlus 旧引擎把 WSC 脚本以**每字节循环右移 2 位（ror 2）**的形态存进归档。
本模块提供还原函数；`galrev.willplus.wsc` 的反汇编器只吃**已解密**形态，
从归档直读的 WSC 必须先过 `decrypt_wsc`。

ror 2 **不是自逆运算**：对已解密数据再跑一遍会把数据解坏 ——
判断是否已解密可看脚本头（明文 WSC 以 `8c <u16> 00` 开头）。
"""


def decrypt_wsc(raw):
    """原版归档内 WSC 的存储形态为每字节 ror 2；返回解密后的字节串。

    输入须是**归档直读的原始形态**；语料库里的 WSC 若已是解密形态，不要再过本函数。
    """
    return bytes(((b >> 2) | (b << 6)) & 0xff for b in raw)
