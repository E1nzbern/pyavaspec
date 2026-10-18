"""利用光谱仪板载 RAM 以尽可能短的间隔连续采 N 帧

``acquire_to_ram()`` 使用光谱仪自带 RAM 做缓冲，适合快速动力学、闪烁、稳定性采样。

限制：

- 设备端 ``averages`` 必须为 1；
- 需要软件触发；
- 采集期间不能修改配置，结束后 ``store_to_ram`` 会自动复位

运行::

    uv run python examples/08_ram_batch.py
    uv run python examples/08_ram_batch.py --frames 500 --integration 5

结果保存为 ``examples/output/ram_batch.npz``，``counts`` 形状为 ``帧数 x 像素数``
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from pyavaspec import IncompleteAcquisitionError, Spectrometer

OUTPUT_DIR = Path(__file__).with_name("output")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用板载 RAM 批量采集")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument("--integration", type=float, default=5.0, help="积分时间，单位 ms")
    parser.add_argument("--frames", type=int, default=200, help="采集帧数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Spectrometer(args.serial) as spec:
        # RAM 采集要求 averages == 1，软件触发
        spec.configure(integration_ms=args.integration, averages=1)
        print(
            f"设备：{spec.info.name}  SN={spec.info.serial}  "
            f"积分 {args.integration} ms，采集 {args.frames} 帧"
        )

        start = time.monotonic()
        try:
            frames = spec.acquire_to_ram(args.frames)
        except IncompleteAcquisitionError as exc:
            # 缓冲深度和触发不匹配时会无法取回所有帧
            frames = exc.partial_frames
            print(f"未取满：请求 {exc.requested} 帧，实际 {len(frames)} 帧")
        elapsed = time.monotonic() - start

        if not frames:
            raise SystemExit("没有取到任何帧，请检查积分时间和触发配置")

        counts = np.stack([frame.counts for frame in frames])
        print(f"取回 {len(frames)} 帧，耗时 {elapsed:.3f}s，约 {len(frames) / elapsed:.1f} 帧/s")
        print(f"counts 形状：{counts.shape}，全局峰值：{counts.max():.0f} counts")
        print(f"帧间峰值范围：{counts.max(axis=1).min():.0f} - {counts.max(axis=1).max():.0f}")

        npz_path = OUTPUT_DIR / "ram_batch.npz"
        np.savez_compressed(
            npz_path,
            wavelengths=frames[0].wavelengths,
            counts=counts,
            timestamps_s=np.array([frame.timestamp_s for frame in frames]),
            integration_ms=args.integration,
        )
        print(f"已保存：{npz_path}")

        # acquire_to_ram 结束后 store_to_ram 已复位，可以继续普通采集
        frame = spec.measure()
        print(f"之后单帧采集正常：峰值 {frame.peak_counts:.0f} counts")


if __name__ == "__main__":
    main()
