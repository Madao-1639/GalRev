# Willplus 旧引擎（WillAdv）

## 引擎概述

Willplus 旧引擎（下称 WillAdv）是 WSC 脚本时代的使用者：脚本是纯二进制的 `.WSC`，归档是类型表 + 21 字节定长条目的老式 Arc，全部资源随游戏目录分发。本卷以 CROSS†CHANNEL 语料（原版 `CROSSCHANNEL_v0.992.exe`，manifest 名 `will.willadv.exe`，`.text` 熵约 6.55 = 明文未加壳）为实证来源；该作之外的 Willplus 作品需逐项重验。

脚本解释器是 exe 内的一个大函数 `sub_40A050`（约 26 KB），按**两级查表**分发 opcode，见 [wsc-opcodes.md](wsc-opcodes.md)；256 项 opcode→handler 对照表已反汇编为 [`data/wsc_handlers.json`](../../../data/wsc_handlers.json)。

与本库 AdvHD 卷（Steam 系引擎）的关系见 [../../cross-engine/README.md](../../cross-engine/README.md)。

## 新项目快速通道

拿到一部 Willplus 旧引擎游戏，按以下顺序建立可读的脚本层：

1. **读老式归档**：用 `galrev.willplus.arc.read_old_arc`。名字是 ASCII/Shift-JIS（类型名即扩展名），**绝不能用 UTF-16LE 解**——偶数长度名字会被静默解成乱码且不报错，格式见 [file-formats.md](file-formats.md)。
2. **解密 WSC**：归档内的 WSC 是每字节 ror 2 的存储形态，用 `galrev.willplus.decrypt.decrypt_wsc` 还原；ror 2 不是自逆运算，对已解密数据二次解密会解坏。
3. **对照 opcode 表**：拿 `data/wsc_handlers.json` 对照反汇编出的 opcode，确认 handler 地址与本作 exe 一致；不同作家的 Willplus 版本 opcode 编号可能不同，须以本作的 `sub_40A050` 分发表为准。
4. **全量反汇编**：用 `galrev.willplus.wsc.disassemble` 线性解析全部脚本，要求 0 个 `UnknownInstruction`；布局口径见 [wsc-opcodes.md](wsc-opcodes.md)。
5. **建立语料统计**：对全量脚本统计每个 opcode 的频次与操作数模态，任何「恒定字节段」都要按全语料逐字节核对，而不是只看覆盖率（覆盖率不等于解析正确——错误位置重新同步后覆盖率检查照样通过）。

## 本卷文档

- [file-formats.md](file-formats.md) —— 老式归档格式与 WSC 文件级结构（混淆、头尾、脚本路由机制）。
- [wsc-opcodes.md](wsc-opcodes.md) —— WillAdv VM 的分发机制与指令布局（含图形指令逐字节参数）。
- [../../cross-engine/wsc-to-ws2.md](../../cross-engine/wsc-to-ws2.md) —— 向 AdvHD WS2 的忠实转换（字节模板、语义差异、实现陷阱）。

## 本库代码

- `galrev/willplus/arc.py` —— 老式归档读取。
- `galrev/willplus/decrypt.py` —— WSC ror 2 解密。
- `galrev/willplus/wsc.py` —— WSC 线性反汇编器（输入须为已解密形态）。
- `galrev/convert/wsc2ws2.py` —— WSC→WS2 忠实转换器（单语料标定值全部经 `ConvertOptions` 注入）。
