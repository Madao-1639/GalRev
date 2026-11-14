# 第三方打包器

与"游戏引擎"无关的容器格式：它们套在宿主程序外面，先于引擎生效。遇到补丁/整包产物时先看这里，
再决定是否要按引擎的归档格式去解。

| 打包器 | 特征 | 文档 |
|---|---|---|
| Enigma Virtual Box | PE 尾部有 `.enigma1`/`.enigma2` 节；文件内可搜到 `EVB\0` | [enigma-virtual-box.md](enigma-virtual-box.md) |
