#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PySpice 1.5 × ngspice 45 兼容层
=====================================================================
装好 PySpice 与 ngspice 之后仍然跑不出仿真，一共三个坑，都由本模块在运行时修掉。
**不改 site-packages**（改了换台机器就失效、也无法随仓库复现）。

用法：在 import PySpice 之前 `import _ngspice_compat`。三个电路脚本已经引用了它。

---------------------------------------------------------------------
坑① raw 头多了字段 → NameError: Expected label Circuit instead of Note
---------------------------------------------------------------------
ngspice 43 起在 raw 头里新增了 `Command:` 行，而 PySpice 是按固定字段顺序逐行读的
（Circuit → Temperature → Title → Date → Plotname → Flags → ...），读到多出来的那行就崩。
修法：把「标签必须正好等于预期」放宽成「往下扫到预期标签，中间的未知字段跳过」。

---------------------------------------------------------------------
坑② NumPy 2 移除了 np.fromstring 的二进制模式
---------------------------------------------------------------------
PySpice 用 `np.fromstring(raw_data, dtype='f8')` 解二进制块，在 NumPy 2 下会抛
    ValueError: The binary mode of fromstring is removed, use frombuffer instead
修法：换成 np.frombuffer，并**原样保留 count 语义**（注意：不能因为 buffer 尾部
      有多余字节就忽略 count，那会静默多读数据）。

---------------------------------------------------------------------
坑③（最要命）ngspice 的 server 模式输出坏数据
---------------------------------------------------------------------
PySpice 的 ngspice-subprocess 走的是 `ngspice -s`（server 模式），**而这个模式在
ngspice 45 下吐出的二进制是损坏的**。实测同一个 RC 瞬态电路：

    模式              点数        time 列        v(vin) 列
    ngspice -r       3000042     max=0.003 ✅   max=2.000 ✅     ← 写 raw 文件，正确
    ngspice -s       3000070     max=6e130 ❌   max=5.5e177 ❌   ← PySpice 用的，坏

坏数据极有迷惑性：v(vout) 那一列看着「还挺合理」（因为它是第 3 列，错位后恰好落在
一段有效的数值上），只有 time / vin 是天文数字。很容易误判成「我的读取代码写错了」。

修法：干脆不用 server 模式 —— 换成一个用 `ngspice -r` 写临时 raw 文件、再把文件读回来
      的替代 server。`-r` 的输出是干净的，也就绕开了这个坏模式。
=====================================================================
"""

import os
import subprocess
import tempfile

_PATCHED = False


def _patch_header_parser():
    """坑①：raw 头解析容错（跳过未知字段）。"""
    from PySpice.Spice import RawFile

    def _read_header_field_line(self, header_line_iterator, expected_label, has_value=True):
        """读到 expected_label 那一行为止，中间夹着的其它字段一律跳过。

        ⚠️ 容忍窗口要给够：`ngspice -r` 写出的头里**没有 Circuit 行**，
        而从 Circuit 往后要跳过 Title / Date / Command / Plotname / Flags 等，
        窗口太小就会在读到 `No. Points` 时误报「Expected label Circuit」。
        这里给到 32 行，同时把「耗尽」的情形也报清楚，方便以后排查。
        """
        last_label = '<空>'
        for _ in range(32):
            line = self._read_line(header_line_iterator)
            self._logger.debug(line)
            if has_value:
                location = line.find(': ')
                if location < 0:
                    continue
                label, value = line[:location], line[location + 2:]
            else:
                label, value = line[:-1], None
            if label == expected_label:
                return value.strip() if has_value else None
            last_label = label
        raise NameError("Expected label %s instead of %s" % (expected_label, last_label))

    RawFile.RawFileAbc._read_header_field_line = _read_header_field_line


def _patch_fromstring():
    """坑②：把 np.fromstring 的二进制模式接到 np.frombuffer。"""
    import numpy as _np
    if getattr(_np, "_pyspice_fromstring_shim", False):
        return
    _orig = _np.fromstring

    def _fromstring_compat(s, dtype=float, count=-1, sep=''):
        if isinstance(s, (bytes, bytearray, memoryview)) and sep == '':
            return _np.frombuffer(s, dtype=dtype, count=count, offset=0)
        return _orig(s, dtype=dtype, count=count, sep=sep)

    _np.fromstring = _fromstring_compat
    _np._pyspice_fromstring_shim = True


def _build_rawfile_from_bytes(raw, simulation=None):
    """自己从 `ngspice -r` 的字节流构造一个 PySpice RawFile 对象。

    为什么不用 RawFile.__init__：它按固定字段序列逐行解析头部（Circuit → 温度行 →
    Title → ...），而 `-r` 输出的头跟这个序列对不上，补起来牵一发动全身。
    这里干脆直接按 raw 格式解析出它需要的几个属性，然后创建对象、手工塞进去 ——
    对象的 to_analysis() / nodes() 等方法照常可用，因为它们只读属性。
    """
    from PySpice.Spice.NgSpice.RawFile import RawFile, Variable

    marker = b'Binary:' + os.linesep.encode('ascii')
    loc = raw.find(marker)
    if loc < 0:
        raise NameError('raw 数据里找不到 Binary: 段')
    head = raw[:loc].decode('utf-8', errors='replace')
    start = loc + len(marker)
    while raw[start:start + 1] in (b'\n', b'\r'):
        start += 1
    blob = raw[start:]

    meta = {}
    var_specs = []
    in_vars = False
    for line in head.splitlines():
        if line.startswith('Variables:'):
            in_vars = True
            continue
        if in_vars:
            parts = [p for p in line.replace('\t', ' ').split(' ') if p]
            if len(parts) >= 3 and parts[0].isdigit():
                var_specs.append((int(parts[0]), parts[1], parts[2]))
            continue
        if ': ' in line:
            k, v = line.split(': ', 1)
            meta[k] = v.strip()
        elif line.endswith(':'):
            meta[line[:-1]] = ''

    flags = meta.get('Flags', 'real')
    nvars = len(var_specs)
    ncols = nvars * (2 if flags == 'complex' else 1)
    # ⚠️ 点数用「实际字节数」反推，不信头部/ stderr 里的数字（ngspice 45 的 server
    #    模式两者都会偏小，导致整块数据错位）
    npoints = len(blob) // (ncols * 8)

    obj = RawFile.__new__(RawFile)
    obj.number_of_points = npoints
    obj.flags = flags
    obj.plot_name = meta.get('Plotname', '')
    obj.title = meta.get('Title', '')
    obj.date = meta.get('Date', '')
    obj.circuit_name = 'ngspice'
    obj.temperature = 25.0
    obj.nominal_temperature = 25.0
    obj.warnings = []
    obj.number_of_variables = nvars
    obj._simulation = simulation

    import numpy as np
    data = np.frombuffer(blob[:npoints * ncols * 8], dtype='f8').reshape(npoints, ncols)
    data = data.transpose()
    if flags == 'complex':
        tmp = data
        data = np.array(tmp[0::2], dtype='complex128')
        data.imag = tmp[1::2]

    obj.variables = {}
    for index, name, unit_name in var_specs:
        var = Variable(index, name, obj._name_to_unit.get(unit_name, ''))

        class _D:  # 占位，下面赋值
            pass
        var.data = data[index]
        obj.variables[name] = var
    return obj


def _normalize_raw_header(raw):
    """把 `ngspice -r` 的 raw 头补全成 PySpice 解析器认识的字段序列。

    PySpice 期望的顺序（见 PySpice/Spice/NgSpice/RawFile.py::_read_header）：
        Circuit: → Doing analysis at TEMP... → [Warning...] → Title: → Date:
        → Plotname: → Flags: → No. Variables: → No. Points: → Variables:
        → No. of Data Columns → <变量表>

    `ngspice -r` 给的是：
        Title: → Date: → Command: → Plotname: → Flags: → No. Variables:
        → No. Points: → Variables: → <变量表> → Binary:

    缺 Circuit / 温度行 / No. of Data Columns。这里补齐（缺什么补什么，
    已有的字段保持原样），数据区一个字节都不动。
    """
    binary_marker = b'Binary:' + os.linesep.encode('ascii')
    loc = raw.find(binary_marker)
    if loc < 0:
        return raw
    head, rest = raw[:loc], raw[loc:]
    text = head.decode('utf-8', errors='replace')
    lines = text.splitlines()

    def has(prefix):
        return any(l.startswith(prefix) for l in lines)

    # No. Variables 的值（用来推 No. of Data Columns）
    nvars = 0
    for l in lines:
        if l.startswith('No. Variables'):
            try:
                nvars = int(l.split(':')[1].strip())
            except ValueError:
                nvars = 0
    flags = 'real'
    for l in lines:
        if l.startswith('Flags'):
            flags = l.split(':')[1].strip()

    out = []
    for l in lines:
        # Command: 是 ngspice 43+ 新增的，PySpice 不认识；而且我们上面已经放宽了
        # 跳过逻辑，留着也无妨，但删掉更干净
        if l.startswith('Command:'):
            continue
        out.append(l)
        if l.startswith('Flags:'):
            # Flags 之后紧跟 No. Variables / No. Points / Variables / 变量表，
            # 而 No. of Data Columns 要插在 Variables 之前 —— 见下面的处理
            pass
        if l.startswith('No. Points'):
            if not has('No. of Data Columns'):
                out.append('No. of Data Columns: %d' % (nvars * (2 if flags == 'complex' else 1)))

    if not has('Circuit:'):
        out.insert(0, 'Circuit: ngspice')
    if not has('Doing analysis at TEMP'):
        # 温度行插在 Circuit 之后、Title 之前
        idx = 1 if out and out[0].startswith('Circuit:') else 0
        out.insert(idx, 'Doing analysis at TEMP = 25.000000 deg C, Nominal = 25.000000 deg C')

    return ('\n'.join(out) + '\n').encode('utf-8') + rest


def _patch_spice_server():
    """坑③：用 `ngspice -r` 写文件再读，替换掉会产出坏数据的 server 模式。

    ⚠️ 要补的是 **SpiceServer.__call__ 本身**，不能在
    `NgSpiceSubprocessCircuitSimulator` 上挂类属性 —— 它的 __init__ 里写着
        self._spice_server = SpiceServer(**server_kwargs)
    每个实例都会重新建一个，把类属性整个盖掉（我第一次就是这么改的，白忙一场：
    跑出来的数据一模一样，因为压根没走到我的实现）。
    """
    from PySpice.Spice.NgSpice.Server import SpiceServer
    from PySpice.Spice.NgSpice.RawFile import RawFile as _RawFile

    def _call_via_raw_file(self, spice_input):
        fd, path = tempfile.mkstemp(suffix='.raw', prefix='pyspice_')
        os.close(fd)
        try:
            proc = subprocess.run(
                (self._spice_command, '-b', '-r', path),
                input=str(spice_input).encode('utf-8'),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stderr = proc.stderr.decode('utf-8', errors='replace')
            if 'run simulation(s) aborted' in stderr or not os.path.getsize(path):
                raise NameError('Simulation aborted' + os.linesep + stderr)
            with open(path, 'rb') as f:
                stdout = f.read()

            return _build_rawfile_from_bytes(stdout)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    SpiceServer.__call__ = _call_via_raw_file


def apply():
    global _PATCHED
    if _PATCHED:
        return True
    try:
        _patch_header_parser()
        _patch_fromstring()
        _patch_spice_server()
    except Exception:
        return False
    _PATCHED = True
    return True


apply()
