"""WS2 字节补丁的共享原语：绝对偏移重写、跳转边界自检、调用边扫描、成就调用判定。

背景：`0x01 Condition`（ops[7:11]=a、ops[11:15]=b）、`0x02 Jump2`（ops[0:4]）、
`0x06 Jump`（ops[0:4]）的操作数是**文件内绝对偏移**。凡在指令流中做的字节增删
（拼接、改名、注入），这些目标都必须按累积位移重写，并回读校验每个目标落在
指令边界上（目标 0 = "不跳转"哨兵，跳过）。

指令对象来自 galrev.advhd.ws2disasm（Instruction：offset/opcode/size/operands/fields）。
本模块只含纯算法，不读任何项目文件；`callers_of` 需要的归档路径由调用方显式传入。
"""
import re
from collections import defaultdict

JUMP2, COND, JUMP = 0x02, 0x01, 0x06


def is_ach(ins):
    """是否为成就调用指令（0x04 + `CG_ACHIEVEMENT`）。"""
    return ins.opcode == 0x04 and (ins.operands or b'').startswith(b'CG_ACHIEVEMENT\x00')


def jump_targets(ins):
    """该指令引用的**文件内绝对偏移**（Condition/Jump2/Jump）。

    直接从 operands 字节读取（不依赖反汇编器的字段命名，0x06 的字段名在不同
    反汇编器里可能是 `target` 或 `a`）。"""
    ops = ins.operands or b''
    if ins.opcode == JUMP2 and len(ops) >= 4:
        return [int.from_bytes(ops[0:4], 'little')]
    if ins.opcode == COND and len(ops) >= 15:
        return [int.from_bytes(ops[7:11], 'little'),
                int.from_bytes(ops[11:15], 'little')]
    if ins.opcode == JUMP and len(ops) >= 4:
        return [int.from_bytes(ops[0:4], 'little')]
    return []


def rewrite_targets(ops, opcode, fn):
    """按 fn(old)->new 重写一条指令操作数里的绝对偏移；返回新 operands（bytes/bytes）。

    `0x02 Jump2` 改 ops[0:4]；`0x01 Condition` 改 ops[7:11] 与 ops[11:15]；
    `0x06 Jump` 改 ops[0:4]。其余 opcode 原样返回。old == 0 是"不跳转"哨兵，不改。
    """
    ops = bytearray(ops)
    if opcode == JUMP2:
        old = int.from_bytes(ops[0:4], 'little')
        if old:
            ops[0:4] = (fn(old) & 0xFFFFFFFF).to_bytes(4, 'little')
    elif opcode == COND:
        for off in (7, 11):
            old = int.from_bytes(ops[off:off + 4], 'little')
            if old:
                ops[off:off + 4] = (fn(old) & 0xFFFFFFFF).to_bytes(4, 'little')
    elif opcode == JUMP:
        old = int.from_bytes(ops[0:4], 'little')
        if old:
            ops[0:4] = (fn(old) & 0xFFFFFFFF).to_bytes(4, 'little')
    return bytes(ops)


def check_boundaries(ins_list, skip_offsets=()):
    """绝对偏移硬自检：每个目标都必须落在指令边界上。

    返回违规列表 [(opcode, offset, target)]；目标 0 与 offset ∈ skip_offsets 跳过
    （skip 用于被判为 inert 的疑似非指令）。
    """
    bounds = {i.offset for i in ins_list}
    bad = []
    for i in ins_list:
        if i.offset in skip_offsets:
            continue
        ops = i.operands
        if i.opcode == JUMP2:
            targets = [int.from_bytes(ops[0:4], 'little')]
        elif i.opcode == COND:
            targets = [int.from_bytes(ops[7:11], 'little'),
                       int.from_bytes(ops[11:15], 'little')]
        elif i.opcode == JUMP:
            targets = [int.from_bytes(ops[0:4], 'little')]
        else:
            continue
        for t in targets:
            if t and t not in bounds:
                bad.append((i.opcode, i.offset, t))
    return bad


_EDGE = re.compile(rb'[\x04\x07]([A-Z0-9_]{4,40})\x00')


def call_graph(decoded_members, skip=()):
    """全脚本 `0x04 RunFile`/`0x07 NextFile` 调用边的反向索引。

    decoded_members: {成员名大写: galrev.advhd.ws2.decode 后的 bytes}；skip 里的成员不作为调用者。
    返回 {目标 stem + '.WS2': set(调用者成员名大写)}。
    """
    rev = defaultdict(set)
    for name, dec in decoded_members.items():
        if not name.endswith('.WS2') or name in skip:
            continue
        for m in _EDGE.finditer(dec):
            rev[m.group(1).decode('ascii') + '.WS2'].add(name)
    return rev


def callers_of(stem_e, archive_path):
    """哪些脚本的 `0x04/0x07` 指向 <stem_e>.WS2。

    archive_path: AdvHD 格式 Arc 归档路径（galrev.advhd.arc.read_raw 读取），
    通常是与脚本同池的 Rio.arc；结果按成员名排序返回。
    """
    from galrev.advhd import arc, ws2
    members = {n.decode('utf-16le').upper(): ws2.decode(d)
               for n, d in arc.read_raw(archive_path)}
    return sorted(call_graph(members).get(stem_e.upper() + '.WS2', []))
