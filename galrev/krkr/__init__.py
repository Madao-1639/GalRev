"""galrev.krkr —— krkrz（KiriKiri Z）+ M2「MDF」脚本引擎通用库。

模块清单（全部纯标准库，无项目耦合，不内嵌任何一部游戏的标定值）：

- xp3:   普通 xp3 归档读写（索引/条目/段、adler32、文本打散 FE FE 的 `decrypt_text` / `encrypt_text`；不含加密变体）
- cx:    Cx 变体加解密（条目内容 XOR 密钥流；参数 profile 由调用方注入），并暴露可复用的流式 XOR（`tweak` / `crypt_stream`）
- cxdec_v2: Cxdec V2（新版 cxdec 插件）：内嵌模块参数自描述 + 调插件本体取密钥；XOR 层复用 cx.crypt_stream
- hxv4:  krkrz 的 Hxv4 加密归档（wamsoft 变体）：XChaCha20-Poly1305 索引 + DRIP 过滤器
         + 参数 profile 载入。参数是每游戏构建一组，必须由调用方注入（见 load_json）
- psb:   PSB v3 对象图读取、「字符串池级」重写（零改动往返逐字节一致），以及 `PsbGraph` 整图重排（`parse_graph()` → `build()`，用于插入/删除对象；零改动逐字节一致）
- tjs2:  TJS2100 字节码读取 + 反汇编（只读，不反编译；用于读 KAG/脚本层逻辑）
- scn:   MDF 剧情脚本（.scn = `mdf\0` + zlib + PSB）的文本模型：
         scenes / texts / selects、页形态、length 口径、行内标记
- mdf:   多语言块布局（同一行内嵌 jp / en / cn …）：语言块 `[name, text, plain, plain2]`、
         ruby `[よみ,N]` + 后随 N+1 个基字、plain = 读音版 / plain2 = 基字版（规则可 4839/4839 复验）
- tlg:   TLG5 / TLG6 位图**解码** + TLG5 编码（含 `TLG0.0\0sds` 15 字节外壳）。
         `decode() -> Image`（带 `.kind`）/ `header() -> Header` / `encode(..., kind=)`。
         TLG5/6 解码与 GARbro `ImageTLG.cs` 逐像素一致；`encode(kind="TLG6")` **显式抛错**
         （Golomb 编码器 + 30 种预测器的选取搜索成本远大于收益，而引擎两个变体都读）
- hxv4hash:    名字层（`file_hash` = BLAKE2s；`domain_hash` = SipHash-2-4(小写目录 + 盐)，根目录只哈希盐）
- hxv4_write:  写入 Hxv4 变体（索引树 / 映射表封装 / 条目过滤器 / adler），与读取端严格互逆

引擎文档：`docs/engines/krkr/`（README / file-formats / script-text / cx-crypto / hxv4-crypto / engine-mechanics）。
"""
