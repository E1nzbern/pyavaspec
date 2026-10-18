"""数据的保存和读取

运行::

    uv run python examples/02_save_and_load.py

结果默认存储至 ``examples/output/``
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from pyavaspec import Spectrometer, Spectrum

OUTPUT_DIR = Path(__file__).with_name("output")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with Spectrometer() as spec:
        spec.configure(integration_ms=50.0, averages=1)
        frame = spec.measure(saturated_mask=True)

    stem = "spectrum_001"

    # CSV 只存波长和强度
    csv_path = OUTPUT_DIR / f"{stem}.csv"
    np.savetxt(
        csv_path,
        np.column_stack([frame.wavelengths, frame.counts]),
        delimiter=",",
        header="wavelength_nm,counts",
        comments="",
        fmt=["%.6f", "%.3f"],
    )

    # JSON 存储完整数据，可还原成 Spectrum 类
    json_path = OUTPUT_DIR / f"{stem}.json"
    json_path.write_text(
        json.dumps(frame.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # NPZ 存储比较灵活，可根据实际工作流调整
    npz_path = OUTPUT_DIR / f"{stem}.npz"
    np.savez_compressed(
        npz_path,
        wavelengths=frame.wavelengths,
        counts=frame.counts,
        integration_ms=frame.integration_ms,
        averages=frame.averages,
    )

    for path in (csv_path, json_path, npz_path):
        print(f"已保存 {path}（{path.stat().st_size} Bytes）")

    # 验证 JSON 存储正确性
    loaded = Spectrum.from_dict(json.loads(json_path.read_text(encoding="utf-8")))
    print(f"JSON 是否完全一致：{loaded.equals(frame)}")
    print(f"积分时间 {loaded.integration_ms} ms，像素 {loaded.size}")

    # 验证 CSV 列数
    data = np.loadtxt(csv_path, delimiter=",", skiprows=1)
    print(f"CSV 形状：{data.shape}，峰值 {data[:, 1].max():.0f} counts")


if __name__ == "__main__":
    main()
