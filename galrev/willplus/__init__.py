"""galrev.willplus —— Willplus 旧引擎（WillAdv）库。

模块清单：
- arc:      老式归档读取（类型表 + 21 字节定长条目，ASCII/Shift-JIS 名）
- decrypt:  WSC 字节混淆还原（每字节 ror 2）
- wsc:      WSC 线性反汇编器（输入须为已解密形态）

本包不内嵌任何一部游戏的标定值；项目专属参数由调用方注入。
"""
