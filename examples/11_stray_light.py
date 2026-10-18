"""杂散光抑制

``Spectrometer.suppress_stray_light()`` 调用驱动自带的 ``AVS_SuppressStrayLight`` 纯软件算法。

- ``multi_factor`` 为抑制强度，有效范围 0-2，越大越强；
- 只返回处理后的新帧，原始帧保持不变；
- 抑制效果与光谱形状、探测器型号有关，使用前最好先对比实际样品。

运行::

    uv run python examples/11_stray_light.py
    uv run python examples/11_stray_light.py --factor 1.0 --integration 100
"""

from __future__ import annotations

import argparse

import numpy as np

from pyavaspec import Spectrometer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对比杂散光抑制前后的光谱")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument("--dll", dest="dll_path", help="avaspecx64.dll 的路径")
    parser.add_argument("--integration", type=float, default=100.0, help="积分时间，单位 ms")
    parser.add_argument("--factor", type=float, default=0.5, help="抑制强度 0-2，默认 0.5")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with Spectrometer(args.serial, dll_path=args.dll_path) as spec:
        spec.configure(integration_ms=args.integration)
        frame = spec.measure(saturated_mask=True)
        processed = spec.suppress_stray_light(frame, multi_factor=args.factor)

        # 取峰值另一侧的一段低信号区，杂散光的变化更容易看出来
        peak = frame.peak_index
        margin = max(10, frame.size // 10)
        if peak >= frame.size // 2:
            region = slice(0, max(1, peak - margin))
        else:
            region = slice(min(frame.size, peak + margin), frame.size)
        before = float(np.mean(frame.counts[region]))
        after = float(np.mean(processed.counts[region]))

        print(f"峰值：{frame.peak_counts:.0f} counts @ {frame.peak_wavelength_nm:.2f} nm")
        print(f"抑制强度：{args.factor}")
        print(f"总计数：{frame.counts.sum():.0f} -> {processed.counts.sum():.0f}")
        print(f"远离峰值的低信号区均值：{before:.1f} -> {after:.1f} counts")
        print(f"处理后的最小值：{processed.counts.min():.1f} counts（应为非负）")


if __name__ == "__main__":
    main()
