# CMVS 引擎（Purple SOFTWARE）

CMVS 是 Purple SOFTWARE 自《アマツツミ》起的当代引擎，用 C++ 实现、PE32/PE64 双版本
（`cmvs32.exe` / `cmvs64.exe`），脚本是自研的 PS2A 字节码（`.ps3`），图像是自研的 PB3B
容器（`.pb3`），资源封包为 CPZ（`.cpz`）。多部作品共用同一套格式，因此本卷结论可跨作复用，
但 exe 内的**立即数与地址随构建变化**，凡涉及此类值的结论都标注「跨作需重验」。

本卷覆盖：脚本容器、图像容器、资源查找槽位、文本渲染与编码通路、字体装载、
以及不改 exe 的前提下把所有改动做成外挂的形态。
**不含** PS2A 指令集语义逆向（见[已知边界](#已知边界)）、CPZ 内部结构与压缩算法。

## 引擎概述

- **脚本**：`*.ps3`（`PS2A` 头，见 [file-formats.md](file-formats.md) §1）。剧情、界面逻辑、
  系统命令全部是同一套字节码；系统命令走统一分发表（`case N` → 命令号 `0x2000+N`）。
- **图像**：`*.pb3`（`PB3B` 头，6 种 codec，见 [file-formats.md](file-formats.md) §2）。
  界面贴图是**扁平文件名**（`config02_chip.pb3`），CG/立绘在 CPZ 封包里。
- **封包**：`*.cpz`（`CPZ7`/`CPZ6`，成员名与密钥由脚本在启动时传入）。
- **音频**：`mog3x32.dll`（仅依赖 KERNEL32 的 MOG/OGG 封装库，见 [engine-mechanics.md](engine-mechanics.md) §4）。
- **文本编码**：Shift-JIS。引擎内部把字节直接合成 16 位码位交给 GDI，
  **转码完全由 `LOGFONT.lfCharSet` 决定**，因此换编码只需要 charset + 引导字节判定两处，
  见 [text-rendering.md](text-rendering.md)。

## 本卷文档导航

| 文档 | 内容 |
|---|---|
| [file-formats.md](file-formats.md) | PS2A / PB3B / CPZ 判型与布局；PB3B 六种 codec 的实现状态；头部自加密 |
| [engine-mechanics.md](engine-mechanics.md) | 资源查找槽位（外挂覆盖的根本机制）、系统命令分发表、代理 DLL 注入形态、随包字体的三条硬性要求 |
| [text-rendering.md](text-rendering.md) | 文本渲染链路：`CreateFontA` → `GetGlyphOutlineA` → GDI、charset 两档、**双字节判定的两支汇编形态**、标点禁则、标题栏 |

工具库：`galrev/cmvs/`，纯标准库，**所有游戏标定值由调用方注入**：

- `ps3`：PS2A 编解码（头部字段、字节变换、LZSS、文本段读写）
- `pb3`：PB3B type 1 解码 + 全字面编码

## 新项目快速通道

拿到一部疑似 CMVS 的游戏，按此清单起步：

1. **判型**：游戏根有 `cmvs32.exe` / `cmvs64.exe`；`data/code/*.ps3` 头 4 字节 `PS2A`；
   `data/image/**/*.pb3` 头 4 字节 `PB3B`。
2. **先读脚本**：`galrev.cmvs.ps3.load()`，取 `.strings()` 看是不是目标语言。
   密钥在文件头里，不需要额外参数；85 份量级语料的零改动往返应逐字节一致。
3. **找覆盖槽位**：读 `start.ps3` 的挂载命令，确认 `data/update/` 与 `data/image/update/`
   是不是**槽 0**（见 [engine-mechanics.md](engine-mechanics.md) §1）。
   是的话，放同名文件进去即可覆盖，原生文件一个字节都不用改。
4. **换编码（若目标是 GBK/UTF-8）**：读 [text-rendering.md](text-rendering.md)，
   确认**双字节判定**与**标点禁则**两处都要改——只改 charset 会出现「字能显示但宽度算错」。
5. **不要引擎也能跑**：先只做「脚本 + 贴图」两件事，这足以出完整汉化；
   字体与标题栏属于锦上添花。

## 跨作需重验清单

| 结论 | 语料观测 | 为什么要重验 |
|---|---|---|
| 双字节判定位置 | 内联 9 份，`cmp X,0x9F` / `lea+0x20` 两支混排 | 构建变化即变，且两种编码混排 |
| 标点禁则位置 | 一个函数内联 8 份，共 32 处比较 | 同上 |
| `CreateFontA` charset 立即数 | 4 个 `push 80h` | 函数布局随编译器变化 |
| 默认字体串地址 | 同一串在 exe 里有 4–5 份拷贝 | 权威的是调用点参数，需 xref 定位 |
| PB3B 分块边长 | 16 | 可能是其它值 |
| PB3B 位深 | 24 / 32 并存 | 24 位解码后补 alpha=255 |
| 字体 face 数 | 引擎只请求 weight 400 与 600 | `cWeight` 表在 `.rdata`，值可能不同 |
| 资源表槽位数 | 脚本 2 槽、图片 10 槽 | 随作品变化 |

## 已知边界

- **PS2A 指令集语义未做**：本卷只覆盖容器层。要读剧情文本，`strings()` 足够；
  要理解分支/变量/系统命令语义，需要另行反汇编系统命令分发表。
- **CPZ 内部结构未做**：成员名与密钥由脚本运行时传入，静态解析需要先解析 `start.ps3`。
- **PB3B 只实现 type 1**：type 2/3（JBP1 差分）、type 5（预测器+累加）、type 6（外部底图）
  只记录布局，未实现。GARbro 与 CMVS-Engine 的 `Pb3Decoder` 可作参照。
- **LZSS 压缩未实现**：编码器只走「全字面」，体积约 1.8 倍。解码端已实现。
