# GalRev — Galgame 引擎逆向知识库

按**游戏引擎**组织的逆向知识与通用工具库。目标：遇到相同引擎的新项目时直接复用已有结论与代码，避免重复分析。

知识来源是实际完成过的内容还原补丁项目（原版内容还原到 Steam 版），已剥离项目专属细节，只保留引擎层面可复用的部分：

| 来源项目 | 涉及引擎 | 主要贡献 |
|---|---|---|
| CROSS†CHANNEL Steam 版还原补丁 | Willplus（原版）、AdvHD（Steam 版） | 两代引擎的指令集与文件格式、WSC→WS2 忠实转换、AdvHD 存档机制（CCST） |
| A Sky Full of Stars 内容还原补丁 | AdvHD（原版与 Steam 版） | Steam 成就机制、WS2 字节模态分析、PNA 图层机制 |

## 目录结构

```
GalRev/
├── docs/                      # 知识文档（按引擎分卷 + 跨引擎卷 + 方法论）
│   ├── README.md              # 文档索引与阅读路径（从这里开始）
│   ├── methodology.md         # 跨引擎逆向方法论（与引擎无关，优先读）
│   ├── engines/
│   │   ├── advhd/             # AdvHD（MoeNovel Amaneko 系，WillPlus 新引擎）
│   │   └── willplus/          # Willplus 旧引擎（WillAdv）
│   └── cross-engine/          # 跨引擎主题（WSC→WS2 转换等）
├── galrev/                    # 引擎通用 Python 库（纯标准库，无项目耦合）
│   ├── advhd/                 # Arc/WS2/PNA/LNG/Lua 5.3/存档 读写与反汇编
│   ├── willplus/              # 老式归档/WSC 解密与反汇编
│   └── convert/               # WSC→WS2 忠实转换器（全参数化）
└── data/                      # 引擎级权威数据表
    ├── ws2_operand_formats.json   # AdvHD WS2 全部 164 个 opcode 的操作数格式表
    └── wsc_handlers.json          # Willplus WillAdv VM 全部 256 项 opcode handler 表
```

## 快速上手

- **遇到 AdvHD 引擎的新游戏**：先读 `docs/engines/advhd/README.md`，按其中导航深入；工具直接 `from galrev import advhd`。
- **遇到 Willplus 旧引擎的游戏**：先读 `docs/engines/willplus/README.md`；工具 `from galrev import willplus`。
- **需要把原版内容移植到 AdvHD Steam 版**：读 `docs/cross-engine/wsc-to-ws2.md`，转换器在 `galrev/convert/`，项目专属标定值全部通过参数注入。
- **任何逆向工作开始前**：读 `docs/methodology.md`，里面的判据与陷阱每一条都来自实打实的返工教训。

## 使用约定

- `galrev/` 全部模块只依赖 Python 标准库，可作为独立包复制或以路径引用进具体项目。
- 所有涉及具体游戏标定的值（BGM 曲目号基数、立绘名前缀、站位档位、lng XOR 密钥等）一律是**调用方参数**，库内不内嵌任何一部游戏的值。
- 文档只写当前成立的最新结论，不含探究历史与勘误；每篇文档自包含，跨文档以相对链接引用。
