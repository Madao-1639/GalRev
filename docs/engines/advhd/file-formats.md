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

PTF 是引擎的字体容器（`Fonts.arc` 内 `.PTF` 成员）。

- 已识别部分：对文件主体做逐字节 XOR 0x2C 后，偏移 5 处出现 OpenType/CFF 的 `OTTO` 签名，其后 `numTables`、`searchRange` 等与 OpenType 头部字段吻合，表目录区域可见 `BASE` / `CFF ` / `GPOS` / `GSUB` / `VORG` / `cmap` / `head` 等标准表标签。
- 即 **PTF ≈ 5 字节自定义前缀 + XOR 0x2C 混淆的 OpenType 字体**；封装细节（前缀语义、表目录未完全对齐）**未逆向完毕，如实待考**。
- 工程要点：字体替换可直接整体复用一份含目标字形集的 Fonts.arc（中文显示还需 Lua 侧 `CharSet = GB2312_CHARSET`），无需自制 PTF；如需自制，按上述封装思路打包 OpenType 后实机验证。详见 [localization.md](localization.md)「字体」。
