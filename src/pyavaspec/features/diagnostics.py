"""设备自检

- :func:`device_report`：只读汇总（版本、波长范围、标定项是否存在、板载温度）；
- :func:`self_test`：只读检查 + 采集一帧；
- :func:`digital_loopback`：显式的 DO→DI 回环检查（**有副作用**，会改写数字输出，
  所以不放进 :func:`self_test` 的默认流程）。
"""

from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ._device import DeviceAccess

__all__ = [
    "CheckResult",
    "DeviceReport",
    "SelfTestReport",
    "device_report",
    "digital_loopback",
    "self_test",
]


@dataclass(frozen=True, slots=True)
class DeviceReport:
    """设备的只读能力数据类"""

    serial: str
    name: str
    num_pixels: int
    detector_name: str
    sensor_type: int
    fpga_version: str
    firmware_version: str
    dll_version: str
    #: 设备波长标定描述的全量范围，与像素窗口无关
    wavelength_range_nm: tuple[float, float]
    #: 当前测量像素窗口对应的波长范围
    measurement_range_nm: tuple[float, float]
    has_spectrum_correction: bool
    has_irradiance_calibration: bool
    has_reflectance_calibration: bool
    nonlinearity_enabled: bool
    tec_enabled: bool
    tec_setpoint: float
    has_temperature_fit: bool
    board_temperature_c: float | None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["wavelength_range_nm"] = list(self.wavelength_range_nm)
        data["measurement_range_nm"] = list(self.measurement_range_nm)
        return data


def _bounds(values: np.ndarray) -> tuple[float, float]:
    """波长数组的首尾值，空数组则返回报"""
    if not values.size:
        return (float("nan"), float("nan"))
    return (float(values[0]), float(values[-1]))


def device_report(device: DeviceAccess) -> DeviceReport:
    """汇总设备信息、配置和板载温度"""
    info = device.info
    config = device.config
    full = np.asarray(device.wavelengths)
    full_range = _bounds(full)
    cfg = device.measurement_config
    window = full[int(cfg.start_pixel) : int(cfg.stop_pixel) + 1]
    measurement_range = _bounds(window)
    try:
        temperature: float | None = float(device.io.board_temperature())
    except Exception:
        temperature = None
    fits = config.temperature_fits
    return DeviceReport(
        serial=info.serial,
        name=info.name,
        num_pixels=int(info.num_pixels),
        detector_name=info.detector_name,
        sensor_type=int(info.sensor_type),
        fpga_version=info.fpga_version,
        firmware_version=info.firmware_version,
        dll_version=info.dll_version,
        wavelength_range_nm=full_range,
        measurement_range_nm=measurement_range,
        has_spectrum_correction=bool(config.spectrum_correction_present),
        has_irradiance_calibration=bool(config.irradiance_calibration_present),
        has_reflectance_calibration=bool(config.reflectance_calibration_present),
        nonlinearity_enabled=bool(config.nonlinearity_enabled),
        tec_enabled=bool(config.tec_enabled),
        tec_setpoint=float(config.tec_setpoint),
        has_temperature_fit=bool(fits and any(fits[0])),
        board_temperature_c=temperature,
    )


@dataclass(frozen=True, slots=True)
class CheckResult:
    """
    单项检查结果

    ``ok=None`` 表示跳过或硬件不支持
    """

    name: str
    ok: bool | None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SelfTestReport:
    """自检结果集合"""

    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        """所有项目成功"""
        return all(check.ok is not False for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [asdict(check) for check in self.checks]}


def self_test(
    device: DeviceAccess,
    *,
    timeout_s: float | None = None,
    measure: bool = True,
) -> SelfTestReport:
    """
    执行自检，可选采集一帧

    - 板载温度是否可读
    - 当前配置下采集一帧，报告峰值判断是否饱和
    """
    checks: list[CheckResult] = []

    try:
        temperature = float(device.io.board_temperature())
        checks.append(CheckResult("board_temperature", True, f"{temperature:.2f} ℃"))
    except Exception as exc:
        checks.append(CheckResult("board_temperature", None, f"不可读：{exc}"))

    if measure:
        try:
            frame = device.measure(timeout_s=timeout_s, saturated_mask=True)
            saturated = frame.any_pixel_saturated
            checks.append(
                CheckResult(
                    "measure",
                    not saturated,
                    f"峰值 {frame.peak_counts:.0f} @ {frame.peak_wavelength_nm:.2f} nm"
                    + ("（饱和）" if saturated else ""),
                )
            )
        except Exception as exc:
            checks.append(CheckResult("measure", False, f"采集失败：{exc}"))

    return SelfTestReport(tuple(checks))


def digital_loopback(
    device: DeviceAccess,
    *,
    out_pin: int = 5,
    in_pin: int = 5,
) -> CheckResult:
    """把 ``out_pin`` 置高再读 ``in_pin``，检查是否存在内部回环

    部分型号会把输出状态直接回读到输入，即使没有外部接线，同引脚也会返回 ``True``；
    因此 ``ok=True`` 只能说明读到了高电平，不能证明外部短接。
    """
    name = f"digital_loopback({out_pin}->{in_pin})"
    try:
        device.io.digital_out(out_pin, True)
        high = device.io.digital_in(in_pin)
    except Exception as exc:
        return CheckResult(name, False, f"IO 操作失败：{exc}")
    finally:
        # 读失败也必须复位，否则引脚会停在 HIGH
        with contextlib.suppress(Exception):
            device.io.digital_out(out_pin, False)
    if high:
        return CheckResult(name, True, f"检测到回环（{out_pin} 号引脚已置低）")
    return CheckResult(
        name,
        None,
        f"未检出回环（{out_pin} 号引脚已置低；取决于机型接线，非故障）",
    )
