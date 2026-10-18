"""多帧平均：设备端平均与软件平均的差别。

降噪效果要用时间噪声衡量，即对同一个像素连续采多帧，看强度的标准差。
不能只看单帧内一段像素的空间标准差，会包含光谱形状，使噪声偏大。

流程：

1. ``averages=1`` 连续采集 N 帧，估计单帧时间噪声；
2. 把 N 帧分成两半各自平均，用两半之差估计软件平均后的噪声；
3. ``averages=M`` 再连采若干帧，估计设备端平均后的噪声。

运行::

    uv run python examples/05_averaging.py
    uv run python examples/05_averaging.py --frames 200 --integration 20
"""

from __future__ import annotations

import argparse

import numpy as np

from pyavaspec import Spectrometer, Spectrum, mean_spectrum


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="比较多帧平均前后的时间噪声")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument("--integration", type=float, default=20.0, help="积分时间，单位 ms")
    parser.add_argument("--frames", type=int, default=100, help="用于软件平均的帧数")
    return parser.parse_args()


def temporal_noise(frames: list[Spectrum]) -> float:
    """
    逐像素计算时间标准差，再取中位数。

    中位数能避开坏点等离群值。
    """
    stack = np.stack([frame.counts for frame in frames])
    return float(np.median(stack.std(axis=0)))


def main() -> None:
    args = parse_args()
    if args.frames < 4:
        raise SystemExit("--frames 至少为 4")

    with Spectrometer(args.serial) as spec:
        spec.configure(integration_ms=args.integration, averages=1)
        frames = list(spec.measure_many(args.frames))

        single_noise = temporal_noise(frames)
        print(f"单帧时间噪声       ~{single_noise:8.2f} counts")

        # 奇偶帧各自平均，再比较两个平均结果
        # 交错取帧能让二者覆盖同一段时间，抵消光源慢漂移
        # 两个独立平均之差的标准差 = 各自噪声 * sqrt(2)
        half = len(frames) // 2
        avg_a = mean_spectrum(frames[0::2])
        avg_b = mean_spectrum(frames[1::2])
        diff = avg_a.counts - avg_b.counts
        pair_noise = float(np.sqrt((diff * diff).mean() / 2.0))
        print(f"{half} 帧软件平均噪声  ~{pair_noise:8.2f} counts", end="")
        if single_noise > 0:
            print(f"（降低 {single_noise / pair_noise:.1f} 倍，理论 sqrt(N)={np.sqrt(half):.1f}）")
        else:
            print()

        averaged = mean_spectrum(frames)
        print(f"峰值：单帧 {frames[0].peak_counts:.0f} -> 平均后 {averaged.peak_counts:.0f} counts")

        # 设备端平均在光谱仪内部完成，上位机只会收到一帧光谱数据
        device_n = min(args.frames, 20)  # 不同型号对平均次数上限不同，这里取 20
        spec.configure(averages=device_n)
        device_frames = list(spec.measure_many(10))
        device_noise = temporal_noise(device_frames)
        print(f"\n设备端平均 {device_n} 次噪声 ~{device_noise:8.2f} counts", end="")
        if device_noise > 0:
            print(
                f"（降低 {single_noise / device_noise:.1f} 倍，理论 sqrt(N)="
                f"{np.sqrt(device_n):.1f}）"
            )
        else:
            print()
        print(f"设备端平均后峰值：{device_frames[0].peak_counts:.0f} counts")
        print("注：实测降幅通常低于 sqrt(N)。光源漂移、固定图案噪声等帧间相关成分不会被平均掉。")


if __name__ == "__main__":
    main()
