"""连续采集

使用 stream() 持续读取帧，输入 Ctrl+C 中断或达到最大帧数后退出。

适合观察实时信号、调光路、做简单的稳定性检查。

运行::

    uv run python examples/04_stream.py
    uv run python examples/04_stream.py --frames 100 --integration 20
"""

from __future__ import annotations

import argparse
import time

from pyavaspec import Spectrometer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="连续采集并打印帧率和峰值")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument("--integration", type=float, default=20.0, help="积分时间，单位 ms")
    parser.add_argument(
        "--frames",
        type=int,
        default=100,
        help="采集多少帧后停止；设为 0 表示持续采集直到 Ctrl+C 中断",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with Spectrometer(args.serial) as spec:
        spec.configure(integration_ms=args.integration, averages=1)
        print(f"连续采集：积分 {args.integration} ms，Ctrl+C 可随时停止")

        seen = 0
        start = time.monotonic()
        try:
            with spec.stream() as stream:
                for frame in stream:
                    seen += 1
                    if seen == 1 or seen % 10 == 0:
                        elapsed = time.monotonic() - start
                        fps = seen / elapsed if elapsed > 0 else 0.0
                        print(
                            f"#{seen:5d}  {fps:6.1f} 帧/s  "
                            f"峰值 {frame.peak_counts:8.0f} @ "
                            f"{frame.peak_wavelength_nm:8.2f} nm"
                        )
                    if args.frames and seen >= args.frames:
                        break
        except KeyboardInterrupt:
            print("\n收到 Ctrl+C，停止采集")

        elapsed = time.monotonic() - start
        if seen:
            print(f"\n共 {seen} 帧，耗时 {elapsed:.2f}s，平均 {seen / elapsed:.1f} 帧/s")
        else:
            print("\n没有采集到帧")

        # 退出 stream 后设备仍是打开状态，可以继续单帧采集
        frame = spec.measure()
        print(f"stream 之后单帧采集正常：峰值 {frame.peak_counts:.0f} counts")


if __name__ == "__main__":
    main()
