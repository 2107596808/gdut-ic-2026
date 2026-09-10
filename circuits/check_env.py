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
    print("\n[3/3] 检查 ngspice 共享库")
    try:
        from PySpice.Spice.NgSpice.Shared import NgSpiceShared
        shared = NgSpiceShared.new_instance()
        print(f"  ✓ 已找到 ngspice：{shared.lib}")
        return True
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
