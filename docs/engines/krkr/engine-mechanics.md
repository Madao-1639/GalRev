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

### 3.3 名字与域的规范化

- 请求名与 autopath 目录在查索引前会**小写化**（`system/Initialize.tjs` 能命中归档里的 `initialize.tjs` 即为此）。**【跨作需重验】**小写化究竟发生在存储层还是加密层尚未分离验证。
- 解析方式：autopath 前缀与请求名拼成相对路径，再按「**目录部分 = 域、文件名部分 = 条目**」去归档索引里查（域的含义见 §4）。

### 3.4 补丁怎么压过同一路径的官方条目

- **明文 xp3 可被直接读取**：按真名打进普通（未加密）xp3、放进游戏目录即可被读到（发行版样本中基础归档本身就是明文）。是否必须与官方同为加密变体取决于加载器判定方式，**以实测为准**。**【跨作需重验】**
- `*.sig` 是 RSA-PSS 签名，只做完整性校验：**不改已签名原包、只新增未签名包**即可规避风险，也便于用「Steam 校验文件完整性」还原。
- 唯有当提供者注册得**更晚**时（典型是语言段落里的 `<arc>><lang>/scn/`），启动期注册的新归档压不住它。通用手段只有两条：
  1. **重建持有目标文件的那个归档**：逻辑最简单，代价是体积；
  2. **把注册推迟到启动末期**：挑一个「其自身提供者的优先级不高于你的归档、且执行时机在全部注册之后」的脚本文件作载体，在其末尾追加 `addAutoPath(...)`，让你的路径成为最后一次注册。载体文件的挑选与钩子形式是**逐作**问题（受该作启动脚本、语言选择时机、追加包配置影响），不要照搬。
- 注册优先用**带目录前缀**的形态（`<arc>><lang>/scn/`）：只影响该命名空间。用归档根（`<arc>>`）会插手**所有裸名解析**（配置、存档、素材名都要先查一遍），风险面大得多。


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

文本补丁一般不改图片，只换字体与字号，做法是在明文 `*.tjs` 里重定向字体：

- `embfontlist.tjs`：把自带字体文件注册成字面名（font face）
- `deffontmap.tjs`：把 `SystemDefault` / `MessageDefault` / `*NameFont*` 等映射到该字面名；
  语言键（`lang_cn` 等）常被注释掉，走 `lang_*` 通配回落
- `prerenderfontex.tjs` / `editstandtext.tjs` / `textrender.dll` 参与字形预热与排版
- 移植到另一发行版前，先确认目标版自己的字体映射（在加密归档内，用 [hxv4-crypto.md](hxv4-crypto.md) 解出）

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
