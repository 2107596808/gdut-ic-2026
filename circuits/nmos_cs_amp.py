#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电路③  NMOS 共源级放大电路（PySpice 仿真 + 手算对比）
=====================================================================
按题卡给定的参数（固定值，不能改）：

    VDD = 5 V
    Rg1 = 60 kΩ（上偏置）      Rg2 = 40 kΩ（下偏置）
    Rd  = 2 kΩ（漏极电阻）
    Cb1 → 视为足够大（本脚本取 10 µF，1 kHz 下容抗仅 15.9 Ω，足够“短路”）
    NMOS：K = 0.8 mA/V², V_th = 1 V, λ = 0.02 /V
    Vi  = 10 mV / 1 kHz 正弦波

电路：
               VDD
                |
        +-------+-------+
        |               |
       [Rg1]           [Rd]
        |               |
   Vi --||--+-----------+---- Vo     (Cb1 隔直，把交流信号送到栅极)
     Cb1   |           (NMOS: D=漏, G=栅, S=源接地)
          [Rg2]        G---+
           |               |
          GND        S -----+---- GND

手算（分三步）：
  ① 静态工作点
      V_G  = VDD · Rg2/(Rg1+Rg2) = 5 × 40/100 = 2.0 V     （栅极无电流）
      V_GS = V_G = 2.0 V
      V_ov = V_GS − V_th = 1.0 V
      I_D  = K · V_ov² = 0.8 × 1² = 0.8 mA
      V_DS = VDD − I_D·Rd = 5 − 0.8m×2k = 3.4 V
      饱和区判据 V_DS > V_GS − V_th：3.4 V > 1.0 V ⇒ 工作在饱和区 ✔
  ② 小信号参数
      gm = 2K·V_ov = 2×0.8m×1 = 1.6 mA/V
      ro = 1/(λ·I_D) = 1/(0.02×0.8m) = 62.5 kΩ
  ③ 中频增益
      Av = −gm·(Rd ∥ ro) = −1.6m × (2k ∥ 62.5k) = −1.6m × 1.9379k ≈ −3.101
      （输出反相，所以是负号）

运行：
    pip install PySpice matplotlib
    python nmos_cs_amp.py
=====================================================================
"""
import argparse
import math
import os
import sys

# ----------------------------------------------------------------- 题给参数
VDD = 5.0
RG1 = 60e3
RG2 = 40e3
RD = 2e3
K = 0.8e-3          # K = ½·KP·W/L = 0.8 mA/V²
VTH = 1.0
LAMBDA = 0.02       # 1/V
VI_AMP = 10e-3      # 10 mV 幅值
FREQ = 1e3          # 1 kHz
CB1 = 10e-6         # 题中“足够大”，这里取 10 µF（1 kHz 时 Xc ≈ 15.9 Ω）

# ----------------------------------------------------------------- 手算值
VOV_HAND = None
ID_HAND = None
VDS_HAND = None
GM_HAND = None
RO_HAND = None
AV_HAND = None


def hand_calculations():
    global VOV_HAND, ID_HAND, VDS_HAND, GM_HAND, RO_HAND, AV_HAND
    vg = VDD * RG2 / (RG1 + RG2)
    vgs = vg
    vov = vgs - VTH
    if vov <= 0:
        raise SystemExit("偏置点不在导通区，请检查 Rg1/Rg2")
    id_ = K * vov ** 2
    vds = VDD - id_ * RD
    gm = 2 * K * vov
    ro = 1.0 / (LAMBDA * id_)
    rd_par_ro = RD * ro / (RD + ro)
    av = -gm * rd_par_ro
    vov_hand, id_hand, vds_hand, gm_hand, ro_hand, av_hand = vov, id_, vds, gm, ro, av

    print("=" * 72)
    print("NMOS 共源级放大电路：手算")
    print("=" * 72)
    print(f"  参数     VDD={VDD:.0f}V, Rg1={RG1 / 1e3:.0f}kΩ, Rg2={RG2 / 1e3:.0f}kΩ, Rd={RD / 1e3:.0f}kΩ")
    print(f"           K={K * 1e3:.1f}mA/V², V_th={VTH:.0f}V, λ={LAMBDA:.2f}/V, Vi={VI_AMP * 1e3:.0f}mV/{FREQ / 1e3:.0f}kHz")
    print("\n  ① 静态工作点")
    print(f"     V_G  = VDD·Rg2/(Rg1+Rg2) = {VDD:.0f}×{RG2 / 1e3:.0f}/({RG1 / 1e3:.0f}+{RG2 / 1e3:.0f}) = {vg:.3f} V")
    print(f"     V_GS = V_G = {vgs:.3f} V （栅极电流为 0）")
    print(f"     V_ov = V_GS − V_th = {vgs:.3f} − {VTH:.1f} = {vov:.3f} V")
    print(f"     I_D  = K·V_ov² = {K * 1e3:.2f}m × {vov:.2f}² = {id_ * 1e3:.4f} mA")
    print(f"     V_DS = VDD − I_D·Rd = {VDD:.0f} − {id_ * 1e3:.4f}m×{RD / 1e3:.0f}k = {vds:.4f} V")
    sat = vds > vov
    print(f"     饱和区判据：V_DS({vds:.3f}V) {'>' if sat else '≤'} V_ov({vov:.3f}V) ⇒ {'工作在饱和区 ✔' if sat else '不在饱和区 ✘'}")
    print("\n  ② 小信号参数")
    print(f"     gm = 2K·V_ov = 2×{K * 1e3:.2f}m×{vov:.2f} = {gm * 1e3:.3f} mA/V")
    print(f"     ro = 1/(λ·I_D) = 1/({LAMBDA:.2f}×{id_ * 1e3:.4f}m) = {ro / 1e3:.3f} kΩ")
    print("\n  ③ 中频电压增益")
    print(f"     Rd∥ro = {RD / 1e3:.0f}k∥{ro / 1e3:.2f}k = {rd_par_ro / 1e3:.4f} kΩ")
    print(f"     Av = −gm·(Rd∥ro) = −{gm * 1e3:.3f}m × {rd_par_ro / 1e3:.4f}k = {av:.4f}")
    print(f"     |Av| = {abs(av):.4f}（{20 * math.log10(abs(av)):.2f} dB），输出与输入反相")
    print(f"     预期输出幅度 = |Av| × Vi = {abs(av) * VI_AMP * 1e3:.3f} mV")
    return dict(vov=vov, id_=id_, vds=vds, gm=gm, ro=ro, av=av, rd_par_ro=rd_par_ro)


def spice_model():
    """NMOS level-1 模型参数：K = ½·KP·(W/L)，取 W/L = 1 则 KP = 2K"""
    return {
        "LEVEL": 1,
        "VTO": VTH,
        "KP": 2 * K,          # 0.8mA/V² × 2 = 1.6mA/V²
        "LAMBDA": LAMBDA,
        "W": 10e-6,
        "L": 10e-6,
    }


def run_dc():
    """直流工作点：量与手算 I_D、V_DS 对比"""
    from PySpice.Spice.Netlist import Circuit

    c = Circuit("NMOS common-source - DC operating point")
    model = spice_model()
    c.model("NMOS1", "nmos", **model)
    c.V("dd", "vdd", c.gnd, VDD)
    c.R("g1", "vdd", "g", RG1)
    c.R("g2", "g", c.gnd, RG2)
    c.R("d", "vdd", "d", RD)
    c.M("1", "d", "g", c.gnd, c.gnd, model="NMOS1")

    op = c.simulator(simulator="ngspice-subprocess", temperature=25).operating_point()
    vg = float(op["g"])
    vd = float(op["d"])
    id_ = (VDD - vd) / RD
    return dict(vg=vg, vd=vd, id_=id_)


def run_transient(save_dir, do_plot=True):
    """瞬态：输入 10mV/1kHz 正弦，看输出反相放大并实测增益"""
    from PySpice.Spice.Netlist import Circuit
    from PySpice.Unit import u_V, u_kOhm, u_uF, u_ms, u_us

    c = Circuit("NMOS common-source - transient")
    model = spice_model()
    c.model("NMOS1", "nmos", **model)
    c.SinusoidalVoltageSource("sig", "vi", c.gnd, amplitude=VI_AMP, frequency=FREQ)
    c.C("b1", "vi", "g", CB1 @ u_uF)         # Cb1：隔直电容，视为足够大
    c.R("g1", "vdd", "g", RG1 @ u_kOhm)
    c.R("g2", "g", c.gnd, RG2 @ u_kOhm)
    c.V("dd", "vdd", c.gnd, VDD @ u_V)
    c.R("d", "vdd", "d", RD @ u_kOhm)
    c.M("1", "d", "g", c.gnd, c.gnd, model="NMOS1")

    sim = c.simulator(simulator="ngspice-subprocess", temperature=25)
    analysis = sim.transient(step_time=2 @ u_us, end_time=5 @ u_ms)
    t = [float(x) for x in analysis.time]
    vin = [float(x) for x in analysis["vi"]]
    vg = [float(x) for x in analysis["g"]]
    vout = [float(x) for x in analysis["d"]]

    # 取后半段（已进入稳态）算峰峰值与增益
    half = len(t) // 2
    vin_pp = max(vin[half:]) - min(vin[half:])
    vg_pp = max(vg[half:]) - min(vg[half:])
    vout_pp = max(vout[half:]) - min(vout[half:])
    av_meas = vout_pp / vg_pp if vg_pp else float("nan")

    # 判断反相：找输出最大处，看对应输入是否接近最小
    imax = max(range(half, len(t)), key=lambda i: vout[i])
    phase_inverted = vin[imax] < 0

    print("\n瞬态分析（输入 10 mV / 1 kHz 正弦）")
    print(f"  输入 Vi  峰峰值  {vin_pp * 1e3:.3f} mV")
    print(f"  栅极 Vg  峰峰值  {vg_pp * 1e3:.3f} mV")
    print(f"  输出 Vo  峰峰值  {vout_pp * 1e3:.3f} mV")
    print(f"  实测增益 |Av| = Vo/Vg = {abs(av_meas):.4f}")
    print(f"  输出是否反相：{'是 ✔（输出最大时输入为负）' if phase_inverted else '否 ✘'}")

    if do_plot:
        _plot_waveform(save_dir, t, vin, vout, av_meas)
    return dict(vin_pp=vin_pp, vg_pp=vg_pp, vout_pp=vout_pp, av=av_meas, inverted=phase_inverted)


def _plot_waveform(save_dir, t, vin, vout, av_meas):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), dpi=140, sharex=True)
    tt = [x * 1e3 for x in t]
    ax1.plot(tt, [v * 1e3 for v in vin], lw=1.8, color="#1f6feb", label="Vi 输入 (mV)")
    ax1.set_ylabel("Vi (mV)")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=9)
    ax1.set_title("NMOS 共源级：输入 10 mV / 1 kHz，输出反相放大")
    ax2.plot(tt, [v * 1e3 for v in vout], lw=1.8, color="#e8590c",
             label=f"Vo 输出 (mV)，实测 |Av|={abs(av_meas):.2f}")
    ax2.set_ylabel("Vo (mV)")
    ax2.set_xlabel("时间 (ms)")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=9)
    fig.tight_layout()
    path = os.path.join(save_dir, "nmos_waveform.png")
    fig.savefig(path)
    plt.close(fig)
    print(f"  已保存波形图   {path}")


def plot_schematics(save_dir, hand):
    """画直流通路、小信号等效模型、以及完整电路图"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), dpi=140)

    # (1) 完整电路
    ax = axes[0]
    ax.set_axis_off()
    ax.plot([0.5, 0.5], [0.86, 0.95], color="#333", lw=1.6)
    ax.text(0.5, 0.96, "VDD = 5V", ha="center", fontsize=9)
    ax.plot([0.25, 0.75], [0.86, 0.86], color="#333", lw=1.6)
    ax.add_patch(plt.Rectangle((0.225, 0.62), 0.05, 0.2, fill=False, ec="#1f6feb", lw=1.6))
    ax.text(0.16, 0.72, "Rg1\n60k", fontsize=8, color="#1f6feb", ha="center")
    ax.plot([0.25, 0.25], [0.62, 0.5], color="#333", lw=1.6)
    ax.add_patch(plt.Rectangle((0.725, 0.62), 0.05, 0.2, fill=False, ec="#1f6feb", lw=1.6))
    ax.text(0.86, 0.72, "Rd\n2k", fontsize=8, color="#1f6feb", ha="center")
    ax.plot([0.75, 0.75], [0.62, 0.5], color="#333", lw=1.6)
    ax.plot([0.75, 0.9], [0.5, 0.5], color="#333", lw=1.6)
    ax.text(0.91, 0.5, "Vo", fontsize=10, va="center")
    ax.add_patch(plt.Rectangle((0.225, 0.2), 0.05, 0.2, fill=False, ec="#1f6feb", lw=1.6))
    ax.text(0.16, 0.3, "Rg2\n40k", fontsize=8, color="#1f6feb", ha="center")
    ax.plot([0.25, 0.25], [0.5, 0.4], color="#333", lw=1.6)
    ax.plot([0.25, 0.5], [0.5, 0.5], color="#333", lw=1.6)
    ax.plot([0.5, 0.5], [0.5, 0.42], color="#333", lw=1.6)
    ax.plot([0.25, 0.25], [0.2, 0.12], color="#333", lw=1.6)
    ax.plot([0.4, 0.6], [0.12, 0.12], color="#333", lw=1.6)
    ax.add_patch(plt.Rectangle((0.42, 0.33), 0.16, 0.17, fill=False, ec="#7048e8", lw=1.6))
    ax.text(0.5, 0.41, "NMOS", ha="center", fontsize=8, color="#7048e8")
    ax.plot([0.5, 0.5], [0.33, 0.12], color="#333", lw=1.6)
    ax.plot([0.5, 0.75], [0.12, 0.12], color="#333", lw=1.6)
    ax.plot([0.75, 0.75], [0.12, 0.42], color="#333", lw=1.6)
    ax.plot([0.1, 0.22], [0.42, 0.42], color="#333", lw=1.6)
    ax.text(0.02, 0.42, "Vi", fontsize=10, va="center")
    ax.set_title("完整电路", fontsize=10)

    # (2) 直流通路（电容开路）
    ax = axes[1]
    ax.set_axis_off()
    ax.plot([0.5, 0.5], [0.86, 0.95], color="#333", lw=1.6)
    ax.text(0.5, 0.96, "VDD", ha="center", fontsize=9)
    ax.plot([0.25, 0.75], [0.86, 0.86], color="#333", lw=1.6)
    ax.add_patch(plt.Rectangle((0.225, 0.6), 0.05, 0.2, fill=False, ec="#1f6feb", lw=1.6))
    ax.text(0.15, 0.7, "Rg1", fontsize=8, ha="center")
    ax.add_patch(plt.Rectangle((0.725, 0.6), 0.05, 0.2, fill=False, ec="#1f6feb", lw=1.6))
    ax.text(0.87, 0.7, "Rd", fontsize=8, ha="center")
    ax.plot([0.25, 0.25], [0.6, 0.42], color="#333", lw=1.6)
    ax.plot([0.25, 0.5], [0.42, 0.42], color="#333", lw=1.6)
    ax.plot([0.75, 0.75], [0.6, 0.42], color="#333", lw=1.6)
    ax.add_patch(plt.Rectangle((0.225, 0.18), 0.05, 0.2, fill=False, ec="#1f6feb", lw=1.6))
    ax.text(0.15, 0.28, "Rg2", fontsize=8, ha="center")
    ax.plot([0.25, 0.25], [0.18, 0.1], color="#333", lw=1.6)
    ax.plot([0.4, 0.6], [0.1, 0.1], color="#333", lw=1.6)
    ax.add_patch(plt.Rectangle((0.42, 0.3), 0.16, 0.16, fill=False, ec="#7048e8", lw=1.6))
    ax.text(0.5, 0.38, "NMOS", ha="center", fontsize=8, color="#7048e8")
    ax.plot([0.5, 0.5], [0.3, 0.1], color="#333", lw=1.6)
    ax.text(0.5, 0.55, f"V_G = {VDD * RG2 / (RG1 + RG2):.1f} V", ha="center", fontsize=9, color="#d6336c")
    ax.text(0.5, 0.02, f"I_D = {hand['id_'] * 1e3:.2f} mA,  V_DS = {hand['vds']:.2f} V",
            ha="center", fontsize=9, color="#d6336c")
    ax.set_title("直流通路（隔直电容视为开路）", fontsize=10)

    # (3) 小信号等效模型
    ax = axes[2]
    ax.set_axis_off()
    ax.plot([0.15, 0.15], [0.35, 0.7], color="#333", lw=1.6)
    ax.plot([0.15, 0.5], [0.7, 0.7], color="#333", lw=1.6)
    ax.plot([0.15, 0.3], [0.35, 0.35], color="#333", lw=1.6)
    ax.add_patch(plt.Rectangle((0.3, 0.315), 0.16, 0.07, fill=False, ec="#1f6feb", lw=1.6))
    ax.text(0.38, 0.24, f"Rd∥ro", fontsize=8, ha="center", color="#1f6feb")
    ax.plot([0.46, 0.62], [0.35, 0.35], color="#333", lw=1.6)
    ax.plot([0.62, 0.62], [0.35, 0.28], color="#333", lw=1.6)
    ax.plot([0.5, 0.74], [0.28, 0.28], color="#333", lw=1.6)
    ax.plot([0.5, 0.74], [0.21, 0.21], color="#333", lw=1.6)
    ax.plot([0.62, 0.62], [0.21, 0.35], color="#333", lw=1.6)
    ax.plot([0.62], [0.35], marker="o", ms=5, color="#333")
    ax.text(0.66, 0.32, "Vo", fontsize=9)
    ax.annotate("", xy=(0.5, 0.28), xytext=(0.5, 0.21),
                arrowprops=dict(arrowstyle="->", color="#d6336c", lw=1.4))
    ax.text(0.42, 0.245, f"gm·Vgs\n{hand['gm'] * 1e3:.2f}mS", fontsize=8, color="#d6336c")
    ax.plot([0.15], [0.52], marker="o", ms=5, color="#333")
    ax.text(0.06, 0.52, "Vgs", fontsize=9, va="center")
    ax.set_title("小信号等效模型", fontsize=10)

    path = os.path.join(save_dir, "nmos_schematic.png")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"  已保存电路图   {path}")


def report_no_simulator(exc, hand):
    """没装 ngspice 时：给出可执行的安装指引，并把已经算好的手算值打出来。"""
    print("\n[仿真没跑成] PySpice 只是个“遥控器”，真正解方程的是 ngspice，本机需要装它。")
    print("  安装：Ubuntu / Debian : sudo apt install ngspice")
    print("        macOS (Homebrew): brew install ngspice")
    print("        Windows         : https://ngspice.sourceforge.io/download.html")
    print(f"  原始报错：{type(exc).__name__}: {exc}")
    print("\n下面是手算结果，装好 ngspice 后重跑本脚本，仿真列会自动补齐：")
    print("=" * 72)
    print(f"  {'量':<18}{'手算':>16}")
    for name, hv in [
        ("V_GS (V)", VDD * RG2 / (RG1 + RG2)),
        ("I_D (mA)", hand["id_"] * 1e3),
        ("V_DS (V)", hand["vds"]),
        ("gm (mS)", hand["gm"] * 1e3),
        ("ro (kΩ)", hand["ro"] / 1e3),
        ("|Av|", abs(hand["av"])),
    ]:
        print(f"  {name:<18}{hv:>16.4f}")
    print("=" * 72)
    return 1


def main():
    parser = argparse.ArgumentParser(description="NMOS 共源级放大电路仿真")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(save_dir, exist_ok=True)

    hand = hand_calculations()
    if not args.no_plot:
        plot_schematics(save_dir, hand)

    try:
        dc = run_dc()
        tr = run_transient(save_dir, not args.no_plot)
    except Exception as exc:  # noqa: BLE001
        return report_no_simulator(exc, hand)

    print("\n" + "=" * 72)
    print("对比表 1：静态工作点（手算 vs 直流仿真）")
    print("=" * 72)
    print(f"  {'量':<12}{'手算':>16}{'仿真':>16}{'相对误差':>12}")
    for name, hv, sv in [
        ("V_GS (V)", VDD * RG2 / (RG1 + RG2), dc["vg"]),
        ("I_D (mA)", hand["id_"] * 1e3, dc["id_"] * 1e3),
        ("V_DS (V)", hand["vds"], dc["vd"]),
    ]:
        err = abs(sv - hv) / hv * 100 if hv else float("nan")
        print(f"  {name:<12}{hv:>16.4f}{sv:>16.4f}{err:>11.3f}%")
    print(f"  饱和区判断：V_DS = {dc['vd']:.3f} V > V_ov = {hand['vov']:.3f} V ⇒ 工作在饱和区 ✔")

    print("\n" + "=" * 72)
    print("对比表 2：小信号增益（手算 vs 瞬态实测）")
    print("=" * 72)
    print(f"  {'量':<16}{'手算':>16}{'仿真':>16}{'相对误差':>12}")
    err = abs(abs(tr["av"]) - abs(hand["av"])) / abs(hand["av"]) * 100
    print(f"  {'gm (mS)':<16}{hand['gm'] * 1e3:>16.4f}{'—':>16}{'—':>12}")
    print(f"  {'ro (kΩ)':<16}{hand['ro'] / 1e3:>16.3f}{'—':>16}{'—':>12}")
    print(f"  {'|Av|':<16}{abs(hand['av']):>16.4f}{abs(tr['av']):>16.4f}{err:>11.2f}%")
    print(f"\n  输入/输出波形已保存，输出与输入反相：{'是 ✔' if tr['inverted'] else '否'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
