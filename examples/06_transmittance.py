"""参考谱和透射比、吸光度的计算

完整流程：

1. 固定积分时间，之后不要改，否则参考谱与测量谱的测量条件不一致无法进行后续计算；
2. 遮光，采暗谱 D；
3. 放入标准白板参考，采亮谱 R；
4. 放入样品，测一帧 S；
5. 透射比 T = (S - D) / (R - D)，吸光度 A = -log10(T)；
6. 参考谱和结果都保存到 ``examples/output/``。

运行::

    uv run python examples/06_transmittance.py
    uv run python examples/06_transmittance.py --integration 100 --frames 20
    uv run python examples/06_transmittance.py --integration 10000 --timeout 60
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from pyavaspec import (
    MeasurementTimeoutError,
    Reference,
    ReferencePair,
    Spectrometer,
    capture_reference,
    check_reference,
)

OUTPUT_DIR = Path(__file__).with_name("output")


def wait(message: str) -> None:
    input(f"\n{message}\n准备好后按回车继续...")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集参考谱并计算透射比 / 吸光度")
    parser.add_argument("--serial", help="设备序列号；只有一台设备时可省略")
    parser.add_argument("--integration", type=float, default=50.0, help="积分时间，单位 ms")
    parser.add_argument("--frames", type=int, default=10, help="每张参考谱的采集帧数")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="单帧等待超时，单位 s；默认按积分时间自动估算（10 s 积分约 25 s）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        run(args)
    except MeasurementTimeoutError as exc:
        print(f"\n采集超时：{exc}", file=sys.stderr)
        print(
            "请调大 --timeout（例如 10 s 积分用 --timeout 60），"
            "或降低 --integration 后重新采集参考谱。",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def run(args: argparse.Namespace) -> None:
    with Spectrometer(args.serial) as spec:
        cfg = spec.configure(integration_ms=args.integration, averages=1)
        print(f"设备：{spec.info.name}  SN={spec.info.serial}")
        print(f"积分时间固定为 {cfg.integration_ms} ms，采集过程中不要修改。")

        wait("请完全遮住光谱仪的入光口（采暗谱 D）")
        dark = capture_reference(spec, "dark", frames=args.frames, timeout_s=args.timeout)

        wait("请放入白参考（透射测量用空白比色皿，反射测量用白板）")
        bright = capture_reference(spec, "bright", frames=args.frames, timeout_s=args.timeout)

        # 构造时校验两张参考谱的种类、来源设备和测量条件，不匹配会直接抛异常
        pair = ReferencePair(dark=dark, bright=bright)
        dark_path = dark.save(OUTPUT_DIR / "dark.json")
        bright_path = bright.save(OUTPUT_DIR / "bright.json")
        print(f"\n暗谱已保存：{dark_path}")
        print(f"亮谱已保存：{bright_path}")
        print(f"暗谱状态：{check_reference(dark, spec.measurement_config).message}")

        wait("请放入待测样品")
        sample = spec.measure(timeout_s=args.timeout, saturated_mask=True)
        if sample.any_pixel_saturated:
            print("警告：样品信号饱和，结果不可靠；建议降低积分时间后重新采集参考谱。")

        transmittance = pair.transmittance(sample)
        absorbance = transmittance.absorbance()
        valid = int(transmittance.valid.sum())
        print(f"\n有效像素：{valid} / {transmittance.size}")
        if valid:
            mean_t = float(transmittance.values[transmittance.valid].mean())
            print(f"平均透射比：{mean_t:.4f}")
        print(f"峰值波长：{sample.peak_wavelength_nm:.2f} nm")

        result_path = OUTPUT_DIR / "transmittance.csv"
        np.savetxt(
            result_path,
            np.column_stack(
                [
                    transmittance.wavelengths,
                    transmittance.values,
                    absorbance.values,
                    transmittance.valid.astype(int),
                ]
            ),
            delimiter=",",
            header="wavelength_nm,transmittance,absorbance,valid",
            comments="",
            fmt=["%.6f", "%.8f", "%.8f", "%d"],
        )
        print(f"结果已保存：{result_path}")

        # 演示复用参考谱，下次实验可以直接 load，无需重新遮光或者采集参考
        reloaded = ReferencePair(
            dark=Reference.load(dark_path),
            bright=Reference.load(bright_path),
        )
        reloaded_t = reloaded.transmittance(sample)
        if valid:
            mean_t = float(reloaded_t.values[transmittance.valid].mean())
            print(f"从磁盘重新加载参考谱后计算的平均透射比：{mean_t:.4f}")
        else:
            print(
                "没有有效像素：参考谱信号太弱、样品在该波段完全不透光，"
                "或参考谱与样品几乎相同（分母 R-D 接近 0，比值无定义）。"
            )


if __name__ == "__main__":
    main()
