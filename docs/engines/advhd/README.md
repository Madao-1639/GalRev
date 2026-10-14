# AdvHD 引擎（MoeNovel / Amaneko 系）

AdvHD.exe 是 MoeNovel 的 Amaneko 系视觉小说引擎，WillPlus 新引擎，用于多部游戏（CROSS†CHANNEL Steam 版、A Sky Full of Stars 等均使用本引擎）。

## 引擎概述

- 32 位 PE 可执行文件，imagebase `0x400000`，约 2 MB `.text`。
- 脚本系统：WS2 二进制脚本，逐字节 rot6 混淆（见 [file-formats.md](file-formats.md) 与 [ws2-opcodes.md](ws2-opcodes.md)）。
- 脚本绑定：Lua 5.3（`lua5.3.dll`），系统界面与游戏主逻辑由 `Script.arc` 内的定制 Lua 5.3 字节码承载。
- 表情驱动：E-mote 系统（`emotedriver.dll`，导出 `CEmoteLayer` / `face_talk` / `DISABLETALK` 等符号）。
- 文本编码：内建 BIG5 / GB2312 / SHIFTJIS / UTF-8 四种代码页；脚本内窄字节按 CP932 解码、Lua 层用 UTF-8（见 [engine-mechanics.md](engine-mechanics.md)「文本编码路径」）。
- 语言包机制：`AdvHDLang.dll` + 语言子目录（官方简中为 `zh-CN/`，见 [engine-mechanics.md](engine-mechanics.md)「语言包目录」与 [localization.md](localization.md)）。
- 资源系统：自定义 Arc 归档（UTF-16LE 成员名）+ PNA 分层图像 + LNG 文本替换容器。
- 存档系统：CCST 快照链（见 [save-system.md](save-system.md)）。
- Steam 成就：编译器在 CG 显示的固有 id 对之后追加一条 `CG_ACHIEVEMENT` 调用（见 [steam-achievements.md](steam-achievements.md)）。

个别游戏的 `AdvHD.exe` 的 `.text` 段加壳（熵 8.0），但 `.rdata` / `.data` 始终是明文，导入表、字符串常量与操作数格式表可直接读取；同引擎存在明文样本时结论可交叉核对，**涉及操作数格式的定案必须回该作自身 exe 验证**。

## 本卷文档导航

| 文档 | 内容 |
|---|---|
| [file-formats.md](file-formats.md) | Arc / WS2 / LNG / 定制 Lua 5.3 / NameTable.txt / PTF 字体格式 |
| [ws2-opcodes.md](ws2-opcodes.md) | WS2 指令集：类型码、164 opcode 格式表、函数名对照、关键指令语义、字节模态结论 |
| [engine-mechanics.md](engine-mechanics.md) | 脚本 VM 结构、LAYER_ORDER 槽位机制、ev 槽 7 字节限制、文本编码路径、语言包目录 |
| [pna.md](pna.md) | PNA 分层图像二进制布局、layer_id 机制、写回不变量、图片比对口径 |
| [save-system.md](save-system.md) | CCST 存档块结构、PC 字段、MessageFlag.dat、指定位置存档生成 |
| [steam-achievements.md](steam-achievements.md) | Steam 成就机制与安全注入的工程要求 |
| [localization.md](localization.md) | 汉化通路：lng 位置对应、NameTable、语音通道、字体、注入工程注意事项 |

工具库：`galrev/advhd/`（Arc/WS2/PNA/LNG/Lua 5.3/存档的读写与反汇编，纯标准库）；引擎级数据表：`data/ws2_operand_formats.json`。

## 新项目快速通道

拿到一个 AdvHD 引擎的新游戏，按此清单起步：

1. **解脚本**：取任意 `.ws2` 成员，用 `galrev.advhd.ws2.decode`（逐字节循环左移 6 位）解混淆；能露出 ASCII 指令名与资源名即确认是本引擎。
2. **对照 opcode**：用 `galrev.advhd.ws2disasm.disassemble` 线性反汇编，`data/ws2_operand_formats.json` 对照每条 opcode 的操作数格式；出现 UnknownInstruction 的 opcode 即是该作新出现的形态，按 [ws2-opcodes.md](ws2-opcodes.md) 的模态方法定边界。
3. **Arc/PNA/LNG 工具直接用**：`galrev.advhd.arc`（归档读写与 null padding 规范化）、`galrev.advhd.pna`（分层图像解析/重序列化）、`galrev.advhd.lng`（文本容器编解码，**XOR 密钥从该作 `GameInfo.lua` 查**，观测值有 0x2C 与 0xCE 两种，不要照抄）。
4. **确认本作标定值**：脚本名正则、资源前缀、存档目录名、PC 字段偏移、脚本标记字母（`%LC`/`%LF`/…）一律按本作语料重新标定——库里的默认值只是某作观测值，跨作需重验。
5. **末尾 8 字节尾表必须纳入校验**：脚本文件末尾 8 字节是**明文**的 `[u32 消息数][u32 选项条目数]`
   （不参与 rot 混淆；见 [file-formats.md](file-formats.md)「末尾 8 字节」）。引擎据它给存档里的
   「已读消息位图」分配容量 —— **任何改 `0x14`/`0f` 条数的补丁都必须同步重写它**，否则引擎写位越界，
   表现为概率性 `0xc0000374`（细节与指纹见 [save-system.md](save-system.md)「MessageFlag.dat」）。
   现成工具：`galrev.advhd.ws2.check_tail_counts()`（逐脚本自查）与 `set_tail_counts()`。
6. **读脚本 VM**：需要逆向引擎时，先找明文的同引擎 exe 定位 handler 表（`obj+0x1B18` 附近）与操作数格式表，再回本作 exe（必要时脱壳）核对编号；方法与地址见 [engine-mechanics.md](engine-mechanics.md)。
7. **方法论红线**：同引擎样本只用于提出假设，本作自身样本才用于定案；凡涉及字节增删的补丁，绝对偏移重定位与边界自检（[steam-achievements.md](steam-achievements.md) 的四条强不变式）不可省略。
