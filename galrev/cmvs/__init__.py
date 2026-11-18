"""galrev.cmvs —— Purple SOFTWARE CMVS 引擎通用库。

模块清单（全部纯标准库，无项目耦合，不内嵌任何一部游戏的标定值）：

- ps3: PS2A 脚本容器编解码（头部字段、字节变换、2048 环形窗口 LZSS、文本段读写）。
       密钥与各段长度全部从文件头读取，工具本身不含任何游戏的 key。
- pb3: PB3B type 1 图像容器解码与「全字面」编码（分块优先像素序、头部自加密）。
       type 2/3/4/5/6 见 docs/engines/cmvs/file-formats.md，本库只实现 type 1。

分部编码（compressed_size != 0 的 LZSS 压缩）与 CPZ 封包读取尚未实现，见文档相应章节。
"""
