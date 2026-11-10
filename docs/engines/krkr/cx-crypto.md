# krkrz + M2「MDF」—— Cx 加密层（CxEncryption）

krkrz 的 `.xp3` 除了明文与 [Hxv4 变体](hxv4-crypto.md)，还存在 **Cx 变体**：
索引明文，但**条目内容**由一张按 `adlr` 派生的 XOR 密钥流加密。
两者是**不同方案**（Hxv4 用 XChaCha20-Poly1305 索引 + DRIP 过滤器；Cx 用字节码 VM 生成密钥流），
判型时不要混用。

## 1. 判型

| 特征 | Cx 变体 | Hxv4 变体 | 普通明文 |
|---|---|---|---|
| XP3 头 `0x17` 处 | `0x80` | `0x80` | 无（`0x0B` 即索引偏移） |
| 真索引偏移 | `0x20` 处 u64 | `0x20` 处 u64 | `0x0B` 处 u64 |
| 索引 | **明文** chunk 树（常 zlib） | `Hxv4` 描述符 + XChaCha20 密文 | 明文 chunk 树 |
| 条目名 | `md5(UTF-16LE 全路径)` | 伪名 `U+5000+i` + 哈希映射表 | 真名或哈希名 |
| 条目内容 | **Cx 加密**（`info.flags` 带 `0x80000000`） | DRIP XOR 过滤 | 明文 |
| 名字层参数 | 不需要盐（名字就是 md5） | `HashDomain` 盐 + BLAKE2s | — |

判型方法：`0x17 == 0x80` 且 `0x20` 处 u64 指向**明文**索引（首字节为 `0`/`1`）→ Cx。
索引能解析、但条目内容解不开 → 就是 Cx。

## 2. 参数（每作一组，必须由调用方注入）

| 字段 | 含义 |
|---|---|
| `mask` / `offset` | `base_offset = (hash & mask) + offset`；越过后密钥换成 `(hash >> 16) ^ hash` |
| `prolog_order[3]` | Cx 程序生成期「入口指令」三选一的分支顺序 |
| `odd_branch_order[6]` | 奇分支的六种运算顺序 |
| `even_branch_order[8]` | 偶分支的八种运算顺序 |
| `control_block[1024]` | 「 Encryption control block」表，取反后参与运算 |

`hash` = 条目的 `adlr` = **`adler32(明文内容)`**（既是完整性校验，也是密钥）。

公开资料里常见写法 `CxEncryption(0x12B, 0x7AB)` 只给了 `mask`/`offset`，
其余四项同样必需。

## 3. 参数从哪来（离线可行）

GARbro 的方案库 `GameData/Formats.dat`（`GARbroDB` magic + deflate + BinaryFormatter）
按**游戏标题**索引保存整份 `CxScheme`。做法：

1. 用 GARbro 的 `GameRes.dll` / `ArcFormats.dll` 反射读取对应标题的 `CxEncryption` 实例，
   导出 `mask`/`offset`/`prolog_order`/`odd_branch_order`/`even_branch_order`/`control_block` 成 JSON；
2. 之后全部用 `galrev.krkr.cx` 离线加解密，**不需要运行游戏、不需要调试器**。

注意：

* GARbro 按**游戏标题**反查方案依赖它自己的 game map（存档名/同目录 exe 名 → 标题）；
  若宿主程序（如 `GARbro.Console`）没有该映射，会报 `unknown format` —— 直接用反射取参数即可。
* 参数与**游戏构建**绑定，游戏更新后需重新导出。

## 4. 加解密

`Encrypt` 与 `Decrypt` 是**同一算式**（XOR），所以同一份实现既能读也能写
（这意味着可以生成与官方同构的加密归档）。

判定要点：

* 段（`segm`）若带 zlib（`flags & 7 == 1`），**先解压、再解密**（写入时相反：先加密、再压缩）。
  Cx 的密钥流以常量 XOR 为主，不改变熵，所以密文仍可压缩，压缩率与明文接近。
* 偏移按**解压后**的流位置累计（跨段的连续位置），不是文件偏移。

## 5. 库

```python
from galrev.krkr.cx import CxCrypt

crypt = CxCrypt.load("profile.json")     # 每作一组参数
plain = crypt.crypt(entry_adlr, cipher)  # 解密（同式加密）
```

`galrev/krkr/cx.py` 是 GARbro `KiriKiriCx.cs` 的逐语义移植（Cx 程序生成 + 字节码 VM +
三层密钥）。**验证方式**：对同一段密文，本模块输出必须与 GARbro 的 `ICrypt.Decrypt`
逐字节一致；建议把若干条目解密后的 `sha256` 固化成黄金向量做回归。

## 6. 跨作需重验

| 结论 | 语料观测 | 为什么要重验 |
|---|---|---|
| 名字层就是 `md5(UTF-16LE 全路径)` | 索引里 943/944 条为 32 位十六进制，且与 `md5(全路径)` 命中 | 有的包会带盐或大小写变体 |
| `adlr = adler32(明文)` | 逐条比对成立 | 也可能用别的校验（如 crc32） |
| `File` 内 chunk 顺序 `time, adlr, segm, info` | 官方包一致 | 部分工具按固定顺序写，引擎可能顺序敏感 |
| `.sig` 不参与引擎校验 | 替换归档后游戏照常启动 | 不同发行版可能校验 |

## 7. 二代：Cxdec V2（新版 `cxdec` 插件）

同一套内容加密的第二版：**容器不变、XOR 算式不变、密钥输入不变**，变的是「密钥怎么算」。
样本：M2 的 9-nine-NewEpisode（系列第 5 作）。

| 项 | 初代 Cx | Cxdec V2 |
|---|---|---|
| 方案住在哪 | 参数与生成器编进 exe | exe `.rdata` 内嵌插件 PE（`TVPSetXP3ArchiveExtractionFilter`） |
| 参数从哪来 | 外部方案库（GARbro `Formats.dat`）或反编译 | 模块**自描述**：`--data--PARAMS`（22 B）+ `TABLE`（4096 B） |
| 控制块方向 | 存的是**取反**表，用前再取反 | 存**原表**，直接 `table[idx]` |
| 三个 order 数组 | 下标 = 随机值，值 = form | 下标 = **form**，值 = 命中该 form 的随机值（与初代互为逆排列） |
| 程序生成 | 固定字节码 + 小 VM | `DynamicCodeGen`：128 lane，运行时生成（seed = lane 索引，LCG；bit7 → MT19937） |
| 索引条目名 | 常见 `md5(UTF-16LE 路径)` | 也可能直接是**真名**；`hnfn` 可有可无【跨作需重验】 |
| 段压缩 | 常见 zlib | 常见**不压缩**（`segm.flags = 0`）【跨作需重验】 |

### 7.1 判型

容器判型与初代完全一致（`0x17` 处 `0x80`、真索引偏移在 `0x20`、索引明文、条目
`info.flags` 最高位 = 1），所以**光看头部区分不了两代**。两条实操判据：

1. 用已知的初代参数解不开（签名不对、结构校验全挂）；
2. exe 的 `.rdata` 里能找到 `"module\0"` 开头的那段内嵌模块（初代没有）。

### 7.2 参数（模块自描述）

exe `.rdata` 里一段：`"module\0"` + 16 字节名字槽 + u16(解压后长度 / 256) + 1 字节 0 +
u32(zlib 长度) + zlib 流，解出来是 32 位 PE。模块镜像里有两段数据（名字 → u16 字节长 → 数据）：

* `--data--PARAMS`（22 B）：`[0:8]` even、`[8:14]` odd、`[14:17]` prolog（三者都是
  「按 form 索引」的排列）、`[17]` flags（bit7 = 用 MT19937 而非 LCG）、`[18:20]` mask、
  `[20:22]` offset；
* `TABLE`（4096 B = 1024 × u32）：控制块**原表**。长度 > 0x1000 时插件会另存第一张表，并可与
  相邻 dword 做字节级异或后再用（`sub_10002330`），本样本未触发【跨作需重验】。

### 7.3 密钥

与初代同一模型，只是 `exec` 的实现搬到了插件里：

```
adlr        = adler32(明文)
base_offset = offset + (adlr & mask)
lane        = adlr & 0x7F ; src = adlr >> 7
key64_a     = exec(lane, src) | (exec(lane, ~src) << 32)
key64_b     = 同上，key = adlr ^ (adlr >> 16)
```

`key64` 的低 32 位是 `ret1`（`key3` 与两处附加字节），高 32 位是 `ret2`（两处位置）。
流式 XOR 完全复用 `galrev.krkr.cx.crypt_stream`，两代共用。

### 7.4 取密钥的两条路

1. **复现生成器（不推荐）**：要把记录流布局、form 索引方向、每 lane 的 RNG 消耗全部对齐。
   已知与初代实现的偏差：**stage 重试时插件不复位 RNG**、部分分支的长度记账不同 ——
   这两点会改变「哪一 stage 被接受」，于是整条 lane 的程序都变。实测：把参数按
   「order 取逆 + 控制块取反」对齐后，仍然解不开。
2. **调插件本体（推荐）**：把内嵌模块当 DLL 加载（32 位宿主），按 PARAMS/TABLE 初始化，
   再逐 `adlr` 调它的求值函数。`galrev.krkr.cxdec_v2.derive_keys()` 就是这条路
   （借 Windows 自带的 32 位 PowerShell 承载）。密钥只与 `adlr` 有关，算一次缓存成 JSON 即可。

插件内部地址（**每构建一组，必须注入 profile，换版本要重标**【跨作需重验】）：

| 名字 | 作用 |
|---|---|
| `set_mask` | 写入 mask / offset |
| `build` | 建 128 条 lane（返回 0 = 成功） |
| `gen` | `gen(buf40, adlr)` → `+8` = key64_a、`+16` = key64_b、`+24` = base_offset |
| `g_params` / `g_flag` / `g_table` | 运行时全局量：PARAMS 17 B / flags / TABLE 缓冲 |

### 7.5 判据（不需要跑游戏）

* 每条目自证：解出的明文重新算 adler32 必须等于索引里的 `adlr`；
* 结构化校验：PNG 全 chunk CRC + IDAT inflate 长度对 IHDR；`PSB\0`；`TJS2100\0`；`OggS`；`TLG`；
* 注意**隔行（Adam7）PNG** 的原始长度不等于 `w × channels × depth × h`，按非隔行公式校验会把
  正确的解密判成失败（本样本 116/558 张图踩过）。

### 7.6 库

`galrev/krkr/cxdec_v2.py`：`extract_embedded_module` / `Scheme`（`from_module` / `from_json` /
`to_json`）/ `derive_keys` / `decrypt` / `encrypt` / `KeyCrypt`（写端）/ `load_keys` /
`save_keys` / `read_entry`。不内嵌任何一部游戏的标定值，参数与 RVA 全部由调用方注入。
