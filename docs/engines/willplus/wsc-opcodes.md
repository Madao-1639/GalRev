# WillAdv VM 指令集（WSC opcode）

实证来源：CROSS†CHANNEL 原版 `CROSSCHANNEL_v0.992.exe`（manifest `will.willadv.exe`，`.text` 熵约 6.55 = 明文）中的脚本解释器 **`sub_40A050`**（约 26 KB）。全部结论为该 handler 的逐字节静态分析结果；其他 Willplus 作品的 handler 地址与布局需重验。

## 两级查表分发

```asm
movzx edx, byte_4108E0[opcode-2]   ; opcode -> case 号（case 126 = 未实现）
add   ecx, -2 ; cmp ecx, 0FDh      ; 有效 opcode 范围 2..0xFF
jmp   ds:jpt_40A392[edx*4]         ; case -> handler（全部在本函数内）
```

分发是**两级查表**：opcode 先经 `byte_4108E0` 映射为 case 号，case 号再经跳转表 `jpt_40A392` 落到 handler。完整 256 项 opcode→case→handler 地址对照表见 [`data/wsc_handlers.json`](../../../data/wsc_handlers.json)。

**引擎 size 的口径**：一条指令的真实长度以 handler 里的 `add dword_4F88F8, N`（脚本指针步进）为准——这是唯一不可争议的真值来源；反汇编器与引擎 size 逐条吻合才算布局正确。

## 图形指令（逐字节参数，handler 实证）

| WSC | 功能 | 操作数（字节） | 引擎 size | 备注 |
|---|---|---|---|---|
| `0x45` | 立绘层状态 | `<u8 slot><u8 sub><u8 flag><u8>` | 5 | 写 per-slot 数组 `dword_61E5xx[slot*0x1EF70]` |
| `0x46` | **CG / 背景** | `<u16 x><u16 y><u32><u8 flags><name\0>` | 9+串 | `flags` bit0/bit1 → x/y 是**预设表 `word_6D9148` 的索引**；画布 800×600 |
| `0x47` | | `<u8><u8>` | 3 | |
| `0x48` | **立绘** | `<u8 slot><u16 x><u16 y><u16><u16><u8 flags><u8><name\0>` | 11+串 | slot 索引 `dword_5F8890[slot*0x150]`；x/y 同 `0x46` 预设机制 |
| `0x49` | 位号开关 | `<u8 slot><u8 a><u8 b>` | 4 | per-slot `dword_5F888C[slot*0x150]` |
| `0x54` | 遮罩 | `<u8><name\0>` | 变长 | |
| `0x55` | | `<u8>` | 2 | |
| `0x64` | | `<u8 a><u16 x><u16 y><u8 z><u16 w>` | 9 | |
| `0x65` | | `<u16><u16><u8>` | 6 | |
| `0x66` | | `<u8 a><u16 x><u16 y><u8 z><u16 w>` | 9 | |
| `0x67` | | `<u8 a><u8 b><u8 c><u32>` | 9 | |
| `0x68` | 文本框矩形 | `<u16 x><u16 y><u16 w><u16 h><u8>` | 10 | 走消息框 API（`sub_45F0F0`/`sub_4650C0`） |
| `0x74` | | `<u16>` | 3 | |
| `0x8c` | 脚本头 | `<u16 script_index><u8 00>` | 4 | 全局脚本号，见 [file-formats.md](file-formats.md) |

### `0x48` 立绘 handler（`sub_40BF0D`）逐操作数

| 偏移 | 类型 | 含义 |
|---|---|---|
| 0 | u8 | slot（槽/位号） |
| 1 | u16 | x |
| 3 | u16 | y |
| 5 | u16 | 未知 |
| 7 | u16 | 未知 |
| 9 | u8 | flags（bit0/bit1 选预设索引） |
| 0xA | u8 | 未知 |
| 0xB | — | 文件名（NUL 结尾串） |

- **`x`/`y` 是字面值**：`flags@9` 的 bit0/bit1 未置位时直接写进槽结构（CROSS†CHANNEL 语料 4381 条立绘的 `flags` 全为 0——单语料统计，跨作需重验）。
- **handler 里没有 `x==0` 分支**：`x == 0` 就是字面坐标 0，即**贴屏幕左缘**（原版立绘高度恒等于画布高，x 是精灵左边缘）。任何把 x==0 解释成「未指定/居中」的转换行为都是偏差。
- **`0x46`/`0x48` 的坐标支持预设索引**：用 `flags` 位选择「字面值 / 预设表条目」，与 Steam WS2 `0x46` 的 bitmask 机制同源——两代引擎都有「预设站位」设计。

### `0x49` 位号开关

`slot u8@0`、`flag u8@1`：`flag != 0` 置位（显示）、否则清位（隐藏）；写 per-slot 标志数组。立绘的显隐控制就是它，**不是** `0x64`。

## 文本、音频与控制指令

- `0x41` 叙述：`<u16 id> 00 0f <文本 CP932> 00`；`0x42` 对话：`<u16 id> 00 0f 0f <说话人 CP932> 00 <文本 CP932> 00`。id 是字符串池序号（与选项文本共用一个池，见 [../../cross-engine/wsc-to-ws2.md](../../cross-engine/wsc-to-ws2.md)）。
- `0x02` 选项表：`<u8 count> 00` 后跟 count × (`<u16 sid>` 文本 NUL + 11 字节选择器描述)；分支由其后的 `0x06` 阶梯或引擎路由承担。
- `0x06` 文件内跳转：`<u32 绝对目标> 00`。
- `0x0a` BGM：mode `0xff` = 播放（`<u8 loop><u32 fade><name\0>`）、mode `0x00` = 停止（无操作数）。
- `0x23` 语音：`00 ff ff 00 00 00 00 65 00 <name\0>`，前缀恒定。
- `0x07`/`0x09` 脚本转移：`<name\0>`；**兼有调用语义**（转移后仍有活代码 = call-and-return），见 [../../cross-engine/wsc-to-ws2.md](../../cross-engine/wsc-to-ws2.md)。
- `0xff` 结尾：`<u32 a><u32 b>`。
- 其余变量 / 标志 / 渐变驱动类指令（`01`/`03`/`25`/`26`/`4a`/`82` 等）为引擎状态原语，详见 `data/wsc_handlers.json` 与本库 `galrev/willplus/wsc.py` 的 handler 注释。

## 「时机 = 流序」

`0x41`/`0x42`（文本）只写文本区状态（`4FB0xx`），`0x48`（立绘）只写槽状态（`5F88xx`），两者互不交叉、**按流序各自即时生效**。因此一条立绘指令属于它**之后最近的一句台词**——语音、对白、立绘的相对顺序就是演出顺序。AdvHD（Steam 版）遵循同一规则，跨引擎转换时立绘块的发射时机不变。

## 本库反汇编器

`galrev/willplus/wsc.py` 是线性反汇编器（输入须为已解密形态，先过 `galrev.willplus.decrypt.decrypt_wsc`），操作数布局与上表逐条吻合；对 CROSS†CHANNEL 语料 324/324 个文件解析零失败、引擎 size 一致（单语料统计，跨作需重验）。凡新增 opcode 布局结论，先按 handler 的 `add dword_4F88F8, N` 核准引擎 size，再改反汇编器。
