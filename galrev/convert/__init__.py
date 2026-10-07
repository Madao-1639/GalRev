"""galrev.convert —— 跨引擎转换（Willplus WSC → AdvHD WS2）。

模块清单：
- wsc2ws2: 忠实指令集转换器（每条 WSC 指令映射为等价 WS2 序列，或明确跳过并计数；
  支持切片模式把源场景一段就地插入宿主脚本）

单部游戏语料的标定值（BGM id 基数、立绘族正则、站位分档等）一律不内嵌，
经 `wsc2ws2.ConvertOptions` 由调用方注入。转换规则与两代引擎语义差异见
docs/cross-engine/wsc-to-ws2.md。
"""
