# krkrz + M2「MDF」 —— 文件格式规范

krkrz（KiriKiri Z）提供归档与 TJS 运行时；M2 的工具链把剧情编译成 **PSB 对象图**，
由 `psbfile.dll` 解释执行。本文只写「磁盘上长什么样」，运行时行为见
[engine-mechanics.md](engine-mechanics.md)，加密层见 [hxv4-crypto.md](hxv4-crypto.md)。

## 0. 判型速查

| 判据 | 观察点 |
|---|---|
| 引擎 | `plugin/` 里有 `psbfile.dll`、`KAGParserEx.dll`、`krmovie.dll`、`layerExDraw.dll`；exe 内有 `TVPXP3Archive`、`TVPSelectXP3FileOrFolder` 等 `TVP*` 字符串 |
| 剧情载体 | `.scn` 文件头 `mdf\0`；加密归档解出来的脚本是**裸 PSB**（`PSB\0`） |
| 归档 | `*.xp3`，11 字节魔数 `58 50 33 0D 0A 20 0A 1A 8B 67 01` |
| 加密变体 | `0x17` 处为 `0x80`（真索引偏移在 `0x20`），索引树里多一个 `Hxv4` 块，条目名是伪名 |
| 加密实现 | 插件 `PackinOne.dll`（RTTI 可见 `BasicCryptFilter<BlockStreamCipher<ChaCha<DJBernsteinStreamCipher>>>`、`ArchiveStreamBuf`）|

---

## 1. xp3（krkrz 归档）

### 1.1 普通 xp3

```
0x00 11 魔数 58 50 33 0D 0A 20 0A 1A 8B 67 01
0x0B 8  u64 索引偏移
索引区:
  u8  compress_flag           0 = 索引明文，1 = 索引 zlib
  [u64 zsize, u64 fsize]      仅 compress_flag = 1
  entry[]:
    "File" + i64 size
      "info" + i64 size + u32 flags, i64 fsize, i64 zsize, u16 namelen, UTF-16LE name
      "segm" + i64 size + [u32 flags, u64 offset, u64 fsize, u64 zsize] * n
      "adlr" + i64 size + u32 adler32
```

- `segm.flags & 1` = 该段 zlib 压缩；`offset` 相对文件头。
- **文本打散**：段数据若以 `FE FE <mode> FF FE` 开头，其后是 tvp 文本混淆
  （mode 1 = 相邻 bit 两两对调，解出 `FF FE` 开头的 UTF-16LE；mode 2 = zlib）。
  这是引擎层通用机制，不限于剧情脚本，凡是 `FF FE` 开头的 UTF-16LE 资源都可能被套。
- 索引里的文件名是 UTF-16LE。

**顶层还可以有 `hnfn` 块（哈希 → 真名映射表）**，它不是 `File` 条目，而是并列在索引根上：

```
"hnfn" + i64 size + n × [u32 hash, i16 namelen, UTF-16LE name]
```

带加密/哈希命名的发行版（条目名是 32 位十六进制或伪名）**必须有这张表**：
引擎按请求名先经它映射到哈希，再去索引里找条目。缺表的表现是「文件明明在包里却报
`<name> not found`」。

**写法：每个文件一条 `hnfn` 块**（官方打包器的做法：所有 `hnfn` 在前、`File` 在后，两者数量相同）。
把全部名字塞进一条 `hnfn` 虽然能被部分读取器接受，但 krkrz 用它建立「归档内子目录别名」
（`addAutoPath("arc.xp3>sub/")`）时只认得出第一个文件名 ⇒ 该子域只能覆盖第一个文件，
其余请求名全部落到别的 autopath（典型表现：补丁包只有第一个脚本生效）。写包一律逐文件一条。

`File` 块内 chunk 顺序实测为 `time, adlr, segm, info`（首个条目可省略 `time`）；
`info.flags` 的 `0x80000000` 位表示内容加密。**顺序敏感**：按别的顺序重写可能导致
条目被跳过（建议照官方顺序）。

- 库：`galrev.krkr.xp3`（`parse_xp3` / `extract_entry` / `unpack_xp3` / `pack_xp3`）

### 1.2 Hxv4 变体（wamsoft 加密）

```
文件头 40 字节
  0x00 11 魔数
  0x0B 8  u64 = 0x17            ★ 诱饵：照它解析索引必崩
  0x13 4  u32 = 1
  0x17 1  u8  = 0x80            ★ 标志：真索引偏移在 0x20
  0x18 8  保留 0
  0x20 8  u64 真索引偏移
索引树 = zlib( chunk 树 )：先一个 Hxv4 块，再逐 File 块
  Hxv4 描述符 14 字节： i64 payload_offset | u32 payload_size | u16 flags(bit0 = open_flag)
  File 块与普通 xp3 相同
```

- 条目名一律是**伪名**：第 i 条 = `U+5000 + i`（`倀倁倂…`）。
  **【跨作需重验】** 个别包 entry 1 会写成字面 `startup.tjs`，此时**条目数 = 记录数 + 1**，
  记录从 entry 1 起。
- **entry 0 恒为 1×1 警告 PNG**（910 B，tEXt 关键字 `Warning`），不过过滤器、原样写出。
  **【跨作需重验】** 内容与「是否参与过滤」都可能不同，遇到异常先核对 entry 0。
- `*.sig`（若存在）是 `-- SIGNATURE - SHA256/PSS/RSA --` 的 base64 签名，只做完整性校验，
  与解密无关；**未签名的新增包不影响加载**（见 [engine-mechanics.md](engine-mechanics.md) §3）。
- 负载的加密与内容过滤见 [hxv4-crypto.md](hxv4-crypto.md)。
- 库：`galrev.krkr.hxv4`

---

### 1.3 Cx 变体（CxEncryption）

与 Hxv4 **不是同一方案**，单独成篇见 [cx-crypto.md](cx-crypto.md)。速查：

```
0x17 4 u32 = 0x80           变体标记
0x20 8 u64 真索引偏移        索引本身**明文**（常 zlib）
条目名 = md5(UTF-16LE 全路径)；adlr = adler32(明文)
条目内容 = Cx 加密（XOR 密钥流），Encrypt 与 Decrypt 同式
```

判型：`0x17 == 0x80`、索引可解析、但内容解不开 → Cx（Hxv4 的索引直接是密文）。
参数每作一组、需注入；库 `galrev.krkr.cx`。

## 2. `.scn`（剧情脚本容器）

| 外壳 | 结构 | 出现场合 |
|---|---|---|
| `mdf` 包装 | `"mdf\0"` + `u32 原文长度` + zlib 流（无尾随校验字节） | 明文补丁/原版归档里的 `.scn` |
| 裸 PSB | 直接 `"PSB\0"` | 加密归档解出来的脚本文件 |

**解析入口必须同时接受两种魔术**（读前 4 字节判断），不能只看扩展名 ——
加密归档解出来的文件没有 `.scn` 后缀。

---

## 3. PSB v3（M2 序列化对象）

### 3.1 头部（44 字节）

```
0x00 "PSB\0"
0x04 u16 version = 3        0x06 u16 header_encrypt（非 0 = 头部加密，本文方案不支持）
0x08 u32 header_length = 0x2C
0x0C u32 offset_names         名字区（charset / 字典树数据 / 字典树根 / 对象图数据）
0x10 u32 offset_strings       字符串偏移表
0x14 u32 offset_strings_data  字符串正文（UTF-8，NUL 分隔）
0x18 u32 offset_chunk_offsets
0x1C u32 offset_chunk_lengths
0x20 u32 offset_chunk_data
0x24 u32 offset_entries       对象图根节点
0x28 u32 checksum             adler32(0x0C..0x27)
```

典型布局（同一文件内）：**names 区（含对象图）→ 字符串偏移表 → 字符串正文 →
chunk 偏移/长度表 → chunk 数据**。chunk 区在纯脚本文件里通常为空数组/空数据。

### 3.2 值类型（全部小端）

| 类型字节 | 含义 |
|---|---|
| 0x00 / 0x01 | None / Null |
| 0x02 / 0x03 | False / True |
| 0x04 | 整数 0 |
| 0x05..0x0C | 整数 N1..N8（跟随 1..8 字节） |
| 0x0D..0x14 | 数组 ArrayN1..N8：N 字节计数 + 1 字节元素宽度类型 + 数据 |
| 0x15..0x18 | 字符串索引（指向字符串偏移表） |
| 0x19..0x1C | 资源索引（chunk） |
| 0x1D / 0x1E / 0x1F | float 0.0 / float32 / float64 |
| 0x20 | List：偏移表 + 子对象（偏移相对偏移表结束处） |
| 0x21 | Objects：名字索引数组 + 偏移表 + 子对象 |
| 0x22..0x25 | ExtraChunk |

### 3.3 names 区是字典树

```
charset 数组       每项是一个字符的偏移修正量
names_data 数组    节点：每项 = 下一个节点的下标
name_indexes       每个名字对应一棵树的根下标
解码： node = names_data[root]
       while node != 0:
           nxt  = names_data[node]
           byte = (node - charset[nxt]) & 0xFF
           node = nxt
       得到的字节倒序拼接 → UTF-8 解出名字
```

### 3.4 字符串池

`offset_strings` 处是偏移表，`offset_strings_data + offset[i]` 起、到下一个 `0x00` 为止，
是第 i 个字符串的 **UTF-8** 正文 → 中文可直接写入，不需要编码转换。

### 3.5 重写策略与验收判据

只重排**字符串正文 + 偏移表**，其余字节原样复制，再修正头部 5 个偏移并重算 checksum：

- 适用前提：字符串**数量不变**（只换内容，不增删）
- 不变量：不改内容重建 ⇒ PSB body **与原始逐字节相同**（第一道验收闸）
- 要改整数（如页的 `length`）必须实现**完整对象图序列化器**：
  数组宽度、`idx` 类字段等也可能随之变化
- 库：`galrev.krkr.psb.PsbFile` / `rebuild(new_strings)`

---

## 4. TJS binary Variant（Hxv4 映射表用的编码）

Hxv4 映射表明文是这套编码，**与 PSB 的值编码不是同一套**（整数定长 8 字节大端、数组内联）：

| 标签 | 含义 |
|---|---|
| `1` | null |
| `2` | string：`i32` 字符数 + UTF-16BE |
| `3` | octet：`i32` 字节数 + 数据 |
| `4` | int：8 字节大端 |
| `5` | real：8 字节大端 double |
| `0x81` | array：`i32` 计数 + 元素 |
| `0xC1` | dict：`i32` 计数 + (键=string, 值) 对 |

库：`galrev.krkr.hxv4.tjs_parse`

## 5. 其它已知载体

| 文件 | 说明 |
|---|---|
| `*.tjs` / `*.ks` | KAG 系统脚本，**明文源码**（UTF-16LE），含 UI 文本与字体配置 |
| `*.pimg` | M2 图片容器（PSB 变体，**没有 `scenes`**；位图在 chunk 资源区，见 §5.1） |
| `*.tlg` | TLG 位图（TLG5 / TLG6，见 §5.1），也会作为 `*.pimg` 的 chunk 出现 |
| `*.mmv.json` | 立绘/背景动画（AffineSourceMMV）配置 |
| `*.otf` | 补丁自带的字体（字形预热由 `prerenderfontex.tjs` 等接管） |

### 5.1 `.pimg`：PSB v3 + 位图 chunk（TLG）

`*.pimg` 是「PSB 对象图 + chunk 资源区」的二合一容器：对象图里 `layers[]` 描述图层，
每个图层的位图单独作为一份 chunk 资源，键名 `<layer_id>.tlg`，内容是 **TLG** 位图。

chunk 表结构（在对象图之后）：`chunk_offsets`（相对 chunk 数据区起点）、`chunk_lengths`、
然后 chunk 数据区。**打包器把每个 chunk 起点按 4 字节对齐**，两张表后面还会有一段对齐填充
（样本：表区 35 字节 = 17 + 18，chunk 起点 0 / 704 / 1412 / …，全是 4 的倍数）。
改资源时必须照抄这套对齐与填充，否则连「原样替换」都不能逐字节往返，后面的数据也会整体错位；
验收判据就是「同内容替换后与原文件逐字节一致」。【跨作需重验：对齐粒度与填充是否恒为 4 字节】

**另一种容器版本**：素材包里的 `*.pimg` 也可能是 **PSB v2**（头部没有 `header_length`），
字段顺序为「names / strings 区在前，chunk 三偏移在 8 起第 5/6/7 个 u32」，且 **chunk 数据在文件尾部**
（其后只剩十数字节尾巴）。这种包替换 chunk 只改两个整数阵列 + 尾部数据，其余字节不动；
判据同样是「零改动往返逐字节一致」（20 张样本 20/20 命中）。

库侧：`PsbFile.resource_bytes(i)` 取 chunk 原始字节、`PsbFile.replace_resources({i: blob})` 换资源并
重排表（照抄 4 字节对齐与表区填充、重算三偏移与 `0x28` checksum、`mdf` 外壳回压缩）。

TLG 有两个变体，引擎两种都读：

```
TLG5: "TLG5.0\0raw" (10) | 0x1a | colors | width u32 | height u32 | blockheight u32
      blocksize[nblocks] u32 × nblocks
      逐块、逐颜色平面：
          u8  mark      0 = LZSS 压缩，非 0 = 原始字节
          u32 size
          payload

TLG6: "TLG0.0\0sds" (10) | 0x1a | 0x00 | 0x00 | "TLG6.0\0raw" | …（Golomb 编码，头部同族）
```

TLG5 的要点（都是踩过的坑）：

- 平面数据是「**行差分 + 颜色相关**」：`g` 直接累加；`b` / `r` 先加同像素的 `g` 再累加；
  累加值最后还要加**上一行同列**的像素；alpha 单独一路累加。
- **首行也以 0 为基准**。GARbro 的 C# 实现把首行 alpha 写死成 `0xff`，照抄的表现是
  「自己编的图回放正常、进游戏整块透明」。判据：解官方界面图的文本层，背景 alpha=0 应占多数、
  文字像素 alpha≈255。
- 压缩用的是 TVP 自带的 **LZSS**（4096 字节滑窗，在整张图的所有块、所有平面之间**连续**复用，
  匹配允许与当前位置重叠＝逐字节 run-length），**不是 zlib**。
- `colors` = 3（BGR）或 4（BGRA）；TLG5 内部通道顺序是 **BGRA**。
- 【跨作需重验】同一归档里 TLG5 与 TLG6 可能混用（取决于素材来源），写入端统一成 TLG5 也能被读。

范围说明：本知识库**不含图像/视频编解码实现**（见 [README.md](README.md)），这里只记录容器与
编码结构，便于判型、审计和写最小解码器；实现放进各项目自己的工具里。
