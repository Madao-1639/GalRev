# 文档索引

知识库按「方法论 → 引擎卷 → 跨引擎卷」组织。每篇文档自包含、只写当前成立的最新结论；具体游戏的标定值出现处均标注「跨作需重验」。

## 通用卷

| 文档 | 内容 |
|---|---|
| [methodology.md](methodology.md) | 跨引擎逆向方法论：证据与判据（字节覆盖不构成正确性证明、同引擎提假设自身定案）、写回与补丁工程（往返回归第一道闸、绝对偏移事故源、幂等复跑）、工程卫生。**任何工作开始前先读。** |

## AdvHD 引擎卷（MoeNovel / Amaneko 系，WillPlus 新引擎）

入口：[engines/advhd/README.md](engines/advhd/README.md)（引擎概述 + 新项目快速通道 + 导航）。

| 文档 | 内容 |
|---|---|
| [engines/advhd/file-formats.md](engines/advhd/file-formats.md) | Arc 归档、WS2 rot6、LNG 文本池、定制 Lua 5.3 字节码、NameTable.txt、**PTF 字体**（容器格式 + 纯字面量 LZSS 打包） |
| [engines/advhd/ws2-opcodes.md](engines/advhd/ws2-opcodes.md) | WS2 指令集：类型码表、164 opcode 格式表（指向 `data/ws2_operand_formats.json`）、关键指令逐条语义、字节模态结论 |
| [engines/advhd/engine-mechanics.md](engines/advhd/engine-mechanics.md) | WS2 VM 结构、LAYER_ORDER 槽位机制、ev 槽 7 字节限制、**文字渲染路径（字体装载 + backlog 膨胀边）**、文本编码路径、语言包范式 |
| [engines/advhd/pna.md](engines/advhd/pna.md) | PNA 分层图像：二进制布局、layer_id 语义、写回硬不变量、帧池比对口径 |
| [engines/advhd/save-system.md](engines/advhd/save-system.md) | CCST 存档快照链：文件布局、块内布局、PC 字段、MessageFlag.dat、指定位置存档生成 |
| [engines/advhd/steam-achievements.md](engines/advhd/steam-achievements.md) | Steam 成就机制：CG 显示固有 id 对、`CG_ACHIEVEMENT` 调用注入、偏移重定位与不变式自检 |
| [engines/advhd/localization.md](engines/advhd/localization.md) | 汉化通路：lng 位置对应等式、NameTable、官方简中注入范式、语音通道规则、字体（PTF 自制 / 族名接线 / 简中 Charset） |
| [engines/advhd/branching-and-variants.md](engines/advhd/branching-and-variants.md) | 条件分支与变体路由：`01`/`0b`/`09` 的存储与比较语义、**布尔旗标陷阱**、选项帧与跨脚本变量路由的字节模板、分段重定基、自检清单与实机验收纪律 |

## Willplus 旧引擎卷（WillAdv）

入口：[engines/willplus/README.md](engines/willplus/README.md)（引擎概述 + 新项目快速通道 + 导航）。

| 文档 | 内容 |
|---|---|
| [engines/willplus/file-formats.md](engines/willplus/file-formats.md) | 老式归档（21 字节定长条目）、WSC 文件结构、ror2 混淆、脚本路由机制 |
| [engines/willplus/wsc-opcodes.md](engines/willplus/wsc-opcodes.md) | WillAdv VM 两级查表分发、图形指令逐字节参数、256 项 handler 全表（指向 `data/wsc_handlers.json`） |

## krkr 引擎卷（KiriKiri Z + M2「MDF」脚本）

入口：[engines/krkr/README.md](engines/krkr/README.md)（引擎概述 + 新项目快速通道 + 跨作需重验清单）。

| 文档 | 内容 |
|---|---|
| [engines/krkr/file-formats.md](engines/krkr/file-formats.md) | 判型速查、普通 xp3 / **Hxv4 加密变体**容器、`.scn` 两种外壳、PSB v3（头部/值类型/名字字典树/字符串池/重写策略）、TJS binary Variant |
| [engines/krkr/script-text.md](engines/krkr/script-text.md) | MDF 文本模型：场景键、对白 5 元、分页 3/5 元、**`length` 两派口径**、行内标记、回写不变量、跨版本对齐键 |
| [engines/krkr/hxv4-crypto.md](engines/krkr/hxv4-crypto.md) | 映射表帧与记录（`packed` 低位 = 条目下标）、**DJB 布局 AEAD**、DRIP VM 与四层 XOR 过滤器、参数清单与获取流程、判据与不变量 |
| [engines/krkr/engine-mechanics.md](engines/krkr/engine-mechanics.md) | 引擎身份/指纹、执行层分工、**归档注册顺序与明文 xp3 覆盖**、语言域、字体重定向、移植操作顺序 |

## 跨引擎卷（Willplus → AdvHD）

| 文档 | 内容 |
|---|---|
| [cross-engine/README.md](cross-engine/README.md) | 两代引擎职责对照、可直接复用的资源 |
| [cross-engine/wsc-to-ws2.md](cross-engine/wsc-to-ws2.md) | 忠实转换：文件级对照、字节模板、关键语义差异 7 条、切片模式、实现陷阱 11 条 |

## 配套代码与数据

- `galrev/advhd/`、`galrev/willplus/`、`galrev/krkr/`、`galrev/convert/`：与上述文档一一对应的通用库（纯标准库，游戏专属标定值全部为调用方参数）。
- `data/ws2_operand_formats.json`：AdvHD WS2 全部 164 个 opcode 的操作数格式表。
- `data/wsc_handlers.json`：Willplus WillAdv VM 全部 256 项 opcode handler 表。

## 阅读路径建议

- **新遇到一台 AdvHD 引擎游戏**：advhd/README → methodology → file-formats → ws2-opcodes，随后按需（图像走 pna，存档走 save-system，汉化走 localization，成就走 steam-achievements）。
- **把原版内容移植到 AdvHD Steam 版**：先各自读完两个引擎卷的 README 与 file-formats，再读 cross-engine/wsc-to-ws2，转换器直接用 `galrev/convert/wsc2ws2.py`。
- **新遇到一台 krkr（KiriKiri Z + MDF 脚本）游戏**：krkr/README → methodology → file-formats → script-text；归档加密走 hxv4-crypto，补丁形态与语言域走 engine-mechanics。
- **只想解包看内容**：methodology → 对应引擎卷 file-formats，配 `galrev` 对应子包即可。
