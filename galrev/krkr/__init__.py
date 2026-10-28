"""galrev.krkr —— krkrz（KiriKiri Z）+ M2「MDF」脚本引擎通用库。

模块清单（全部纯标准库，无项目耦合，不内嵌任何一部游戏的标定值）：

- xp3:   普通 xp3 归档读写（索引/条目/段、adler32、文本打散 FE FE；不含加密变体）
- hxv4:  krkrz 的 Hxv4 加密归档（wamsoft 变体）：XChaCha20-Poly1305 索引 + DRIP 过滤器
         + 参数 profile 载入。参数是每游戏构建一组，必须由调用方注入（见 load_json）
- psb:   PSB v3 对象图读取与「字符串池级」重写（零改动往返逐字节一致）
- scn:   MDF 剧情脚本（.scn = `mdf\0` + zlib + PSB）的文本模型：
         scenes / texts / selects、页形态、length 口径、行内标记
- hxv4hash:    名字层（`file_hash` = BLAKE2s；`domain_hash` = SipHash-2-4(小写目录 + 盐)，根目录只哈希盐）
- hxv4_write:  写入 Hxv4 变体（索引树 / 映射表封装 / 条目过滤器 / adler），与读取端严格互逆

引擎文档：`docs/engines/krkr/`（README / file-formats / script-text / hxv4-crypto / engine-mechanics）。
"""
