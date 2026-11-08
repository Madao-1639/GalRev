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
