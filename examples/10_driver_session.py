"""枚举设备和共享驱动会话

日常直接使用 ``Spectrometer()`` 即可。需要先枚举、按状态选择设备，或让多次
操作共享一次驱动初始化时，使用 ``DriverSession``：

- ``DriverSession`` 本身不打开设备，只负责管理驱动的生命周期；
- ``Spectrometer(session=...)`` 借用会话，因此会话必须比光谱仪活得更久；
- 传入 ``session`` 时不能再指定 ``dll_path`` 或 ``port``。

运行::

    uv run python examples/10_driver_session.py
    uv run python examples/10_driver_session.py --port eth
"""

from __future__ import annotations

import argparse

from pyavaspec import DriverSession, Port, Spectrometer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="枚举设备并在共享驱动会话中采集")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument("--dll", dest="dll_path", help="avaspecx64.dll 的路径")
    parser.add_argument(
        "--port",
        choices=["usb", "eth"],
        default="usb",
        help="设备端口类型，默认 usb",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    port = Port.ETH if args.port == "eth" else Port.USB

    with DriverSession(args.dll_path, port=port) as session:
        devices = session.list_devices()
        if not devices:
            raise SystemExit("未发现设备，请检查 AvaSoftX 驱动和连接")

        print(f"发现 {len(devices)} 台设备：")
        for device in devices:
            status = session.get_status_by_serial(device.serial)
            print(f"  SN={device.serial}  型号={device.name}  状态={status.name}")

        # 也可以直接用模块级便捷函数，但它会在没有传入 session 时临时初始化一次驱动
        # list_devices(session=session)
        # status_by_serial(serial, session=session)

        target = args.serial or devices[0].serial
        with Spectrometer(target, session=session) as spec:
            spec.configure(integration_ms=50.0)
            frame = spec.measure()
            print(f"\n从 {target} 采集一帧：峰值 {frame.peak_counts:.0f} counts")
            print(f"波长范围：{frame.wavelengths[0]:.2f} - {frame.wavelengths[-1]:.2f} nm")


if __name__ == "__main__":
    main()
