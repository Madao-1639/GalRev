# 引擎机制与逆向发现

本文档记录 AdvHD.exe 的脚本 VM 结构、图层槽机制、文本编码路径与语言包机制。文件格式见 [file-formats.md](file-formats.md)，指令集见 [ws2-opcodes.md](ws2-opcodes.md)。

## WS2 脚本 VM

在明文的观测样本 `AdvHD.exe`（内嵌 PDB 路径形如 `…\VAdvHD-1.99a\…\AdvHD_S.pdb`）中定位到脚本 VM 的完整结构，并在另一部作品的脱壳 exe 中逐项核对同构。**opcode 就是原始字节，直接作为分发表下标**：

| 环节 | 某作 exe（明文样本） | 另一作 exe（脱壳后） |
|---|---|---|
| handler 表 | `obj + 0x1B18` | `this + 0x1BA4` |
| 注册 | memset 0x400 后逐项写 handler（151/255 项） | 同构 |
| VM 主循环 | `sub_481450` | `sub_4727B0` |
| 操作数解析 + 格式表 | `sub_4F0A10` + `off_5EE2A8` | `sub_4CD400` + `off_55AEB8` |

- handler 表与格式表都**按原始 opcode 字节索引**；格式表每项指向以 `0xff` 结尾的类型码串（类型码 → 字节数见 [ws2-opcodes.md](ws2-opcodes.md)）。
- 上述地址是**各作 exe 的实测观测值，跨作需重验**；结构跨作同构，地址不同。
- 反汇编器与引擎表的比对结论：字节合计处处一致（全语料零错位）；差异仅在**指令分解**——引擎按变参格式表切分（`2e`/`66`/`0f`/`0e`/`05`/`13` 是引擎多指令、反汇编器合并或反之的典型），需要精确 opcode 计数的场景要注意。

**方法论红线**：某部语料的操作数取值统计只能当旁证；字段是不是绝对偏移、读几个字节，要读该 opcode 的格式表与 handler 定案（自身 exe 优先，其次同引擎明文样本）——「值看起来像偏移」不等于「引擎会照它跳」。

## LAYER_ORDER：图层槽登记表

### 文件格式

LAYER_ORDER 是一个 `.ws2` 文件，但不是可执行剧情脚本，而是**纯键名数据表**：

```
0x3f <count u8> <key0>\x00 <key1>\x00 ... <keyN>\x00 0x05 0xff 00...
  │              └────── 键名列表 ──────┘              └── 终止符
  └= 键数量
```

`0x3f` 就是引擎的 LayersList 指令；尾部 `05 ff …` 是引擎的「音效全停」，说明这个文件是当作普通脚本加载执行的，只是它只做「登记」这一件事。脚本里出现的 `04 LAYER_ORDER` 是 RunFile 子调用——每个立绘/背景块都显式跑一遍这张登记表。

### 性质：登记既有键，不定义键

**槽位本身由引擎内部硬编码**（`insertPNARefLayer` 等 Lua 绑定函数的注册表），LAYER_ORDER 只登记引擎已经认识的键。实测把表里加一个引擎不认识的新键（裸键或三元组）**永远注册不上**。⇒ LAYER_ORDER 里没有位置、没有坐标，也没有「新增槽位」的能力；它是白名单，不是布局表。

各作槽位清单不同（某作为 `ev` 单事件槽 + 19 键，另一作为 `ev01`/`ev02` 双事件槽 + blink/talk 三元组 + 114 键），以本作 LAYER_ORDER 内容为准。

### 引擎封装

引擎在绑定事件 CG 的 PNA 时，会按 PNA 内部的帧组结构自动生成 `ev01/ev01blink/ev01talk` 这类子图层——blink/talk 是引擎「封装」出来的，不从任何脚本显式调用；LAYER_ORDER 中的 blink/talk 键对应 PNA 为口型/眨眼动画提供的帧组数量。

## 事件 CG 槽对 PNA stem 的 7 字节硬限制

`ev01`/`ev02` 事件 CG 槽对 PNA 文件名（不含 `.pna` 后缀的 stem）有**严格的 7 字节（ASCII）硬限制**，某作 A/B 实测定性：

- stem ≤ 7 字节：可以注册（`HIK_17L`、`TEST_7B` 等）。
- stem > 7 字节：**必然失败**（报「サブレイヤー [ev01] は存在しません」）。
- 但 **`st*` 立绘槽无此限制**：15 字节的 Shift-JIS 名（如 `ORG_Aひかり_01M`）正常工作。

失败样本的共同点是 stem 字节数 > 7，与是否有前缀、PNA 内容、图层数、LAYER_ORDER 配置均无关 ⇒ 机制是 ev01/ev02 槽内部使用**定长 7 字节缓冲区**存储 stem，`st*` 槽用更大的缓冲。

命名应用：事件 CG 必须用简短名（不能加占 4 字节的隔离前缀），原版新增 CG 用 9X 段位（`[路线]_9X[L/S]`）；立绘可任意长名并可加隔离前缀。**资源注册失败优先怀疑资源名**，用「换成普通新名」的 A/B 测试最快定性（比继续逆向二进制高效得多）。

## 文本编码路径

`AdvHD.exe` 内建 BIG5 / GB2312 / SHIFTJIS / UTF-8 四种代码页，并提供 Lua 侧转换绑定（`MyConv__lua_utf8tosjis` / `MyConv__lua_sjistoutf8` / `lua_utf8split` 等）。

- 引擎内部对**脚本内窄字节文本按 CP932 解码**：对明文样本统计 `MultiByteToWideChar` 调用点的代码页参数，CP932 占绝对多数（40 处，UTF-8 仅 2 处）。
- **Lua 字符串层是 UTF-8**：`LegacyGame_utf8.lua` 里的非 ASCII 字符串就是 UTF-8 编码且直接传给引擎 API。
- 反方向 `WideCharToMultiByte` 以 UTF-8 为主——那是输出方向（交给 Lua / Steam API）。

**结论**：脚本内窄字节（如 `%LC` 这类标记与其后的名字）受 CP932 限制，简体专用字写不进去；**文本汉化必须走宽字符通路**——正文/选项走 `.lng`（UTF-16LE），人名走 `NameTable.txt`（UTF-16LE），剧本 ws2 字节不动。这也是官方简中的做法（见 [localization.md](localization.md)）。

## 语言包目录范式

引擎支持语言包：`AdvHDLang.dll`（语言桩，内含设置界面的本地化字符串与语言列表）加语言子目录。官方简中的目录结构：

```
<游戏根>/
└── zh-CN/
    ├── AdvHDLang.dll
    ├── Fonts.arc          # 含汉字字形的字体
    ├── Rio.arc            # .lng（正文/选项）+ NameTable.txt（人名）
    ├── Script.arc         # 仅 ui_language.lua（语言开关）
    └── SysGraphic.arc     # 系统界面图（如有汉化）
```

- 中文剧本**没有 ws2**：剧本仍用原 ws2，中文全部经 `.lng`（正文/选项）与 `NameTable.txt`（人名）注入。
- `ui_language.lua` 是语言开关，官方实现恒为两个函数：`getLangPatchFlag()` 置 `PatchFlag = true`，`setInitLang()` 置 `g_altLanguage = true`。
- 无语言子目录的游戏，把 `NameTable.txt` 与 `.lng` 放进主 `Rio.arc` 也可行，但是否完全等效需实机验证。
- 语言开关 Lua 的字节码是定制 Lua 5.3（见 [file-formats.md](file-formats.md)「定制 Lua 5.3 字节码」）。

## 逆向与实测的经验

- **实测优于逆向的场景**：资源注册失败、显示效果一类问题，先做 A/B 测试（快、结论确定）；「资源在槽上注册失败」优先怀疑资源名/身份。
- **逆向不可替代的场景**：文本编码路径（统计 `MultiByteToWideChar` 代码页参数）与名字表机制（从官方语言包对照规则）这类结论，静态分析比逐个试错快且确定。前提是找到一份**未加密的同引擎 exe**；`.text` 加壳的游戏其 `.rdata`/`.data` 仍是明文，格式表可读，壳可脱（脱壳后熵与函数序言密度同明文样本量级）。
- **符号缺失**：无符号 C++ 二进制，函数名以 RTTI 形式存在（`.?AVCPNALayer@@`），Lua 函数注册表运行时按名/哈希动态绑定，无法经字符串 xref 静态定位函数体。
- **先找同引擎的官方样本，但拿到自身样本就先用自身**：同引擎样本给的是假设（枚举、门控、取值域可能与本作不同），自身样本才能定案；这条红线贯穿 [ws2-opcodes.md](ws2-opcodes.md) 与 [pna.md](pna.md)。
