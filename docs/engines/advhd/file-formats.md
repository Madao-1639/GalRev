# 文件格式规范

本文档覆盖 AdvHD 引擎的资源容器与文本格式：Arc 归档、WS2 脚本、LNG 文本、定制 Lua 5.3 字节码、NameTable.txt、PTF 字体。指令集细节见 [ws2-opcodes.md](ws2-opcodes.md)，PNA 分层图像见 [pna.md](pna.md)。

## Arc 归档格式

Arc 是 AdvHD 引擎的自定义归档格式，用于打包全部游戏资源。

### 文件结构

```
[Header 8 bytes] [Table N bytes] [Data ...]
```

Header（8 字节）：

```c
struct Header {
    uint32_t count;       // 成员数量
    uint32_t table_size;  // 表大小（字节）
};
```

Table Entry（每成员一条，变长）：

```c
struct Entry {
    uint32_t size;        // 数据大小
    uint32_t offset;      // 相对偏移（相对于 data_start = 8 + table_size）
    wchar_t name[];       // UTF-16LE 编码的文件名
    uint16_t terminator;  // 0x0000（UTF-16 NUL）
};
```

关键特性：

1. 文件名编码为 UTF-16LE，以 `\x00\x00` 终止。
2. 偏移字段是**相对偏移**，读取时加上 `data_start` 得到绝对位置；按绝对偏移写出会导致整档不可读。
3. 数据段紧随表结构之后，按表中顺序连续存储。
4. 读写必须保持成员名字节精确（不能经文件系统往返，会损坏日文 UTF-16LE 名）。

### null padding 陷阱与规范化

某些 Arc 文件在「成员名扫描终点」与「数据段起点」之间存在游离的 null padding：

- 后果是每次读写产生不同的 SHA256，安装器哈希校验失败。
- 检查点在名字扫描终点与数据起点**之间**，不是数据区头 2 字节（后一位置查不到该问题）。
- 解决：`galrev.advhd.arc.normalize_arc_padding()` 去除 padding 统一为规范格式；`galrev.advhd.arc.verify()` 会拒绝带 padding 的归档。

工具：`galrev.advhd.arc`（`read_raw` / `write_arc` 原子写 / `verify` / `normalize_arc_padding`）；超大归档（数百 MB 的语音档）用 `galrev.advhd.arcstream` 流式处理。

## WS2 脚本格式

WS2 是场景脚本（对话、跳转、CG 显示等），逐字节 rot6 混淆。

### 混淆算法

```python
# 解码（rotate left 6）
def decode(raw):
    return bytes(((c << 6) | (c >> 2)) & 0xff for c in raw)

# 编码（rotate right 6 == rotate left 2）
def encode(data):
    return bytes(((c << 2) | (c >> 6)) & 0xff for c in data)
```

解码后暴露 ASCII opcode 与操作数（脚本名、资源名等）。指令集、类型码与全部 opcode 格式见 [ws2-opcodes.md](ws2-opcodes.md)。

### 末尾 8 字节：明文「消息数 / 选项条目数」尾表 ★

脚本**文件末尾 8 字节**是引擎要用的一张表：`[u32 消息数][u32 选项条目数]`（即 `0x14` 条数 / `0f` 条目数）。

- ⚠️ **这 8 字节不参与上面的混淆**（混淆作用于代码区，尾表原样存储）：直接读文件末尾 8 字节就是两个小整数；
  反过来，把整个文件过一遍 `decode()` 会把它们旋转成垃圾值——反汇编器把末尾那条 `ff` 的「操作数」读成两个大数，
  **那不是引擎操作数**，不要按操作数解释、更不要硬编码。
- 引擎在**加载脚本**时读它（取 `data[size-8]` / `data[size-4]`），用来给「已读消息位图」分配容量
  `(消息数 + 选项条目数 + 7) / 8` 字节；位图存在存档目录的 `MessageFlag.dat`，见
  [save-system.md](save-system.md)「MessageFlag.dat」。
- ⇒ **任何改变 `0x14` / `0f` 条数的改动（插入、删格、拆格、换脚本）都必须同步重写这 8 字节**，
  且要写成**明文**、在**编码之后**写（先写会被混淆旋转）。容量与脚本消息数不一致时，引擎标记已读会写下标越界
  → 堆破坏（概率性闪退，`0xc0000374`）。
- 自查：`raw[-8:] == struct.pack('<II', 0x14 条数, 0f 条目数)`；在未改动的同引擎语料上逐脚本成立
  （某作 363 个脚本 363/363）。工具：`galrev.advhd.ws2` 的 `read_tail_counts()` / `tail_counts()` /
  `set_tail_counts()` / `check_tail_counts()`（**`set_tail_counts()` 必须在 `encode()` 之后调**）。

## LNG 文本容器

LNG 是 AdvHD 的文本替换机制，每个含文本的 `.ws2` 对应一个同名 `.lng`，两者同池存放。

```
[Header]
  uint32  count                 // 条目数
  uint16  length[count]         // 每条的字节长（含结尾 NUL 对 00 00）
[Payload]
  count 条字符串背靠背，无对齐填充
```

- 单条字符串为 UTF-16LE 编码，每字节再 **XOR 混淆**；容器本身不做 rot6。
- **XOR 密钥是逐作标定值，不是引擎常量**：密钥来自该游戏 `GameInfo.lua`（读档路径上引擎从 `getHostInfo` 的数字字段取一字节）。实测观测值：CROSS†CHANNEL 语料为 `0x2C`，A Sky Full of Stars 语料为 `0xCE`；新游戏必须从 `GameInfo.lua` 确认。
- 终端控制标记（`%K`/`%P`/`%N` 等）以普通文本形式随条目携带。
- 引擎按**播放位置**替换文本（无 id 字段），位置对应严格等式与汉化通路见 [localization.md](localization.md)。
- 工具：`galrev.advhd.lng`（`parse_lng` / `encode_lng`，密钥为必填参数）。

## 定制 Lua 5.3 字节码

`Script.arc` 里的 `*.lua` 成员是 Lua 5.3 编译产物（不是混淆，rot6 不适用）。

文件头：

| 字段 | 值 |
|------|-----|
| 签名 | `\x1bLuaS`（`\x1bLua` + 版本 `0x53`） |
| 格式字节 | `0x00` |
| `LUAC_DATA` | `19 93 0d 0a 1a 0a` |
| 字长声明 | `int=4, size_t=4, Instruction=4, lua_Integer=8, lua_Number=8` |
| `LUAC_INT` | `0x5678`（8 字节） |
| `LUAC_NUM` | `370.5`（double，8 字节） |

**与官方 Lua 5.3 的两处差异**（穷举验证的唯一解）：

1. 字符串长度字段 `LoadSize` 是 **1 字节**（官方为 `sizeof(size_t)` = 4 字节）；判据是把（前置字节数，字符串长度宽度，计数宽度，行号宽度）全部组合跑一遍，只有 `(1, 1, 4, 4)` 能让归档全部成员逐个精确消耗到文件末尾且字符串可读。
2. opcode 枚举在**索引 9 处多一项**，其后全部后移 1 位 —— `op=10` 是 `SETTABLE`、`op=11` 是 `NEWTABLE`（官方为 9/10）；多出的码在两部观测游戏的全部 Script.arc 里从未出现，身份未知，不影响反汇编。

`LegacyGame.inc` 是纯文本的 include 清单（CRLF，每行 `include "xxx"`），决定实际加载哪些成员；`LegacyGame.lua` 不在清单里，是死代码（原版即如此）。

工具：`galrev.advhd.luac53`（解析）/ `galrev.advhd.luadis53`（反汇编，`--archive` 显式给归档路径）。

## NameTable.txt（说话人名替换表）

引擎的说话人名替换表：脚本里的 `%L?<名>` 标记会被拿去查它，命中则替换为表右列内容。表是 UTF-16LE，不受脚本内窄字节 CP932 的限制，是角色名汉化的正路（见 [engine-mechanics.md](engine-mechanics.md)「文本编码路径」）。

格式：

- 编码 UTF-16LE，**无 BOM**；换行 CRLF；制表符分隔；**左右两列都带完整标记前缀**。

```text
%LCTaichi	%LC太一
%LCMisato	%LC见里
```

关键规则：**表键必须等于脚本里的标记**。每个游戏用哪个字母由脚本生成时固定（CROSS†CHANNEL 语料用 `%LC`，A Sky Full of Stars 语料用 `%LF`），与语言切换无关（同作英文版与简中版用同一字母）。前缀对不上时引擎查不到表，名字框会一直显示原文。存放位置见 [engine-mechanics.md](engine-mechanics.md)「语言包目录」。

## PTF 字体

PTF 是引擎的字体容器（`Fonts.arc` 内 `.PTF` 成员），内部 = `[u32 解压后大小][LZSS(xor 字节流)]`，解压输出再全量异或得字体本体（OpenType `OTTO` / TrueType `glyf` 均可）。

格式（反汇编 + 实机验证，格式对 header `sub_4591E0` 观测）：

- 文件前 4 字节 = 解压后大小（LE u32），后接 LZSS 字节流：
  - flag 字节按 **bit0 先出** 消费 8 位；bit=1 → 1 字节 literal；
    bit=0 → 2 字节 match token：距离源 = `(b1>>4) + 16*b0`（12-bit 环形窗 0x1000），
    长度 = `(b1 & 0xF) + 2`；
  - **环形窗内存的是 XOR 后的字节**；写指针**从 1 起**（明文样本 `0x4593CD`: mov esi,1，跨作需重验）；
- 解压输出逐字节与 xor_key 异或得到标准 OpenType / TrueType 字体文件；
- 引擎随后 `AddFontMemResourceEx` 注册到**进程字体表**，经 `CreateFontIndirectW` +
  `lfCharSet=GB2312_CHARSET` 按 Lua 传入的族名匹配（族名匹配**不走向系统字体表**）。

**XOR 密钥与 lng 同源**（该作 `GameInfo.lua`，见 「LNG 文本容器」），观测值见同上。**拿到新游戏先查 GameInfo.lua**。

**工程要点**：
1. 字体文件熵高，LZSS 压缩对它无实际收益（原版某作 M 位 15.6 MiB 明文打出 17.6 MiB PTF，同样膨胀）；通用压缩包装器无收益；match token 的环形坐标是错误高发点。因此本仓库打包器只生成**纯字面量 LZSS**（flag=0xFF、每 8 字节前 1 flag、零 match）：膨胀固定 ~12.5%，与解压端语义严格一致，零错排风险。
2. **字体格式**用 TrueType（magic `00 01 00 00`）而不是 CFF OpenType（`OTTO`）：GDI 的 `CreateFontIndirectW` 在 `CharSet=GB2312_CHARSET` 下对 CFF 匹配失败，TrueType 通路可正确匹配。
3. **族名查找在本进程内** —— 换字体后，Lua 侧 `g_fonts.name` 等族名与字体内部族名**逐字一致**才会被匹配；不必给玩家装系统字体。
4. 字体族群 name（Windows family）匹配不合并 style：厂商对 Bold 等字重典型的 Windows 家族名是**无后缀** (family) + **独立 style**；引擎侧按族名请求，若**需要**把 Bold 作为一个家族名字来匹配，应把 Bold 字重的 name 表 id1/4/16 重写为带 suffix 的族名（fontTools `name` 表 API）。

工具：`galrev.advhd.ptf`（` lzss_decode` / `lzss_encode_literal` / `pack_ptf` / `unpack_ptf`，**xor_key 为必填参数**）。