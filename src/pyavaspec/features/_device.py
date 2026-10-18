"""features 用到的最小 API"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from ..core.models import DeviceConfig, DeviceInfo, MeasurementConfig, Spectrum

__all__ = ["DeviceAccess", "DeviceIOPort"]


class DeviceIOPort(Protocol):
    """features 诊断用到的数字 IO 和板载温度 API"""

    def digital_in(self, pin: int) -> bool:
        """读数字输入电平"""
        ...

    def digital_out(self, pin: int, value: bool) -> None:
        """设置数字输出电平"""
        ...

    def board_temperature(self, channel: int = 0) -> float:
        """板载温度，℃"""
        ...


class DeviceAccess(Protocol):
    """features 组合能力用到的最小 API"""

    @property
    def measurement_config(self) -> MeasurementConfig:
        """当前生效的测量配置"""
        ...

    @property
    def info(self) -> DeviceInfo:
        """已激活设备信息"""
        ...

    @property
    def config(self) -> DeviceConfig:
        """设备 EEPROM 只读配置"""
        ...

    @property
    def wavelengths(self) -> np.ndarray:
        """设备全量波长，与像素窗口无关，单位 nm"""
        ...

    @property
    def io(self) -> DeviceIOPort:
        """数字 IO 和板载温度"""
        ...

    def configure(
        self,
        *,
        integration_ms: float | None = None,
        averages: int | None = None,
    ) -> MeasurementConfig:
        """下发部分测量参数，返回实际生效的配置"""
        ...

    def measure(
        self,
        *,
        timeout_s: float | None = None,
        raw: bool = False,
        saturated_mask: bool = False,
    ) -> Spectrum:
        """采集一帧光谱"""
        ...
