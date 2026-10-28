# krkrz + M2「MDF」 —— Hxv4 加密层（wamsoft）

容器结构（描述符、伪名、entry 0）见 [file-formats.md](file-formats.md) §1.2。
本文写三层：映射表、内容过滤器、参数（含获取方式与判据）。
库：`galrev.krkr.hxv4`（纯标准库，参数由调用方注入）。

## 1. 映射表（`Hxv4` 负载）

```
负载 = [16B Poly1305 tag][XChaCha20 密文]
明文 = u32 解压后长度 + zlib( TJS binary Variant，见 file-formats.md §4 )
记录 = domain_hash[8] + file_hash[32] + packed u32 + key u64
```

- `nonce` 由描述符 `flags bit0` 选：0 → `nonce0`，1 → `nonce1`（各 24 字节）。
- `packed`：**高 16 = archive_slot，低 16 = 条目下标**；记录顺序 ≠ 条目顺序，绑定必须用下标（§6）。
- `key` 是打包方随手挑的 64 位自由值，与序号无关；读包只需用它，不需要知道来源。
- `domain_hash` 是**目录路径的哈希**（不是语言标签；「语言维度」只是它的一个特例，见 [engine-mechanics.md](engine-mechanics.md) §4）。
- 明文数量级：每条记录约 50 字节 + 每个域的表头，实际负载远小于「条目数 × 记录大小」的朴素估算。

## 2. 密码学细节

- 算法是 **XChaCha20-Poly1305，内层 ChaCha20 为 DJB 布局**：64 位计数器 + 64 位 nonce，
  **不是** RFC 8439 的 IETF 布局。
  ※ 对 counter < 2³²，两种布局的 state 前两个字相同，**不能用「能解开」来区分实现是否正确**。
- 子密钥与 MAC：

```
subkey   = HChaCha20(key, nonce[0:16])
poly_key = ChaCha20Block(subkey, counter=0, nonce[16:24])[0:32]
密文     从 counter=1 起
tag      = Poly1305(poly_key, ct ‖ pad16 ‖ LE64(0) ‖ LE64(len(ct)))      # 无 AAD
```

- 原语正确性用公开向量回归：Poly1305（RFC 7539 §2.5.2）、ChaCha20 块（§2.3.2）、
  HChaCha20（draft-irtf-cfrg-xchacha §2.2.1）。

## 3. 内容层：DRIP VM + 四层 XOR

```
key64 ──DRIP(key64, open_flag)──> 48B 种子状态 ──> 四层 XOR 过滤器 ──> 明文
```

顺序：**先按 `segm.flags bit0` zlib 解压，后过过滤器**；之后再处理 `FE FE` 文本打散。

**DRIP VM**：

- 128 条 lane 程序，每条是 `(param, opcode)` 序列；opcode 以模块 RVA 标识，共 21 种
  （加/减/乘/移位/按位组合/查表/递归/停机…）
- 1024+ 项 dword 查表；`get64(v)` 的低半 = 对 `v >> 7` 求 `lane[v & 0x7F]`，
  高半 = 同一条 lane 对 `~seed` 求值

**48 字节种子状态**：

| 偏移 | 内容 |
|---|---|
| `[0:8]` | `get64(key_lo)` |
| `[8:16]` | `get64(key_hi)` |
| `[16:20]` | `split = holder[5] + (holder[4] & (key64 >> 16))` |
| `[24:40]` | 16B bulk key（反复 `~get64(~key)` 产出） |
| `[44]` | 1（has_drip） |
| `[45]` | 0（null_mode） |

其中 `open_flag & 1 == 0` 时才用 `holder[2]`/`holder[3]` 扰动 key 的高低 32 位（**方向别写反**）。

**四层 XOR 过滤器**（加解密同一函数）：

1. 前 16 字节用 bulk key 逐字节 XOR
2. 按 `split` 切两段
3. 每段用「按逻辑位置旋转的 dword key」整段 XOR
4. 每段在 `pos0`/`pos1` 各 XOR 一个字节

## 4. 参数

| 参数 | 大小 | 作用 |
|---|---|---|
| `hxv4_key` | 32 B | 映射表 AEAD 密钥 |
| `nonce0` / `nonce1` | 24 B ×2 | 按 `flags bit0` 选 |
| `holder_words` | 6 × u32 | 过滤器种子常量：`[0]` 是 `drip_impl` 指针，`[2..5]` 参与运算 |
| `context_u32` | ≥1024 × u32 | DRIP 查表（语料观测 3106 项，**【跨作需重验】**） |
| `lanes` | 128 条 | DRIP 程序（opcode 归一为模块 RVA） |
| `hash_domain` | 字符串 | 名字哈希的盐（语料观测 `xp3hnp`，**【跨作需重验】**） |
| `hash_key` | 32 B | keyed `file_hash` 变体；`key_len = 0` 时不使用 |

**参数与游戏构建绑定**：游戏更新后必须重抓。建议落成一份 profile（JSON）由调用方注入
（`galrev.krkr.hxv4.Hxv4Profile.load_json`），字段名：
`hxv4_key` / `hxv4_nonce0` / `hxv4_nonce1` / `holder_words` / `context_u32` /
`lanes`（`[{index, records:[[param, opcode_rva], …]}]`）/ `hash_domain`；
`source_module_base = 0` 表示 lane 的 opcode 已归一为 RVA。

## 5. 参数获取：只能从运行中的进程读

参数不是 exe/dll 里的明文常量，而是运行时由内嵌 bootstrap 模块的几个例程算出来的，流程：

1. **必须从调试器启动游戏**（附加太晚，启动阶段已经算完）
2. 在 `LoadLibraryW` 下断 → 认出随机十六进制命名的 bootstrap 模块 → `StepOut` 取基址 →
   在 `base + RVA` 布点。语料观测的 RVA：`0xE2D0`（ManagerCtor）、`0x15630`（BootstrapDerive）、
   `0x157D0`（ArchiveDerive）、`0x10410`（HashKeyDerive），seed 全局 `0x81758`
   **【跨作需重验：RVA 随构建变化】**
3. 命中 `BootstrapDerive` → 记录实参（bootstrap 路径、`PARAMS` 字节）→ `StepOut` 读 manager core：
   `core+0` 6 个 holder words、`core+0x3038` key、`+0x3058` nonce1、`+0x3078` nonce0
   （偏移取自语料，**【跨作需重验】**）
4. 顺 `holder[0]`（= `drip_impl`）取 context 表（`drip_impl + 0x10` 指向）与 128 条 lane
   （`drip_impl + 0x04` 起、每条 0x10 字节描述：`[begin, end]` 指向 8 字节 `(param, opcode)` 记录）

**静态派生不可信**：从 exe 静态派生出的 key 可能把映射表解成合法 TJSON，但**内容全解不开**；
其 context 表也不一定与运行时一致（语料中 128 条 lane 一致、context 不一致）。
判据见 §6。

## 6. 判据与不变量

1. **Poly1305 tag 通过 ⇒ 映射表 key/nonce 正确**（强判据，错一位即失败）
2. **内容仍乱 ⇒ DRIP 的 context 表或 holder 不对**（不是过滤器代码问题）
   - context 错时，个别 key 会碰巧走到「不查表」的 lane 上 → 表现为「只有少数条目能解」，
     极易误判成过滤器实现错误
3. **记录绑定用 `packed & 0xFFFF`（条目下标）+ offset**，`offset` = 是否存在字面 `startup.tjs` 条目；
   绑定后校验「每条记录落到唯一条目、除 entry 0 外每个条目都有记录」
4. 条目 0（警告图）不过滤
5. 离线结果必须与**另一条独立路径**（游戏内注入式解包）逐字节比对，不能只和自己闭环

## 7. 名字层（可选）

- `file_hash = BLAKE2s-256( UTF-16LE(小写名字) + UTF-16LE(盐) )`，盐 = `hash_domain`；名字**不含目录**。
- `dir_hash = SipHash-2-4( UTF-16LE(小写目录 + 盐), key = 16 个 0 字节 )`：目录**带结尾 `/`**、**小写**；**根目录 = 只哈希盐**（这是把陌生包的域翻回目录名的依据，见 [engine-mechanics.md](engine-mechanics.md) §4）。
- keyed 变体（`hash_key` 参与）是否存在需按包验证；实测样本 `key_len = 0`，走 unkeyed。
- 只要文本不必还原真名：脚本自带 `root["name"]`，其余文件按 `domain/file_hash` 命名即可
