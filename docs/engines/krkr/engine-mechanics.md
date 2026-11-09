# krkrz + M2「MDF」 —— 引擎机制与补丁形态

格式见 [file-formats.md](file-formats.md)，加密见 [hxv4-crypto.md](hxv4-crypto.md)，
文本模型见 [script-text.md](script-text.md)。

## 1. 引擎身份

- krkrz 本体：32 位 PE，`.text` 常在 2–3 MB；指纹字符串 `TVPSelectXP3FileOrFolder`、
  `TVPCannotFindXP3Mark`、`TVPInfoTryingToReadXp3VirtualFileSystemInformationFrom`、`forcedataxp3`，
  RTTI `tTVPXP3Archive` / `tTVPXP3ArchiveStream`。
- 插件集（`plugin/`）：`KAGParserEx.dll`（KAG 解析）、`psbfile.dll`（PSB 脚本）、
  `krmovie.dll`（视频）、`layerExDraw.dll`（图层）、`PackinOne.dll`（归档/加密）、
  `textrender.dll`（文字渲染）、`menu/windowEx/win32dialog/json/…`。
- **同一作品的多个发行版常共用一份基础构建**：Steam 版可能只多一层 DRM 壳（`.bind` 段 + 加密
  `.text`），其它节区与 `.text` 的 vsize 完全相同。⇒ 拿明文样本做静态分析，结论对其它版本同样成立；
  但**凡涉及地址/常量，仍要回本作样本核对**（见 `docs/methodology.md`）。

## 2. 脚本执行层

```
.scn（mdf + zlib 外壳）或裸 PSB → PSB 对象图 → plugin/psbfile.dll 解释执行
```

- 剧情**不走 KAG**（`.ks`）：`KAGParserEx.dll` 只负责系统级 KAG 脚本，剧情由 `psbfile.dll` 消费 PSB。
- 加密归档的解密由 `PackinOne.dll` 实现（RTTI 可见
  `BasicCryptFilter<BlockStreamCipher<ChaCha<DJBernsteinStreamCipher>>>`、`ArchiveStreamBuf`），
  但**密钥不在该 dll 内**：由 exe 内嵌的 bootstrap 模块运行时算出（见 [hxv4-crypto.md](hxv4-crypto.md) §5）。
- 系统脚本（`startup.tjs`、`*.tjs`、`*.ks`）是**明文 UTF-16LE 源码**，UI 文案与字体映射都在这里，
  需要做界面汉化时从这里入手。

### 2.1 读编译后的 TJS（TJS2100 字节码）

发行版的启动脚本常是**编译产物**而不是源码，此时只能反汇编。容器与关键编码：

```
"TJS2100\0" + u32 总长
  "DATA" + u32 size + 常量池
  "OBJS" + u32 size + 对象（每个"脚本块/函数"一个）
```

* `DATA` 常量池按 `byte/short/int/int64/real` 五个池（各有 u32 count，末尾对齐 4）+ 字符串池（`u32 count`，每条 `u32 字符数 + UTF-16LE`，对齐 4）。
* `OBJS` 里每个对象：`"TJS2" + u32 size`，随后 `parent / nameIdx / ctxType / 各计数 / 源位置表 / codeCount + code[] / varCount + variants[] / 父类 getter 表 / 属性表`。
* **code 是 u16 字数组**（不是 u32）：每条指令的高低 16 位分别是 **opcode 与操作数**；
  操作数个数按 opcode 查表（常见：单字指令 1 个、`VM_CONST`/`VM_GPD` 3~4 个、`VM_CALL*` 随 argc 变长）。
* `variants` 是 `(int16 type, int16 idx)`：**`type == 3` 时 `idx` 就是字符串池下标**
  （用于局部槽名/标识符）；`type == 2` 也常见为字符串，按实际包核对。
* 成员名（`VM_GPD/VM_CALLD` 的操作数）落在**对象的名字/属性表**，不是常量池；读不到时
  只能用调用形态（参数序列、相邻常量）反推。

opcode 枚举见 krkr2 源码 `tjs2/tjsInterCodeGen.h`（`VM_NOP` 起；`TJS_NORMAL_AND_PROPERTY_ACCESSER(x)`
会展开成 `x / xPD / xPI / xP` 四连）。指令长度规则可参照 YuaExtract 的
`CxdecAntiMalform/tjs_patcher.cpp::InstructionSize`。

> ⚠️ `@if (XXXX)` 是**编译期**指令：release 版会把整块剔除。依赖 DEBUG 分支的脚本/钩子
> 在正式版里不存在 —— 反汇编时看到常量而没有对应代码，多半就是这个原因。

库：`galrev.krkr.tjs2`（`load(bytes)` → 对象表；`disasm(file, only=None)` → 汇编文本；
遇到未知 VM 码直接抛错，不猜操作数长度）。CLI 支持 `--strings` 只列字符串池、`--only` 只反汇编单个对象。

## 3. 归档加载与覆盖

### 3.1 启动链

```
exe
 └─ 根域 startup.tjs（常见形态是编译字节码，只做参数判定与转发）
     └─ Scripts.execStorage("system/Initialize.tjs")   ← 真正的启动脚本
```

- 与「名字注册」有关的逻辑几乎都在 `Initialize.tjs`（位于 `system/` 域），**不在 exe 里**：exe 只硬编码基础归档名与启动脚本名，**没有 `*.xp3` 通配**。
- 配置文件被加载多次很常见（外壳脚本早一次、`Initialize.tjs` 末尾再一次），两次可能解析到**不同目录域**的同名文件，不要当成同一份。

### 3.2 注册顺序 = 优先级

查找 autopath 时按**注册时间从新到旧**遍历，第一个命中者胜；优先级与路径是否带 `>` **无关**。

| 时间 | 来源 | 注册形态 |
|---|---|---|
| 最早 | exe | 基础归档 `data.xp3` |
| 早 | `addTools("system")` / `addTools("sysscn")` 一类工具目录 | `<dir>/`；同名 `<dir>.xp3` 存在则 `<dir>.xp3>` |
| 早 | subfolders 清单（`video others rule sound bgm fgimage bgimage scenario scn image voice face init font sysse main evimage thum uipsd motion motiondx emote emotedx bishamon` + 语言目录如 `EN/CN/TW`） | `<name>/`；存在则 `<exePath><name>.xp3>` |
| 早–中 | `Scripts.execStorage("Storages.tjs")`（发行方定制点：`addArchive` / `setupSubFolders` / `AppendDataConfig`） | 由该脚本内容决定；append 追加包通常在此注册 |
| 中 | `patch.xp3` | `patch.xp3>` |
| 中 | `patchN.xp3`（N≥2）循环 | **视版本而定**：有的只做存在性探测、`addAutoPath` 被注释掉 |
| 晚 | 追加包与语音子目录 | `patch2.xp3>`、`patch2.xp3>voice/xx/` |
| 最晚 | 语言段落 | `<lang>` 松散目录、`data.xp3><lang>/scn/`、`patch.xp3><lang>/scn/`（整条链最后一次） |

- **`>` 只表示「归档 → 归档内目录」**：`A.xp3>` = 归档根，`A.xp3>sub/` = 归档内子目录；不带 `>` 的是普通目录。
- 同一批代码内的先后也算顺序：语言段落里松散目录（`data/<lang>/scn/`）先注册、`<arc>><lang>/scn/` 后注册 ⇒ **往松散目录放同名文件会被归档内的同名条目压住**（实测，别指望"目录比包优先"）。
- **【跨作需重验】优先级还会成组分层**：exe 用**相对路径**注册的基础归档（`data.xp3`）压住 `addArchive` 系（`exePath + name + ".xp3"` 绝对路径）的同名条目；而启动流程内后注册的相对路径或松散目录又能反过来压住 `data.xp3`。此时「越晚越高」只在同一分组内成立，跨分组看注册方式（相对 / 绝对）。
- **归档子域的覆盖面受索引写法约束**：`addAutoPath("arc.xp3>sub/")` 只有在索引**每文件一条 `hnfn`** 时才能暴露该子目录下所有名字；单条 `hnfn` 时只认第一个（见 file-formats.md §1.1）。与上一条叠加才能解释「某个包只对入口脚本生效」。

### 3.3 名字与域的规范化

- 请求名与 autopath 目录在查索引前会**小写化**（`system/Initialize.tjs` 能命中归档里的 `initialize.tjs` 即为此）。**【跨作需重验】**小写化究竟发生在存储层还是加密层尚未分离验证。
- 解析方式：autopath 是**纯字符串前缀**，与请求名直接拼接后去存储里找；再按「**目录部分 = 域、文件名部分 = 条目**」去归档索引里查（域的含义见 §4）。
- 哈希命名的归档（条目名 = `md5(UTF-16LE 全路径)`，打包器选择）要求拼接结果**能 hash 命中索引项**；因此请求名的扩展名与大小写必须与打包时一致（`a.txt` 与 `a.txt.scn` 是两个名字，`getPlacedPath` 前者为空）。

### 3.4 补丁生效 SOP（决策树）

**先找「引擎会自己注册的合法归档名」，再在合法名里找「同名冲突时优先级最高」的那个；
两者都不满足时，才用「高优先级归档做 TJS hook 注入」，最后才考虑 DLL 注入。**

顺序的理由：越靠前，对原生文件改动越小、越容易回滚、越不容易与其它补丁冲突。

```
① 枚举合法名 ──找到？──否──> ④ 无合法名可用
     │是                       1) hook 注入（需外部注入点）
② 测优先级 ──能覆盖目标？──是──> 完成：补丁 = 该名字的归档
     │否                       2) DLL 注入（hook TVPCreateStream）
③ 借高优先级归档做 hook 注入 ──有载体？──是──> 完成
     │否 ──> ④
```

#### ① 枚举合法名（最优先事项）

合法名只有三处来源：

| 来源 | 查法 |
|---|---|
| **exe 硬编码** | 静态分析脱壳 exe 的初始化代码/字符串（常见 `data.xp3`） |
| **启动脚本（TJS）** | 解包 `system/Initialize.tjs`（常是字节码，见下）、发行方定制脚本（如 `main/Storages.tjs` 一类）。常见 API：`addArchive(name)`、`addTools(name)`、`useArchiveIfExists("xxx.xp3")`、`AppendDataConfig` |
| **配置项** | `AppendDataConfig`（append 包，**只认配置里登记的项**）、`setupSubFolders`（**只注册目录，不注册 xp3**） |

`addArchive(name)` 的实现（官方 `Initialize.tjs`）值得记住：

```tjs
function addArchive(name) {
    Storages.addAutoPath(name + "/");            // 注册**目录**
    return useArchiveIfExists(name);             // 有 name.xp3 才注册归档
}
function useArchiveIfExists(name) {
    with (Storages) name = .chopStorageExt(.extractStorageName(name));
    var arcname = System.exePath + name + ".xp3";   // 绝对路径
    var exist = Storages.isExistentStorage(arcname);
    if (exist) Storages.addAutoPath(arcname + ">");
    return exist;
}
```

**判据不要用「文本是否替换成功」**（它同时受注册与优先级两个变量影响）。
用运行时内存判据（见 `docs/methodology.md`「内存判据」一节）：
注册成功时进程内存会出现 `<name>.xp3>`，数量 ≈ 该归档的条目数；
`addArchive` 系还会额外出现 `<name>/` 目录形式。

**但「注册」不等于「生效」**：条目数命中只说明包被打开列出，不说明目标条目被读取。
生效至少还要两步判据：①搜索「包内独有文本」是否进内存（进了才说明条目被打开）；
②给目标文件埋一个可见标记（改一句文本/加一个弹窗），跑一遍确认标记出现。
只做 ① 容易把「包被列出」误判成「内容被采用」。

#### ② 测优先级（本卷新增实测结论）

**分组规律**（多作一致时可沿用，换作仍需重验）：

| 注册方式 | 能否覆盖最早注册的基础归档的同名文件 |
|---|---|
| exe 硬编码（相对路径，最早注册） | 最高 |
| `addArchive` 系（`System.exePath + name + ".xp3"`，**绝对路径**） | **不能** |
| 启动流程内手动 `Storages.addAutoPath("<相对路径> + ">子域/")` | **能** |

即：**「后注册优先」只在同为相对路径的注册之间成立**；`addArchive` 的绝对路径整体劣于
基础归档的相对路径。**对已注册路径 `removeAutoPath` 后重新 `addAutoPath` 也不会改变这个分组结论。**

验证方法：把自己的条目（与官方同名）放进去，用内存判据搜「包内独有文本」是否进内存
—— 进了说明自己的条目被打开，没进说明被官方包先命中。

#### ③ 借高优先级归档做 hook 注入

前提：找到**会被引擎执行**的 TJS 载体。三种来源：

| 载体 | 条件 |
|---|---|
| 基础归档内某脚本 | 要重建原生归档（体积/完整性代价） |
| **官方补丁/附加归档内的脚本** | 该归档内的脚本有 `KAGLoadScript` 调用链（典型：附加数据包里的初始化脚本） |
| 「基础归档里不存在、但会被可选加载」的脚本 | `KAGLoadScriptIfExists` 一类；**注意 `@if (DEBUG)` 是编译期指令，release 版整块剔除** |

钩子写法（顺序很重要）：

```tjs
// 1) 先执行被替换脚本的原逻辑（原文件改名保留），保持执行环境一致
Scripts.execStorage("<原脚本名>_orig.tjs");
// 2) 再注册自己的搜索路径（相对路径！绝对路径会输给基础归档）
Storages.addAutoPath("<arc>.xp3>scn/");           // 自己的数据归档
Storages.addAutoPath(System.exePath + "scn/");    // 松散目录，便于热更新
```

要点：

* **先转发、后注册**：先 `addAutoPath` 再转发曾导致语言/配置初始化回落到默认值。
* **只注册子域**（`<arc>.xp3>scn/`），不要注册归档根（`<arc>.xp3>`）——
  根域会插手所有裸名解析（配置、字体、素材），风险面大得多。
* 注册顺序 = 优先级（后注册优先），兼容第三方的名字放前面、自己的放后面。
* 替换官方字节码脚本时**必须原样保留并转发**，否则会丢官方功能。

#### ④ 无合法名可用

1. hook 注入：同 ③，但注入点需由外部提供；
2. DLL 注入：hook 引擎的流打开入口（`TVPCreateStream`），把
   `<exePath><任意>.xp3>内部路径` 直接打开，完全绕开归档注册。
   代价：多一个 DLL、可能触发杀软误报、需按 32/64 位适配。
   参考实现：KirikiriTools（`KirikiriUnencryptedArchive`）、KrkrPatch、KrkrExtract。

#### 附：明文包的定位

按真名打进普通（未加密）xp3、放进游戏目录即可被读到（发行版样本中基础归档本身就是明文）。
但**多数发行版的基础归档是加密变体**，此时未加密包需要配套 DLL（如 KirikiriUnencryptedArchive）
才能被读；判型见 [file-formats.md](file-formats.md) §1。

`*.sig` 是实现外的 RSA-PSS 签名，**引擎不校验**（替换归档后游戏照常启动，实测）；
它只影响「Steam 校验文件完整性」会否还原——不改已签名原包、只新增/替换并保留备份即可。

## 4. 域（`domain_hash`）= 目录哈希，语言只是目录名

Hxv4 映射表按 `domain_hash`（8 字节）分组。它**不是"语言标签"，而是目录路径的哈希**：

```
domain_hash = SipHash-2-4( UTF16LE( 小写目录 + 盐 ), key = 16 个 0 字节 )
根目录 = 只哈希盐；目录字符串带结尾 "/" 且小写
```

- 用该式反查语料包即可把域翻回目录：`system/`、`font/`、`image/`、`sound/`、`main/`、`scenario/`、`<lang>/scn/` 等都能对上；去掉结尾 `/` 或改变大小写就得到另一个值 —— 实用手段是**枚举候选目录字符串比对哈希**。
- 于是「语言分区」只是「目录分区」的特例：同一份脚本按 `<lang>/scn/` 各存一份，解包产物就出现同内容多副本（三层目录 `<归档>/<domain>/<file_hash>`）。
- 盐**不固定**，来自映射表里的 `HashDomain` 字段；同一发行版内恒定，换作需重取。**【跨作需重验】**
- 判断语言不要猜：抽一条对白看字形即可；domain 也可能只是分包维度而不对应语言，先按「同内容多副本」验证。

## 5. 字体

### 5.1 静态重定向（改 `*.tjs`）

文本补丁一般不改图片，只换字体与字号，做法是在明文 `*.tjs` 里重定向字体：

- `embfontlist.tjs`：把自带字体文件注册成字面名（font face）
- `deffontmap.tjs`：把 `SystemDefault` / `MessageDefault` / `*NameFont*` 等映射到该字面名；
  语言键（`lang_cn` 等）常被注释掉，走 `lang_*` 通配回落
- `prerenderfontex.tjs` / `editstandtext.tjs` / `textrender.dll` 参与字形预热与排版
- 移植到另一发行版前，先确认目标版自己的字体映射（在加密归档内，用 [hxv4-crypto.md](hxv4-crypto.md) 解出）

### 5.2 KAG 多语言：语言轨 = 块序号，字体按轨分开

- 语言表：`SystemConfig.multiLangLanguageTags = ["jp","en","cn", …]`（`main/default.tjs`），运行时对应全局 `LanguageTags`；`multiLangFirstTag` 决定首次启动语言。
- 每条对白的语言块 `blocks[]` **按语言表序号取**；引擎调用 `GetScnConvertLangList()`（发行方脚本里定义、TJS 侧无调用者）拿到「除首语言外的 tag 列表」，这决定了 `blocks` 的顺序契约。
- 想在运行时**新增一条语言轨**：在启动流程末尾给 `SystemConfig.multiLangLanguageTags` 与 `LanguageTags` 各追加一个 tag 即可（须先让脚本里存在对应序号的块，否则取到空内容）。
- 每轨字体：消息正文吃 **`kag.chDefaultFace`**（`setMessageLayerUserFont()` 逐层写 `layer.userFace`）；名字/选项层走 `kag.getLanguageFont(idx)`，其覆盖槽是 **`kag.scflags["langUserFontFace" + idx]`**（格式来自 `SystemConfig.multiLangUserFontFaceFmt = "langUserFontFace%d"`），**在 `kag` 上而不是 `SystemConfig` 上**。
- 字体映射：`main/config.tjs` 的 `LanguageDefaultFontFaceMap`（正文）/ `LanguageNameFontFaceMap`（名字）/ `MessageDefaultFontFaceMap`（getter，每次访问用 `MakeFontFaceMap` 重建）。**TJS 里行首 `;` 是空语句，不是注释** —— 形如 `;global.X = …` 的行其实会执行。

### 5.3 运行期注册字体（`System.addFont` / `PreRenderFontEx`）

- `font/embfontlist.tjs` 由**引擎启动时**读取（清单结构：`["LICENSE.txt", [ %[name,file,face,capname], … ], …]`）；对应的 TJS 侧加载器 `LoadEmbeddedFontList()` 在部分发行版里存在但运行期看不到产物（`SystemConfig.EmbeddedFontList` 恒为 void），官方嵌入字体走引擎原生路径。
- 原生 API：**`System.addFont(file, flag)`**（有的版本由插件 `addFont.dll` 提供；缺插件时 `typeof System.addFont` 为 `undefined`）。它**只接受真实文件路径**：归档条目（`archive://…`）即使 `Storages.isExistentStorage` 为真也读不出字体，表现为内部取到 void 后抛 `Cannot convert the variable type ((void) to Object)`。
- 包装层：`sysscn/PreRenderFontEx.tjs` 定义 `PreRenderFontEx` 类（只把类挂到 `global.PreRenderFontEx`，实例由 KAG 初始化时创建），其实例方法 **`AddTrueTypeFont(alias, face, file, 0)`** 会做「检查 `System.addFont` → 检查文件存在 → `MakeFontInfoTable`/`TTFFontNames` → `System.addFont(file,0)`」。
- 时机：钩子脚本在 `main/custom.tjs` 末尾执行时 `kag` 还不存在，`PreRenderFontEx` 也未必是实例；把注册放在 `addAfterInitCallback` 里最稳（此时 `PreRenderFontEx` 已是实例、`System.addFont` 已可用）。不要在钩子里重复 `KAGLoadScript("PreRenderFontEx.tjs")`，它会把全局覆盖回类。
- 验证「别名是否真的生效」：把 alias 临时指向一个字形风格明显不同的字体文件（如把黑体来源换成宋体），渲染风格变化即说明链路成立；只改字体名看不出区别。

## 6. 操作顺序（一次文本移植）

| 步 | 做什么 | 库/工具 |
|---|---|---|
| 1 | 判型：krkr + MDF 脚本 + 归档是否 Hxv4 变体 | [file-formats.md](file-formats.md) §0、`galrev.krkr.xp3` |
| 2 | 明文归档直接读；加密归档先从运行中的游戏取参数 | [hxv4-crypto.md](hxv4-crypto.md) §5 |
| 3 | 解包：描述符 → 映射表 → 逐条目「zlib → 过滤器 → 文本打散」 | `galrev.krkr.hxv4.Hxv4Archive` |
| 4 | 提文本：按魔术字节识别脚本，取 `scenes[].texts` / `selects`，按语言域与归档优先级取唯一副本 | `galrev.krkr.scn.ScnFile` |
| 5 | 校验：零改动往返逐字节一致、`length` 口径、标记数守恒 | `galrev.krkr.psb`、`docs/methodology.md` |
| 6 | 回写：字符串池级重写（数量不变）；要改整数再补完整对象图序列化器 | `galrev.krkr.psb.PsbFile.rebuild` |
| 7 | 出包：改好的脚本按真名打进普通 xp3，覆盖进游戏目录 | `galrev.krkr.xp3.pack_xp3` |
