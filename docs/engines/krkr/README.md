# krkrz + M2「MDF」脚本引擎

krkrz（KiriKiri Z）是吉里吉里系列的当代分支（32 位 PE，TJS2 运行时 + XP3 归档）。
**M2 的「MDF」工具链**把剧情编译成 PSB 对象图，由插件 `psbfile.dll` 解释执行 ——
所以这类作品的剧情既不是 KAG 的 `.ks`，也不是 TJS 源码，而是 PSB 里的字符串池。

本卷覆盖：归档（普通 xp3 与 wamsoft 的 Hxv4 加密变体）、PSB 序列化、MDF 脚本文本模型、
运行时行为与补丁形态。**不含** TJS2 虚拟机逆向与图像/视频编解码。

## 引擎概述

- **归档**：`*.xp3`（chunk 树索引）；加密变体在索引里多一个 `Hxv4` 描述符，
  条目名退化为伪名（`U+5000 + i`），负载用 XChaCha20-Poly1305 加密、条目内容再过一层 DRIP XOR 过滤器
  （见 [file-formats.md](file-formats.md) §1、[hxv4-crypto.md](hxv4-crypto.md)）。
- **脚本**：`.scn` = `mdf\0` + zlib + **PSB v3**；加密归档解出来的是裸 PSB。
  PSB 是「名字字典树 + UTF-8 字符串池 + 对象图」的通用序列化格式，同一套结构也用在图片容器（`.pimg`）上
  （见 [file-formats.md](file-formats.md) §3）。
- **文本**：在 `scenes[].texts[行][分页]` 的字符串槽里，UTF-8，中文可直接写入；
  行内夹着 `%NNN;` / `#RRGGBBAA;` / `#;` / `\n` 等标记，另有 `length` 字段需要跟随重算
  （见 [script-text.md](script-text.md)）。
- **运行时**：剧情由 `psbfile.dll` 解释；`KAGParserEx.dll` 只管系统级 KAG；归档/加密在 `PackinOne.dll`
  （但密钥由 exe 内嵌 bootstrap 模块运行时算出，见 [engine-mechanics.md](engine-mechanics.md) §2）。
- **补丁形态**：归档优先级 = **注册时间（越晚越高）**，新增包只要能压过提供者就生效；发行版样本中明文 xp3 可被直接读取，
  但「加不加密」不是生效前提、也不是障碍 —— 是否需要同格式取决于该作加载器是否按头部判定（见 [engine-mechanics.md](engine-mechanics.md) §3）。
- **多语言**：部分发行版把同一份脚本按语言分域存放（Hxv4 的 `domain_hash`），
  解包产物会看到「同内容多副本」（见 [engine-mechanics.md](engine-mechanics.md) §4）。

个别作品的 exe 加壳（`.text` 熵 8.0），但另一发行版常是明文：**明文样本用于提出假设，
本作样本用于定案**（见 `docs/methodology.md`）。

## 本卷文档导航

| 文档 | 内容 |
|---|---|
| [file-formats.md](file-formats.md) | 判型速查、普通 xp3 / Hxv4 变体容器、`.scn` 两种外壳、PSB v3（头部/值类型/名字字典树/字符串池/重写策略）、TJS binary Variant、其它载体 |
| [script-text.md](script-text.md) | MDF 文本模型：场景键、对白 5 元、分页 3/5 元、`length` 两派口径、行内标记、回写不变量、跨版本对齐键 |
| [hxv4-crypto.md](hxv4-crypto.md) | 映射表帧与记录（`packed` 低位 = 条目下标）、DJB 布局 AEAD、DRIP VM 与四层 XOR 过滤器、参数清单与获取流程、判据与不变量 |
| [engine-mechanics.md](engine-mechanics.md) | 引擎身份/指纹、执行层分工、启动链与**归档注册顺序/优先级**、名字与域规范化、补丁插入的两种通用手段、域=目录哈希、字体重定向、移植操作顺序 |

工具库：`galrev/krkr/`，纯标准库，**所有游戏标定值由调用方注入**：
`xp3`（普通归档读写）、`hxv4`（加密变体读取 + 参数 profile）、`hxv4_write`（加密变体写入，与读取端严格互逆）、`hxv4hash`（名字层：`file_hash` / `domain_hash`）、`psb`（对象图与字符串池级重写）、`scn`（MDF 文本模型）。调试器/MCP 客户端属工具而非格式知识，不随库分发。

## 新项目快速通道

拿到一个疑似本组合的游戏，按此清单起步：

1. **判型**：`plugin/` 有无 `psbfile.dll`；剧情文件是否 `.scn` 且头 4 字节 `mdf\0`；
   xp3 的 `0x17` 处是否 `0x80`（Hxv4 变体）。判据见 [file-formats.md](file-formats.md) §0。
2. **先试明文归档**：若目录里已有 `unencrypted.xp3` 之类明文包，或手上是民间补丁的 xp3，
   `galrev.krkr.xp3` 直接读；能读到 `*.tjs` 与 `.scn` 就说明容器侧不用动。
3. **加密归档**：需要参数 profile（见 [hxv4-crypto.md](hxv4-crypto.md) §4/§5）。
   参数必须从运行中的游戏读；静态派生值只作参考，**不能用 tag 之外的现象当验证**。
4. **提文本**：读前 4 字节判 `mdf\0` / `PSB\0`，用 `galrev.krkr.scn.ScnFile` 取
   `iter_messages()` / `iter_selects()`；脚本身份取 `root["name"]`，不要用文件名。
   加密归档会给出「同内容多副本」的目录形态，按语言域与归档优先级取舍。
5. **校验**：字符串池级重写的**零改动往返必须逐字节一致**；`length` 口径按目标版统一；
   行内标记数量与顺序守恒（`docs/methodology.md` 的第一道闸）。
6. **回写**：只换字符串时用 `PsbFile.rebuild({index: new_text})`；
   要改 `length` 等整数需补完整对象图序列化器。
7. **出包**：把改好的脚本按真名打进普通 xp3 覆盖进游戏目录；不要改已签名原包。

## 跨作需重验清单

| 结论 | 语料观测 | 为什么要重验 |
|---|---|---|
| 伪名规则 | `U+5000 + i`；个别包 entry 1 为字面 `startup.tjs`（条目数 = 记录数 + 1） | 是否所有包都用伪名、特例形态是否一致 |
| 条目 0 | 1×1 警告 PNG，910 B，**不过过滤器** | 内容与是否参与过滤可能不同 |
| 对白行 flag / 分页形态 | `[3] = 64`；3 元与 5 元分页并存 | 其它作品可能不同元数或 flag |
| `length` 口径 | 原版/民间工具链 = 原始长度；官方本地化 = 显示长度 | 取决于打包工具，不是引擎常量 |
| 语言域 | 3 个 domain 对应 3 种语言 | domain 可能只是分包维度 |
| bootstrap 例程 RVA | `0xE2D0` / `0x15630` / `0x157D0` / `0x10410`，seed 全局 `0x81758` | 换构建即变 |
| manager 结构偏移 | `core+0x3038` key、`+0x3058` nonce1、`+0x3078` nonce0 | 可能随引擎版本变化 |
| DRIP 规模 | context 3106 × u32、lanes 128 条 | 查表长度与 lane 数可能不同 |
| 名字哈希盐 | `xp3hnp` | 由启动脚本给出 |
| 名字哈希算法 | `BLAKE2s-256(名字 + 盐)`、目录用 SipHash-2-4（均 UTF-16LE） | keyed 变体存在与否需按包验证 |
