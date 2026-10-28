"""GalRev —— Galgame 引擎逆向通用库。

子包按引擎划分：
- advhd:    MoeNovel AdvHD（Amaneko 系）
- willplus: Willplus 旧引擎（WillAdv）
- krkr:     krkrz + M2「MDF」脚本（xp3 / Hxv4 加密归档 / PSB / .scn 文本模型）
- convert:  跨引擎转换（Willplus WSC → AdvHD WS2）

库内不内嵌任何一部游戏的标定值，项目专属参数一律由调用方注入。
"""
