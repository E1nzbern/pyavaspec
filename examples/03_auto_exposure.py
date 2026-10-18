"""自动曝光

寻找让峰值落在满量程 ~70% 的积分时间。

适用于第一次接设备、或换光源、样品后不知道积分时间该设多少时

- 只调整积分时间
- 失败时回滚搜索前的配置
- ``result.converged`` 为 False 时代表积分时间未收敛，但仍会返回最接近目标的一次

运行::

    uv run python examples/03_auto_exposure.py
    uv run python examples/03_auto_exposure.py --target 0.5
"""

from __future__ import annotations

import argparse

from pyavaspec import Spectrometer, auto_exposure


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自动搜索合适的积分时间")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument(
        "--target",
        type=float,
        default=0.7,
        help="目标峰值占满量程的比例（0-1），默认 0.7",
    )
    parser.add_argument("--max-ms", type=float, default=60000.0, help="积分时间上限，默认 60 s")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with Spectrometer(args.serial) as spec:
        print(f"设备：{spec.info.name}  SN={spec.info.serial}")
        result = auto_exposure(
            spec,
            target_fraction=args.target,
            max_integration_ms=args.max_ms,
        )

        print(
            f"结果：积分 {result.integration_ms:.3f} ms，"
            f"峰值 {result.peak_counts:.0f} / {result.saturation_level}"
            f"（{result.peak_fraction:.1%}），迭代 {len(result.history)} 次"
        )
        if not result.converged:
            print("警告：未收敛，信号可能太弱或太强；检查光路后再试。")

        print("\n搜索过程：")
        for step in result.history:
            print(f"  {step.integration_ms:10.3f} ms -> {step.peak_counts:9.0f} counts")

        # auto_exposure 已经把设备配置到最佳积分时间，直接采一帧验证
        frame = spec.measure(saturated_mask=True)
        print(
            f"\n最终光谱：峰值 {frame.peak_counts:.0f} @ {frame.peak_wavelength_nm:.2f} nm，"
            f"饱和={frame.any_pixel_saturated}"
        )


if __name__ == "__main__":
    main()
