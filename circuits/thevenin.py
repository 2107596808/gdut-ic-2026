#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电路②  验证戴维南定理（PySpice 仿真 + 手算对比）
=====================================================================
含源二端网络（给定题卡里的分压结构）：

        R1 = 4 kΩ
  +----[    ]----+------ a
  |              |
  |             [ ] R2 = 12 kΩ
 (V1=12V)        |
  |              |
  +--------------+------ b

手算（三步）：
    1) 开路电压 V_oc：a、b 开路时，R1 与 R2 串联分压
       V_oc = V1 · R2 / (R1 + R2) = 12 × 12 / (4 + 12) = 9 V
    2) 短路电流 I_sc：a、b 短接时 R2 被短路，只有 R1 接在电源上
       I_sc = V1 / R1 = 12 / 4000 = 3 mA
    3) 等效内阻 R_th：由 V_oc / I_sc 得到
       R_th = 9 V / 3 mA = 3 kΩ（也等于 R1 ∥ R2 = 4×12/(4+12) = 3 kΩ）

仿真验证：
    1) 空载仿真直接量 V_oc
    2) 短路仿真直接量 I_sc（用 0 V 电压源当短路线，量它的电流）
    3) 由 V_oc / I_sc 算出 R_th，与手算比
    4) 用「V_th 串联 R_th」搭等效电路，分别接 1k / 3k / 10k 负载，
       与原网络在同一负载下的电压、电流逐项对比

运行：
    pip install PySpice matplotlib
    python thevenin.py
=====================================================================
"""
import argparse
import os
import sys

# ----------------------------------------------------------------- 元件参数
V1 = 12.0       # 电源电压 V
R1 = 4e3        # 4 kΩ
R2 = 12e3       # 12 kΩ
LOAD_VALUES = [1e3, 3e3, 10e3]   # 三个测试负载

# ----------------------------------------------------------------- 手算值
V_OC_HAND = V1 * R2 / (R1 + R2)          # 9 V
I_SC_HAND = V1 / R1                      # 3 mA
R_TH_HAND = V_OC_HAND / I_SC_HAND        # 3 kΩ
R_TH_PARALLEL = R1 * R2 / (R1 + R2)      # 用并联公式再验算一次


def hand_calculations():
    print("=" * 70)
    print("戴维南定理验证：手算")
    print("=" * 70)
    print(f"  元件        V1 = {V1:.0f} V, R1 = {R1 / 1e3:.0f} kΩ, R2 = {R2 / 1e3:.0f} kΩ")
    print("  ① 开路电压 V_oc")
    print(f"     分压公式   V_oc = V1 · R2/(R1+R2) = {V1:.0f} × {R2 / 1e3:.0f}/({R1 / 1e3:.0f}+{R2 / 1e3:.0f}) = {V_OC_HAND:.3f} V")
    print("  ② 短路电流 I_sc")
    print(f"     短路时 R2 被旁路，I_sc = V1/R1 = {V1:.0f}/{R1:.0f} = {I_SC_HAND * 1e3:.3f} mA")
    print("  ③ 等效内阻 R_th")
    print(f"     由定义     R_th = V_oc/I_sc = {V_OC_HAND:.3f}/{I_SC_HAND * 1e3:.3f}m = {R_TH_HAND / 1e3:.3f} kΩ")
    print(f"     并联公式   R_th = R1∥R2 = {R1 / 1e3:.0f}×{R2 / 1e3:.0f}/({R1 / 1e3:.0f}+{R2 / 1e3:.0f}) = {R_TH_PARALLEL / 1e3:.3f} kΩ")
    print("  ④ 接负载 RL 后（戴维南等效电路）")
    for rl in LOAD_VALUES:
        vl = V_OC_HAND * rl / (R_TH_HAND + rl)
        il = vl / rl
        print(f"     RL = {rl / 1e3:>4.0f} kΩ → V = {vl:.4f} V, I = {il * 1e6:8.2f} µA")
    return V_OC_HAND, I_SC_HAND, R_TH_HAND


def _sim(circuit):
    return circuit.simulator(simulator="ngspice-subprocess", temperature=25)


def measure_oc():
    """空载：量开路电压"""
    from PySpice.Spice.Netlist import Circuit
    from PySpice.Unit import u_V, u_kOhm

    c = Circuit("Thevenin - open circuit")
    c.V("1", "n1", c.gnd, V1 @ u_V)
    c.R("1", "n1", "a", R1 @ u_kOhm)
    c.R("2", "a", c.gnd, R2 @ u_kOhm)
    op = _sim(c).operating_point()
    return float(op["a"])


def measure_sc():
    """短路：用 0 V 电压源把 a、b 短接，量流过它的电流"""
    from PySpice.Spice.Netlist import Circuit
    from PySpice.Unit import u_V, u_kOhm

    c = Circuit("Thevenin - short circuit")
    c.V("1", "n1", c.gnd, V1 @ u_V)
    c.R("1", "n1", "a", R1 @ u_kOhm)
    c.R("2", "a", c.gnd, R2 @ u_kOhm)
    c.V("sc", "a", c.gnd, 0 @ u_V)      # 0 V 电源 = 理想短路线
    op = _sim(c).operating_point()
    # 流过短路线的电流（SPICE 里电压源电流正方向为流入正端）
    return abs(float(op.branches["vsc"]))


def measure_original_with_load(rl):
    """原网络接负载 RL：返回 (端口电压, 负载电流)"""
    from PySpice.Spice.Netlist import Circuit
    from PySpice.Unit import u_V, u_kOhm

    c = Circuit(f"Thevenin - original with RL={rl:.0f}")
    c.V("1", "n1", c.gnd, V1 @ u_V)
    c.R("1", "n1", "a", R1 @ u_kOhm)
    c.R("2", "a", c.gnd, R2 @ u_kOhm)
    c.R("L", "a", c.gnd, rl @ u_kOhm)
    op = _sim(c).operating_point()
    v = float(op["a"])
    return v, v / rl


def measure_equivalent_with_load(vth, rth, rl):
    """戴维南等效电路接负载 RL：返回 (端口电压, 负载电流)"""
    from PySpice.Spice.Netlist import Circuit
    from PySpice.Unit import u_V, u_kOhm

    c = Circuit(f"Thevenin - equivalent with RL={rl:.0f}")
    c.V("th", "a", c.gnd, vth)
    c.R("th", "a", "b", rth @ u_kOhm)
    c.R("L", "b", c.gnd, rl @ u_kOhm)
    op = _sim(c).operating_point()
    v = float(op["b"])
    return v, v / rl


def plot_schematics(save_dir):
    """画「原含源二端网络（标注端口）」与「戴维南等效电路」两张图"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4), dpi=140)

    # ---- 左：原网络 ----
    ax1.set_axis_off()
    ax1.plot([0.15, 0.15], [0.3, 0.7], color="#333", lw=1.6)
    ax1.plot([0.15, 0.45], [0.7, 0.7], color="#333", lw=1.6)
    ax1.plot([0.15, 0.45], [0.3, 0.3], color="#333", lw=1.6)
    ax1.add_patch(plt.Rectangle((0.45, 0.665), 0.18, 0.07, fill=False, ec="#1f6feb", lw=1.8))
    ax1.text(0.54, 0.78, f"R1={R1 / 1e3:.0f}kΩ", ha="center", color="#1f6feb", fontsize=9)
    ax1.plot([0.63, 0.85], [0.7, 0.7], color="#333", lw=1.6)
    ax1.plot([0.85, 0.85], [0.7, 0.56], color="#333", lw=1.6)
    ax1.add_patch(plt.Rectangle((0.815, 0.42), 0.07, 0.14, fill=False, ec="#e8590c", lw=1.8))
    ax1.text(0.95, 0.48, f"R2={R2 / 1e3:.0f}kΩ", color="#e8590c", fontsize=9, va="center")
    ax1.plot([0.85, 0.85], [0.42, 0.3], color="#333", lw=1.6)
    ax1.plot([0.45, 0.85], [0.3, 0.3], color="#333", lw=1.6)
    ax1.plot([0.15], [0.5], marker="o", ms=5, color="#333")
    ax1.text(0.06, 0.5, f"{V1:.0f}V", fontsize=11, va="center")
    ax1.plot([0.85], [0.7], marker="o", ms=6, color="#2f9e44")
    ax1.plot([0.85], [0.3], marker="o", ms=6, color="#2f9e44")
    ax1.text(0.87, 0.72, "a", color="#2f9e44", fontsize=12)
    ax1.text(0.87, 0.24, "b", color="#2f9e44", fontsize=12)
    ax1.set_title("原含源二端网络（端口 a-b）", fontsize=10)

    # ---- 右：戴维南等效 ----
    ax2.set_axis_off()
    ax2.plot([0.2, 0.2], [0.3, 0.7], color="#333", lw=1.6)
    ax2.plot([0.2, 0.45], [0.7, 0.7], color="#333", lw=1.6)
    ax2.plot([0.2, 0.45], [0.3, 0.3], color="#333", lw=1.6)
    ax2.add_patch(plt.Rectangle((0.45, 0.665), 0.18, 0.07, fill=False, ec="#1f6feb", lw=1.8))
    ax2.text(0.54, 0.78, f"R_th={R_TH_HAND / 1e3:.0f}kΩ", ha="center", color="#1f6feb", fontsize=9)
    ax2.plot([0.63, 0.85], [0.7, 0.7], color="#333", lw=1.6)
    ax2.plot([0.85, 0.85], [0.7, 0.3], color="#333", lw=1.6)
    ax2.plot([0.45, 0.85], [0.3, 0.3], color="#333", lw=1.6)
    ax2.plot([0.2], [0.5], marker="o", ms=5, color="#333")
    ax2.text(0.04, 0.5, f"{V_OC_HAND:.0f}V", fontsize=11, va="center")
    ax2.plot([0.85], [0.7], marker="o", ms=6, color="#2f9e44")
    ax2.plot([0.85], [0.3], marker="o", ms=6, color="#2f9e44")
    ax2.text(0.87, 0.72, "a", color="#2f9e44", fontsize=12)
    ax2.text(0.87, 0.24, "b", color="#2f9e44", fontsize=12)
    ax2.set_title(f"戴维南等效电路（V_th={V_OC_HAND:.0f}V, R_th={R_TH_HAND / 1e3:.0f}kΩ）", fontsize=10)

    path = os.path.join(save_dir, "thevenin_schematic.png")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"  已保存电路图   {path}")


def main():
    parser = argparse.ArgumentParser(description="戴维南定理验证仿真")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(save_dir, exist_ok=True)
    if not args.no_plot:
        plot_schematics(save_dir)

def report_no_simulator(exc, hand_rows):
    """没装 ngspice 时：给出可执行的安装指引，并把已经算好的手算值打出来。"""
    print("\n[仿真没跑成] PySpice 只是个“遥控器”，真正解方程的是 ngspice，本机需要装它。")
    print("  安装：Ubuntu / Debian : sudo apt install ngspice")
    print("        macOS (Homebrew): brew install ngspice")
    print("        Windows         : https://ngspice.sourceforge.io/download.html")
    print("        （Windows 上也可以用 WSL 跑，命令行最省事）")
    print(f"  原始报错：{type(exc).__name__}: {exc}")
    print("\n下面是手算结果，装好 ngspice 后重跑本脚本，仿真列会自动补齐：")
    print("=" * 70)
    print(f"  {'量':<18}{'手算':>16}")
    for name, hv in hand_rows:
        print(f"  {name:<18}{hv:>16.4f}")
    print("=" * 70)
    return 1


def main():
    parser = argparse.ArgumentParser(description="戴维南定理验证仿真")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(save_dir, exist_ok=True)
    if not args.no_plot:
        plot_schematics(save_dir)

    v_oc_h, i_sc_h, r_th_h = hand_calculations()

    try:
        v_oc = measure_oc()
        i_sc = measure_sc()
    except Exception as exc:  # noqa: BLE001
        return report_no_simulator(exc, [
            ("V_oc (V)", v_oc_h),
            ("I_sc (mA)", i_sc_h * 1e3),
            ("R_th (kΩ)", r_th_h / 1e3),
        ])

    r_th = v_oc / i_sc

    print("\n" + "=" * 70)
    print("第 1 张表：V_oc / I_sc 两次仿真 vs 手算")
    print("=" * 70)
    print(f"  {'量':<16}{'手算':>16}{'仿真':>16}{'相对误差':>12}")
    for name, hv, sv, unit in [
        ("V_oc (V)", v_oc_h, v_oc, "V"),
        ("I_sc (mA)", i_sc_h * 1e3, i_sc * 1e3, "mA"),
        ("R_th (kΩ)", r_th_h / 1e3, r_th / 1e3, "kΩ"),
    ]:
        err = abs(sv - hv) / hv * 100 if hv else float("nan")
        print(f"  {name:<16}{hv:>16.4f}{sv:>16.4f}{err:>11.3f}%")

    print("\n" + "=" * 70)
    print("第 2 张表：等效电路替换后接负载的验证")
    print("=" * 70)
    print(f"  {'RL (kΩ)':>9}{'原网络 V':>12}{'等效 V':>12}{'原网络 I(µA)':>15}{'等效 I(µA)':>14}{'电压误差':>10}")
    ok = True
    for rl in LOAD_VALUES:
        try:
            v1, i1 = measure_original_with_load(rl)
            v2, i2 = measure_equivalent_with_load(v_oc, r_th, rl)
        except Exception as exc:  # noqa: BLE001
            print(f"  负载 {rl / 1e3:.0f}kΩ 仿真失败：{exc}")
            ok = False
            continue
        err = abs(v2 - v1) / v1 * 100 if v1 else float("nan")
        if err > 1:
            ok = False
        print(f"  {rl / 1e3:>9.0f}{v1:>12.4f}{v2:>12.4f}{i1 * 1e6:>15.2f}{i2 * 1e6:>14.2f}{err:>9.3f}%")

    print("\n结论：原网络与「V_th 串联 R_th」的等效电路在三个负载下的端口电压一致，")
    print("      最大误差在 1% 以内 ⇒ 戴维南定理得证。" if ok else "      存在超过 1% 的偏差，需要检查电路接法。")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
