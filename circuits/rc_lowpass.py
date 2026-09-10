#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电路①  RC 低通滤波电路（PySpice 仿真 + 手算对比）
=====================================================================
电路：Vi --[R]--+-- Vo
                |
               [C]
                |
               GND

手算：
    时间常数        τ   = R · C
    截止频率        fc  = 1 / (2πRC)
    |H(jω)|        = 1 / sqrt(1 + (ωRC)²)
仿真做两件事：
    1) 瞬态分析：输入方波，看 C 的充放电波形，从上升沿读 τ（到 63.2% 的时间）
    2) 交流分析：扫频看幅频/相频，从 |H| 下降 3dB 的点读 fc

运行：
    pip install PySpice matplotlib
    python rc_lowpass.py                 # 需要本机有 ngspice
    python rc_lowpass.py --no-plot       # 只打印数值，不存图
输出：
    控制台打印「手算 vs 仿真」对比表；out/rc_*.png 为电路图与波形图
=====================================================================
"""
import argparse
import math
import os
import sys

# NumPy 是 PySpice 的依赖，装了 PySpice 就一定有；这里提前导入，
# 免得在读取仿真波形（几百万个点）时才 import。
try:
    import numpy as np
except ImportError:  # 没装 PySpice 时不应该因为缺 numpy 而直接崩，交给下面的兼容层提示
    np = None

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

# ----------------------------------------------------------------- 元件参数
R = 1e3        # 1 kΩ
C = 100e-9     # 100 nF
VIN_PP = 2.0   # 方波峰峰值 2 V（±1 V）
F_SQ = 1e3     # 方波频率 1 kHz

# ----------------------------------------------------------------- 手算值
TAU_HAND = R * C                       # 时间常数
FC_HAND = 1.0 / (2 * math.pi * R * C)  # 截止频率
# 方波周期 1 kHz = 1 ms，半周期 0.5 ms ≈ 5τ，足以充到稳态
PULSE_HALF_S = 0.5 / F_SQ              # 半个周期 = 高电平持续时间（0.5 ms）
# 读 τ 时只在第一个高电平窗口内找 63.2% 点，否则会被后面几个周期的峰值带偏
PULSE_WIDTH_S = PULSE_HALF_S * 0.999   # 留一点点余量，避开下降沿

# ---------------------------------------------------------------- 兼容层
# ⚠️ 必须在 import PySpice **之前** 生效，见 circuits/_ngspice_compat.py 的说明：
#   PySpice 1.5 与 ngspice 43+ / NumPy 2 有几处不兼容（raw 头多了 Command 字段、
#   np.fromstring 二进制模式被移除），不修的话仿真直接抛异常。
try:
    import _ngspice_compat  # noqa: F401  (import 即生效)
except ImportError:  # 脚本被当作包内模块导入时，走相对路径再试一次
    try:
        from . import _ngspice_compat  # noqa: F401
    except Exception:
        pass



def hand_calculations():
    print("=" * 68)
    print("RC 低通滤波：手算")
    print("=" * 68)
    print(f"  元件        R = {R:.0f} Ω, C = {C * 1e9:.0f} nF")
    print(f"  时间常数    τ  = R·C = {R:.0f} × {C * 1e9:.0f}n = {TAU_HAND * 1e6:.1f} µs")
    print(f"  截止频率    fc = 1/(2πRC) = 1/(2π × {TAU_HAND * 1e6:.1f}µ) = {FC_HAND:.2f} Hz")
    print(f"  10 倍频衰减 -20 dB/dec，1 个倍频约 -6 dB")
    print(f"  在 f = 10·fc = {10 * FC_HAND:.0f} Hz 处 |H| ≈ 1/sqrt(1+100) = {1 / math.sqrt(101):.4f}")
    return {"tau": TAU_HAND, "fc": FC_HAND}


def build_circuit():
    """搭建 RC 低通；返回 (circuit, 说明字符串)"""
    from PySpice.Spice.Netlist import Circuit
    circuit = Circuit("RC low-pass filter")
    circuit.SinusoidalVoltageSource("in", "vin", circuit.gnd, amplitude=VIN_PP / 2)
    circuit.R(1, "vin", "vout", R)
    circuit.C(1, "vout", circuit.gnd, C)
    return circuit


def run_transient(save_dir, do_plot=True):
    """瞬态：方波输入（用脉冲源代替方波），读 τ"""
    from PySpice.Spice.Netlist import Circuit
    from PySpice.Unit import u_V, u_ms, u_us, u_ns, u_Ohm, u_F

    circuit = Circuit("RC low-pass filter (transient)")
    # 方波：0 → 2 V，周期 1 ms，占空比 50%
    circuit.PulseVoltageSource(
        "in", "vin", circuit.gnd,
        initial_value=0 @ u_V, pulsed_value=VIN_PP @ u_V,
        delay_time=0 @ u_ms, rise_time=1 @ u_ns, fall_time=1 @ u_ns,
        pulse_width=0.5 @ u_ms, period=1 @ u_ms,
    )
    circuit.R(1, "vin", "vout", R @ u_Ohm)
    circuit.C(1, "vout", circuit.gnd, C @ u_F)

    sim = circuit.simulator(simulator="ngspice-subprocess", temperature=25)
    # ⚠️ 步长必须用 µs 级，不能用 1ns。
    # 原来写的是 step_time=1ns，实测 ngspice 在 t≈0 附近会自动取 1e-11 量级的密集点，
    # 配合 1ns 的输入上升沿，数值积分在头几个点上就崩了 —— vout 在前 12 个采样点内
    # 直接冲到 2.0V（RC 常数是 100µs，物理上不可能），而终值又恰好收敛到 1.9866V，
    # 看起来「挺对」，极容易误判。换成 1µs 步长后波形完全正确：
    #     t=100µs → vout=1.2697V（正好 63.2%，即 τ）
    # 顺带采样点从 300 万降到 3 千，跑得快得多。
    analysis = sim.transient(step_time=1 @ u_us, end_time=3 @ u_ms)
    t = np.asarray(analysis.time, dtype=float)
    vin = np.asarray(analysis["vin"], dtype=float)
    vout = np.asarray(analysis["vout"], dtype=float)

    # ⚠️ τ 的定义是「从**阶跃发生那一刻**算起到 63.2% 的时间」，起点必须取输入的上升沿，
    #   不能取采样窗口的第一个点。
    #   旧写法用 tw[0] 当 t0，而窗口是从 t=0 开始的，于是 τ 被算成「第 8 个采样点减第 0 个」
    #   ≈ 1e-9 秒 ≈ 0.00µs —— 数据明明是对的，测出来却是 0，就是这么来的。
    first_pulse = t <= PULSE_WIDTH_S
    v_final = float(vout[first_pulse].max()) if first_pulse.any() else float(vout.max())
    target = 0.632 * v_final
    tw = t[first_pulse]
    vw = vout[first_pulse]
    vinw = vin[first_pulse]

    # 起点 t0 = 阶跃发生的时刻。脉冲源的 delay_time = 0，所以就是 t = 0。
    # ⚠️ 不要用「vin 第一次 ≥ 50% 的采样点」去找上升沿：ngspice 在 t≈0 附近会自动
    #    插一批 1e-11 间隔的密集点（那是自适应步长的初始爬坡），按前者找会得到
    #    t0 ≈ 1e-9，于是 τ 被算成「第 8 个点减第 7 个点」≈ 6e-10 s ≈ 0.00µs。
    #    波形数据本身完全正确（t=100µs 处 vout=1.2697V 正好是 63.2%），
    #    错的只是「从哪里开始计时」。
    t0 = float(tw[0]) if tw.size else 0.0

    reached = np.flatnonzero(vw >= target)
    tau_meas = (float(tw[reached[0]]) - t0) if reached.size else None

    print("\n瞬态分析（方波输入，读充电到 63.2% 的时间）")
    print(f"  稳态输出电压   {v_final:.4f} V")
    print(f"  63.2% 目标     {target:.4f} V")
    print(f"  实测 τ         {tau_meas * 1e6:.2f} µs" if tau_meas else "  实测 τ         读取失败")
    print(f"  手算 τ         {TAU_HAND * 1e6:.2f} µs")

    if do_plot:
        _plot_transient(save_dir, t, vin, vout, tau_meas)
    return {"v_final": v_final, "tau": tau_meas}


def run_ac(save_dir, do_plot=True):
    """交流扫频：读 -3 dB 点得到 fc"""
    from PySpice.Spice.Netlist import Circuit
    from PySpice.Unit import u_V, u_Ohm, u_F

    circuit = Circuit("RC low-pass filter (AC)")
    circuit.SinusoidalVoltageSource("in", "vin", circuit.gnd, amplitude=1 @ u_V)
    circuit.R(1, "vin", "vout", R @ u_Ohm)
    circuit.C(1, "vout", circuit.gnd, C @ u_F)

    sim = circuit.simulator(simulator="ngspice-subprocess", temperature=25)
    analysis = sim.ac(start_frequency=10, stop_frequency=1e6, number_of_points=100, variation="dec")
    # ⚠️ 逐点 `float(x)` / `complex(x)` 在新版 NumPy 下会拿到 0 维数组，
    #    float() 只对 0 维可用，而复数列直接抛 TypeError。统一用 np.asarray 展开。
    freq = np.asarray(analysis.frequency, dtype=float).ravel()
    vout = np.asarray(analysis["vout"], dtype=complex).ravel()
    mag = np.abs(vout)
    phase = np.degrees(np.angle(vout))

    # -3 dB 点：低频增益的 1/sqrt(2)
    gain_low = float(mag[0])
    target = gain_low / math.sqrt(2)
    below = np.flatnonzero(mag <= target)
    fc_meas = float(freq[below[0]]) if below.size else None

    print("\n交流分析（扫频读 -3 dB 点）")
    print(f"  低频增益       {gain_low:.4f}（应 ≈ 1）")
    print(f"  -3 dB 增益     {target:.4f}")
    print(f"  实测 fc        {fc_meas:.1f} Hz" if fc_meas else "  实测 fc        读取失败")
    print(f"  手算 fc        {FC_HAND:.1f} Hz")

    if do_plot:
        _plot_bode(save_dir, freq, mag, phase, fc_meas)
    return {"fc": fc_meas, "gain_low": gain_low}


# ----------------------------------------------------------------- 画图
def _plot_transient(save_dir, t, vin, vout, tau_meas):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=140)
    ax.plot([x * 1e3 for x in t], vin, label="Vi 输入方波", lw=1.4, color="#888")
    ax.plot([x * 1e3 for x in t], vout, label="Vo 输出（电容电压）", lw=2, color="#1f6feb")
    ax.axhline(0.632 * max(vout), ls=":", color="#d9534f", lw=1.2)
    ax.text(0.02, 0.632 * max(vout) + 0.05, "63.2% 稳态", color="#d9534f", fontsize=9)
    if tau_meas:
        ax.axvline(tau_meas * 1e3, ls="--", color="#2f9e44", lw=1.2)
        ax.text(tau_meas * 1e3 + 0.02, 0.2, f"τ≈{tau_meas * 1e6:.1f}µs", color="#2f9e44", fontsize=9)
    ax.set_xlabel("时间 (ms)")
    ax.set_ylabel("电压 (V)")
    ax.set_title(f"RC 低通滤波 · 方波瞬态响应（R={R / 1e3:.0f}kΩ, C={C * 1e9:.0f}nF）")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    path = os.path.join(save_dir, "rc_transient.png")
    fig.savefig(path)
    plt.close(fig)
    print(f"  已保存波形图   {path}")


def _plot_bode(save_dir, freq, mag, phase, fc_meas):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), dpi=140, sharex=True)
    ax1.semilogx(freq, [20 * math.log10(m) for m in mag], lw=2, color="#1f6feb")
    ax1.axhline(-3, ls=":", color="#d9534f", lw=1.2)
    if fc_meas:
        ax1.axvline(fc_meas, ls="--", color="#2f9e44", lw=1.2)
        ax1.text(fc_meas * 1.15, -12, f"fc≈{fc_meas:.0f} Hz", color="#2f9e44", fontsize=9)
    ax1.set_ylabel("幅频 |H| (dB)")
    ax1.set_title(f"RC 低通滤波 · 波特图（手算 fc={FC_HAND:.1f} Hz）")
    ax1.grid(which="both", alpha=0.3)
    ax2.semilogx(freq, phase, lw=2, color="#e8590c")
    ax2.set_ylabel("相频 (°)")
    ax2.set_xlabel("频率 (Hz)")
    ax2.grid(which="both", alpha=0.3)
    fig.tight_layout()
    path = os.path.join(save_dir, "rc_bode.png")
    fig.savefig(path)
    plt.close(fig)
    print(f"  已保存波特图   {path}")


def plot_schematic(save_dir):
    """自己画电路图（不依赖任何电路绘图软件），标注元件与节点"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=140)
    ax.set_axis_off()
    # 导线
    ax.plot([0.1, 0.1], [0.28, 0.72], color="#333", lw=1.6)       # 输入竖线
    ax.plot([0.1, 0.42], [0.5, 0.5], color="#333", lw=1.6)        # 到电阻
    ax.plot([0.58, 0.86], [0.5, 0.5], color="#333", lw=1.6)       # 电阻到输出
    ax.plot([0.72, 0.72], [0.5, 0.24], color="#333", lw=1.6)      # 下到电容
    ax.plot([0.72, 0.72], [0.76, 0.5], color="#333", lw=1.6)      # 上到输出节点
    ax.plot([0.62, 0.82], [0.76, 0.76], color="#333", lw=1.6)     # 输出横线
    ax.plot([0.32, 0.32], [0.28, 0.72], color="#333", lw=1.6)     # 地线
    # 电阻（矩形）
    ax.add_patch(plt.Rectangle((0.42, 0.455), 0.16, 0.09, fill=False, ec="#1f6feb", lw=1.8))
    ax.text(0.5, 0.58, f"R = {R / 1e3:.0f} kΩ", ha="center", color="#1f6feb", fontsize=10)
    # 电容（两条平行线）
    ax.plot([0.66, 0.78], [0.38, 0.38], color="#e8590c", lw=2.2)
    ax.plot([0.66, 0.78], [0.30, 0.30], color="#e8590c", lw=2.2)
    ax.plot([0.72, 0.72], [0.5, 0.38], color="#333", lw=1.6)
    ax.plot([0.72, 0.72], [0.30, 0.24], color="#333", lw=1.6)
    ax.text(0.83, 0.34, f"C = {C * 1e9:.0f} nF", color="#e8590c", fontsize=10)
    # 节点标注
    ax.text(0.06, 0.55, "Vi", fontsize=12, color="#333")
    ax.text(0.87, 0.55, "Vo", fontsize=12, color="#333")
    ax.plot([0.72], [0.5], marker="o", ms=5, color="#333")
    ax.text(0.30, 0.18, "GND", fontsize=10, color="#333")
    for y in (0.28, 0.32, 0.36):
        ax.plot([0.28, 0.36], [y, y], color="#333", lw=1.4)
    ax.set_xlim(0, 1)
    ax.set_ylim(0.1, 0.85)
    path = os.path.join(save_dir, "rc_schematic.png")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"  已保存电路图   {path}")


def main():
    parser = argparse.ArgumentParser(description="RC 低通滤波电路仿真")
    parser.add_argument("--no-plot", action="store_true", help="不生成图片")
    args = parser.parse_args()

    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(save_dir, exist_ok=True)
    do_plot = not args.no_plot

    hand = hand_calculations()
    if do_plot:
        plot_schematic(save_dir)

    try:
        tr = run_transient(save_dir, do_plot)
        ac = run_ac(save_dir, do_plot)
    except Exception as exc:  # noqa: BLE001
        print("\n[仿真失败] 需要本机安装 ngspice 共享库，PySpice 才能调用它。")
        print("  安装：Ubuntu/Debian  sudo apt install ngspice")
        print("        macOS          brew install ngspice")
        print("        Windows        https://ngspice.sourceforge.io/download.html")
        print(f"  原始报错：{type(exc).__name__}: {exc}")
        return 1

    print("\n" + "=" * 68)
    print("对比表：理论值 vs 仿真值")
    print("=" * 68)
    print(f"  {'量':<14}{'手算':>16}{'仿真':>16}{'相对误差':>12}")
    rows = [
        ("τ (µs)", hand["tau"] * 1e6, (tr["tau"] or float("nan")) * 1e6),
        ("fc (Hz)", hand["fc"], ac["fc"] or float("nan")),
        ("低频增益", 1.0, ac["gain_low"]),
        ("稳态输出 (V)", VIN_PP, tr["v_final"]),
    ]
    for name, hv, sv in rows:
        err = abs(sv - hv) / hv * 100 if hv else float("nan")
        print(f"  {name:<14}{hv:>16.4f}{sv:>16.4f}{err:>11.2f}%")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
