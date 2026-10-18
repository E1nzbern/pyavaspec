"""Hello World!

运行::

    uv run python examples/01_hello_spectrum.py
    uv run python examples/01_hello_spectrum.py --serial 1908001U1
    uv run python examples/01_hello_spectrum.py --integration 100 --averages 2

前提::

Windows x64，已安装 AvaSoftX 驱动。
若库找不到动态链接库，请设置 ``AVASPEC_DLL`` 环境变量，或通过 ``--dll`` 传递参数
"""

from __future__ import annotations

import argparse

from pyavaspec import Spectrometer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集一帧光谱并输出关键指标")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument("--dll", dest="dll_path", help="avaspecx64.dll 的路径")
    parser.add_argument("--integration", type=float, default=50.0, help="积分时间，单位 ms")
    parser.add_argument("--averages", type=int, default=1, help="设备端平均次数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 使用上下文管理器管理设备调用的生命周期
    with Spectrometer(args.serial, dll_path=args.dll_path) as spec:
        info = spec.info
        print(f"设备：{info.name}  SN={info.serial}")
        print(f"像素：{info.num_pixels}  传感器：{info.sensor_name}  探测器：{info.detector_name}")
        print(f"固件：{info.firmware_version}  FPGA：{info.fpga_version}  DLL：{info.dll_version}")

        # configure 只修改明确给出的字段，其余保持当前值
        cfg = spec.configure(integration_ms=args.integration, averages=args.averages)
        print(
            f"配置：积分 {cfg.integration_ms} ms  平均 {cfg.averages}  "
            f"像素窗口 [{cfg.start_pixel}, {cfg.stop_pixel}]  满量程 {cfg.saturation_level}"
        )

        # saturated_mask=True 会额外返回每个像素是否饱和
        frame = spec.measure(saturated_mask=True)
        print(f"波长范围：{frame.wavelengths[0]:.2f} - {frame.wavelengths[-1]:.2f} nm")
        print(f"峰值：{frame.peak_counts:.0f} counts @ {frame.peak_wavelength_nm:.2f} nm")
        print(f"均值：{frame.mean:.1f} counts")
        if frame.saturated_mask is not None:
            print(f"饱和像素：{int(frame.saturated_mask.sum())} / {frame.size}")

        if frame.any_pixel_saturated:
            print("提示：存在饱和像素，请降低积分时间或平均次数。")
        elif frame.peak_counts < 0.1 * cfg.saturation_level:
            print("提示：信号偏弱，可以尝试增加积分时间。")


if __name__ == "__main__":
    main()
