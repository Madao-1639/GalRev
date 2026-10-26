"""galrev.advhd —— MoeNovel AdvHD（Amaneko 系）引擎通用库。

模块清单（全部纯标准库，无项目耦合，不内嵌任何一部游戏的标定值）：
- arc:        Arc 归档读写（相对偏移、原子写、null padding 检查与规范化）
- arcstream:  大归档流式处理（只读索引、按谓词流式复制子集）
- ws2:        WS2 脚本 rot6 编解码 + 资源引用/调用边正则提取 + 成就 id 对原语
- ws2disasm:  WS2 线性反汇编器（Instruction / UnknownInstruction / disassemble）
- ws2patch:   WS2 字节补丁原语（0x01/0x02/0x06 绝对偏移重写、跳转边界自检、调用图）
- pna:        PNAP 分层图像读写（解析/重序列化往返、图层操作、签名扫描回退）
- lng:        LNG 文本容器编解码（UTF-16LE + 逐字节 XOR，密钥由调用方传入）
- ptf:        Fonts.arc 字体容器编解码（头 4 字节大小 + LZSS，环形窗写指针 1 起 + XOR；打包端纯字面量）
- luac53:     定制 Lua 5.3 字节码 undump（字符串长度 1 字节、opcode 索引 9 多一项）
- luadis53:   定制 Lua 5.3 反汇编器（fields / Dis / dump）
- saveadv:    CCST 存档快照链只读解析（块结构、字符串扫描、环序）
- savegen:    指定位置存档生成（改写第 0 块 PC 字段；写盘类操作需调用方显式给路径）

涉及具体游戏标定值（存档目录名、脚本名正则、PC 字段偏移等）一律是构造/调用参数，
并提供某个已实测游戏（CROSS†CHANNEL 语料）的观测值作默认，注明"跨作需重验"。
"""
