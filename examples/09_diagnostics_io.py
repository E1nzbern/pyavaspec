"""诊断、温度和 IO

- ``device_report()``：型号、固件、波长范围、标定能力、板载温度；
- ``self_test()``：测量温度然后采集一帧，判断是否饱和；
- 数字输入端口范围 0-5、模拟输入端口范围 0-7。

参数：

- ``--loopback``：数字回环测试，会把 ``out_pin`` 置高再置低，结束后固定为低电平；
- ``--unsafe-io``：写数字、模拟输出。必须确保引脚未连接或连接的设备处于可安全动作状态！

运行::

    uv run python examples/09_diagnostics_io.py
    uv run python examples/09_diagnostics_io.py --loopback
    uv run python examples/09_diagnostics_io.py --unsafe-io
"""

from __future__ import annotations

import argparse
import json
import time

from pyavaspec import (
    Spectrometer,
    device_report,
    digital_loopback,
    self_test,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="设备诊断和 IO 检查")
    parser.add_argument("--serial", help="设备序列号，只有一台设备时可省略")
    parser.add_argument(
        "--loopback",
        action="store_true",
        help="执行数字回环测试，会短暂改写 out_pin",
    )
    parser.add_argument(
        "--unsafe-io",
        action="store_true",
        help="允许写数字、模拟输出，必须确保引脚未连接或连接的设备处于可安全动作状态！",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with Spectrometer(args.serial) as spec:
        print("=== 设备报告 ===")
        report = device_report(spec)
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))

        print("\n=== 自检 ===")
        result = self_test(spec)
        for check in result.checks:
            if check.ok is None:
                mark = "SKIP"
            elif check.ok:
                mark = "OK  "
            else:
                mark = "FAIL"
            print(f"[{mark}] {check.name}: {check.detail}")
        print("总体：", "通过" if result.ok else "有失败项")

        print("\n=== 只读 IO ===")
        print("数字输入 0-5：", [spec.io.digital_in(pin) for pin in range(6)])
        unconnected = spec.io.UNCONNECTED_SENTINEL
        analog = [spec.io.analog_in(ch) for ch in range(8)]
        shown = ["未连接" if volts >= unconnected - 1e-3 else round(volts, 3) for volts in analog]
        print("模拟输入 0-7 (V)：", shown)
        try:
            print(f"板载温度：{spec.io.board_temperature():.2f} ℃")
        except Exception as exc:
            print(f"板载温度不可用：{exc}")

        if args.loopback:
            print("\n=== 数字回环 ===")
            check = digital_loopback(spec)
            print(f"{check.name}: ok={check.ok}  {check.detail}")
            if check.ok:
                print("提示：部分型号会把 5 号输出状态内部回读到输入，未接外部线也可能显示回环。")
            print("注意：out_pin 现在为低电平；若原本在驱动快门，请自行恢复。")

        if args.unsafe_io:
            print("\n=== 输出测试（--unsafe-io）===")
            input("确认 0 号数字输出未连接或连接的设备处于可安全动作状态！按回车继续...")
            spec.io.digital_out(0, True)
            time.sleep(0.1)
            spec.io.digital_out(0, False)
            print("数字输出 0：置高 100 ms 后已置低")

            spec.io.analog_out(0, 0.0)
            print("模拟输出 0：已设为 0.0 V")

        print("\n完成。")


if __name__ == "__main__":
    main()
