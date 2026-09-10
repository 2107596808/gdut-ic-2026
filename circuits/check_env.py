#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境自检：跑仿真之前先确认依赖是否齐全
=====================================================================
检查三件事：
  1) 三个电路的 .py 文件能不能正常导入（语法/依赖是否 OK）
  2) PySpice 能不能导入
  3) ngspice 共享库在不在（PySpice 只是个“遥控器”，真正解方程的是 ngspice）

用法：
    python circuits/check_env.py
=====================================================================
"""
import importlib.util
import os
import sys

# ---------------------------------------------------------------- 控制台编码
# ⚠️ 中文 Windows 控制台默认是 GBK，而本脚本要打印 ✓ / ✗ / 表格边框等字符，
#   GBK 里没有这些码位，Python 会直接抛 UnicodeEncodeError 让脚本崩溃。
#   在任何 print 之前把 stdout/stderr 切成 UTF-8，并允许无法编码的字符被替换，
#   保证「打印日志」这个动作本身永远不会让脚本失败。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 流被重定向到不支持 reconfigure 的对象时忽略

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["rc_lowpass.py", "thevenin.py", "nmos_cs_amp.py"]


def check_files():
    print("[1/3] 检查电路脚本语法")
    ok = True
    for name in FILES:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            print(f"  ✗ 找不到 {name}")
            ok = False
            continue
        try:
            with open(path, encoding="utf-8") as f:
                source = f.read()
            compile(source, path, "exec")
            print(f"  ✓ {name} 语法正确（{len(source.splitlines())} 行）")
        except SyntaxError as exc:
            print(f"  ✗ {name} 语法错误：第 {exc.lineno} 行 {exc.msg}")
            ok = False
    return ok


def check_pyspice():
    print("\n[2/3] 检查 PySpice")
    if importlib.util.find_spec("PySpice") is None:
        print("  ✗ 未安装 PySpice，请执行：pip install PySpice")
        return False
    import PySpice
    print(f"  ✓ PySpice {getattr(PySpice, '__version__', '未知版本')}")
    return True


def check_ngspice():
    """检查 ngspice 是否真的能用来跑仿真。

    ⚠️ 不要用 `NgSpiceShared.new_instance().lib` 来判断：PySpice 1.5 里这个属性
    在部分版本/平台上根本不存在（会抛 AttributeError），于是「明明装好了 ngspice
    也跑得通仿真」却被报成没装 —— 假阴性。这里改成真正跑一次最小仿真来验证，
    结论最可靠。
    """
    print("\n[3/3] 检查 ngspice 能否真正跑仿真")
    try:
        import _ngspice_compat  # noqa: F401  兼容层，import 即生效
    except Exception:
        pass
    try:
        from PySpice.Spice.Netlist import Circuit
        from PySpice.Unit import u_V, u_Ohm
        c = Circuit("env check")
        c.V("1", "n1", c.gnd, 1 @ u_V)
        c.R("1", "n1", c.gnd, 1 @ u_Ohm)
        op = c.simulator(simulator="ngspice-subprocess", temperature=25).operating_point()
        import numpy as _np
        v = float(_np.asarray(op["n1"], dtype=float).ravel()[0])
        ok = abs(v - 1.0) < 1e-6
        if ok:
            print("  ✓ ngspice 可用（跑通了 1V 分压的最小仿真，读数正确）")
            return True
        print(f"  ✗ ngspice 能跑但读数不对：n1 = {v}（应为 1.0）")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 没找到可用的 ngspice：{type(exc).__name__}: {exc}")
        print("    安装方式：")
        print("      Ubuntu / Debian : sudo apt install ngspice")
        print("      macOS (Homebrew): brew install ngspice")
        print("      Windows         : https://ngspice.sourceforge.io/download.html")
        print("    提示：Windows 上也可以用 WSL 跑这三个脚本，命令行最省事。")
        return False


def main():
    print("=" * 60)
    print("电路仿真环境自检")
    print("=" * 60)
    a = check_files()
    b = check_pyspice()
    c = check_ngspice()
    print("\n" + "=" * 60)
    if a and b and c:
        print("全部就绪，可以运行：python rc_lowpass.py / thevenin.py / nmos_cs_amp.py")
        return 0
    print("部分检查未通过，请按上面的提示补齐依赖。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
