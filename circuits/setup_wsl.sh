#!/usr/bin/env bash
# =====================================================================
# 在 WSL(Ubuntu) 里一键搭好跑这三个电路仿真所需的环境
# =====================================================================
# 为什么需要这个脚本：Windows 上装 ngspice 比较麻烦（还要配共享库路径），
# 而 WSL 里 `apt install ngspice` 装的是**命令行版**，PySpice 要的
# `libngspice.so` 并不在里面。下面这几步把缺的都补上，而且**全程不需要 sudo**
# —— 共享库直接从 deb 包里解出来、用 LD_LIBRARY_PATH 指过去。
#
# 用法（在 Windows 的 PowerShell / CMD 里执行）：
#     wsl -d Ubuntu -- bash /mnt/d/Documents/projects/考核/circuits/setup_wsl.sh
#
# 跑完之后，三个电路这样跑：
#     wsl -d Ubuntu -- bash -lc 'source /tmp/gvenv/env.sh && cd <仓库>/circuits && python rc_lowpass.py'
# =====================================================================
set -e

VENV=/tmp/gvenv
NGDIR=/tmp/ngdeb/ext/usr/lib/x86_64-linux-gnu

echo "==> [1/4] 准备 uv（Python 包管理器，免 sudo）"
if [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uvi.sh
    sh /tmp/uvi.sh >/dev/null 2>&1
fi
UV="$HOME/.local/bin/uv"
"$UV" --version

echo "==> [2/4] 建虚拟环境并装 PySpice / matplotlib"
# 系统 Python 3.14 没有 ensurepip，venv 建不出来，所以让 uv 自己下一个 3.12
if [ ! -x "$VENV/bin/python" ]; then
    "$UV" venv "$VENV" --python 3.12
fi
"$UV" pip install --python "$VENV/bin/python" PySpice matplotlib

echo "==> [3/4] 取 libngspice.so（apt 的 ngspice 只给命令行版，缺这个共享库）"
if [ ! -f "$NGDIR/libngspice.so.0" ]; then
    mkdir -p /tmp/ngdeb
    cd /tmp/ngdeb
    apt-get download libngspice0
    dpkg-deb -x libngspice0_*.deb ext
fi
# PySpice 找的是 libngspice.so，而包里只有 libngspice.so.0，补个软链
ln -sf libngspice.so.0 "$NGDIR/libngspice.so"
ls -la "$NGDIR"/libngspice.so*

echo "==> [4/4] 写一个 env.sh，以后一条 source 就能用"
cat > "$VENV/env.sh" <<EOF
# 由 circuits/setup_wsl.sh 生成：激活仿真环境
export PATH="\$HOME/.local/bin:\$PATH"
export LD_LIBRARY_PATH=$NGDIR:\$LD_LIBRARY_PATH
export MPLBACKEND=Agg
source $VENV/bin/activate
EOF
chmod +x "$VENV/env.sh"

echo
echo "全部就绪。之后这样跑："
echo "    wsl -d Ubuntu -- bash -lc 'source $VENV/env.sh && cd <仓库>/circuits && python rc_lowpass.py'"
