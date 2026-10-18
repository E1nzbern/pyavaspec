"""面向对象的测量流程示例

把一次完整实验封装成 ``Experiment`` 对象，改造成适合自己工作流的实验脚本

运行::

    uv run python examples/07_measurement_session.py
    uv run python examples/07_measurement_session.py --samples 3 --integration 100
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Self

import numpy as np

from pyavaspec import MeasurementSession, SessionStatus, Spectrometer, StalePolicy

OUTPUT_DIR = Path(__file__).with_name("output")


class Experiment:
    """一次参考谱和若干样品的实验"""

    def __init__(
        self,
        serial: str | None = None,
        *,
        output_dir: Path = OUTPUT_DIR,
        policy: StalePolicy = "warn",
    ) -> None:
        self.spec = Spectrometer(serial)
        self.session = MeasurementSession(self.spec, policy=policy)
        self.output_dir = output_dir

    def __enter__(self) -> Self:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.spec.open()
        info = self.spec.info
        print(f"设备：{info.name}  SN={info.serial}  像素：{info.num_pixels}")
        return self

    def __exit__(self, *exc: object) -> None:
        self.spec.close()

    def setup(self, integration_ms: float, averages: int = 1) -> None:
        cfg = self.spec.configure(integration_ms=integration_ms, averages=averages)
        print(
            f"测量配置：积分 {cfg.integration_ms} ms，平均 {cfg.averages}，"
            f"像素窗口 [{cfg.start_pixel}, {cfg.stop_pixel}]"
        )

    def calibrate(self, frames: int = 10) -> None:
        input("\n请遮光，然后按回车采集暗谱...")
        dark = self.session.capture_dark(frames=frames)
        input("请放入白参考，然后按回车采集亮谱...")
        bright = self.session.capture_bright(frames=frames)

        print(f"暗谱已保存：{dark.save(self.output_dir / 'dark.json')}")
        print(f"亮谱已保存：{bright.save(self.output_dir / 'bright.json')}")
        status = self.session.status()
        if not status.relative_ok:
            print(f"⚠ {status.message}")

    def measure_sample(self, label: str) -> Path:
        measurement = self.session.measure()
        if not measurement.status.ok:
            print(f"[提示] {measurement.status.message}")

        # 原始谱永远可用，扣暗背景的谱只在参考谱条件与当前配置一致时才有值
        if measurement.corrected is not None:
            data = measurement.corrected
            source = "已扣暗"
        else:
            data = measurement.spectrum
            source = "原始"

        csv_path = self.output_dir / f"{label}.csv"
        np.savetxt(
            csv_path,
            np.column_stack([data.wavelengths, data.counts]),
            delimiter=",",
            header="wavelength_nm,counts",
            comments="",
            fmt=["%.6f", "%.3f"],
        )
        meta = {
            "label": label,
            "serial": self.spec.info.serial,
            "integration_ms": data.integration_ms,
            "averages": data.averages,
            "source": source,
            "status_ok": measurement.status.ok,
            "status_message": measurement.status.message,
        }
        csv_path.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"{label}：{source}，峰值 {data.peak_counts:.0f} counts @ "
            f"{data.peak_wavelength_nm:.2f} nm -> {csv_path}"
        )
        return csv_path

    def status(self) -> SessionStatus:
        return self.session.status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用 MeasurementSession 组织一次实验")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument("--integration", type=float, default=50.0, help="积分时间，单位 ms")
    parser.add_argument("--frames", type=int, default=10, help="每张参考谱的采集帧数")
    parser.add_argument("--samples", type=int, default=2, help="样品数量")
    parser.add_argument(
        "--policy",
        choices=["warn", "strict", "off"],
        default="warn",
        help="参考谱失效时的策略，默认 warn",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with Experiment(args.serial, policy=args.policy) as experiment:
        experiment.setup(args.integration)
        experiment.calibrate(frames=args.frames)

        for index in range(1, args.samples + 1):
            input(f"\n请放入第 {index} 个样品，然后按回车...")
            experiment.measure_sample(f"sample_{index:02d}")

        print("\n最终参考谱状态：")
        print(json.dumps(experiment.status().as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
