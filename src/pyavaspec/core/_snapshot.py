"""设备读取协议：把一台已激活设备的描述符读成一份 :class:`DeviceSnapshot`。

C8 抽出的 module：``Spectrometer.open()`` 只负责「激活 → 取快照 → 写缓存 →
下发默认测量配置」，本 module 负责「读哪些字段、按什么顺序、怎么组装」。它只依赖
:class:`~pyavaspec.core._ports.DeviceReadPort` 这个 **seam**，因此可以脱离
``Spectrometer`` 生命周期单独测试——替身只需实现 6 个读取方法。

顺序约束（locality 所在）：

- ``read_parameter`` 先于 ``read_detector_name``：后者要传感器类型当选择子。
- ``read_num_pixels`` 先于 ``read_lambda``：后者要像素数定长度。

与 ``_bridge`` 的分工：``_bridge`` 是纯的「结构体 <-> 模型」转换，不做 I/O；
本 module 消费窄 port 并**组装**控制器（DeviceInfo）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ._bridge import config_from_struct
from ._ports import DeviceReadPort
from .models import DeviceConfig, DeviceIdentity, DeviceInfo

__all__ = ["DeviceSnapshot", "read_config", "read_device"]


@dataclass(frozen=True, slots=True, eq=False)
class DeviceSnapshot:
    """一台已激活设备 ``open()`` 时的只读设备信息快照类"""

    info: DeviceInfo
    config: DeviceConfig
    #: 设备完整的所有波长
    wavelengths: np.ndarray

    @property
    def temperature_fit(self) -> tuple[float, ...] | None:
        """板载温度传感器的标定多项式系数，设备无温度标定时为 ``None``

        未标定的设备 EEPROM 里是全 0 系数，一律按无标定处理
        """
        fits = self.config.temperature_fits
        if not fits or not any(fits[0]):
            return None
        return fits[0]


def read_config(reads: DeviceReadPort) -> DeviceConfig:
    """``AVS_GetParameter`` 读取设备配置"""
    raw = reads.read_parameter_bytes()
    return config_from_struct(reads.read_parameter(), raw)


def read_device(reads: DeviceReadPort, identity: DeviceIdentity) -> DeviceSnapshot:
    """读取已激活设备的完整信息和配置

    ``AVS_GetNumPixels`` 返回光谱仪像素数，配置里的 ``m_Detector.m_NrPixels``
    是传感器像素数。已用 AvaSpec-2048-USB2 实机确认二者一致，波长表也按该值读取。
    """
    version = reads.read_version()
    num_pixels = int(reads.read_num_pixels())
    config = read_config(reads)
    detector_name = reads.read_detector_name(config.sensor_type)

    wavelengths = np.asarray(reads.read_lambda(num_pixels), dtype=np.float64)
    wavelengths.flags.writeable = False

    info = DeviceInfo(
        serial=identity.serial,
        name=identity.name,
        status=identity.status,
        num_pixels=num_pixels,
        sensor_type=config.sensor_type,
        detector_name=detector_name,
        fpga_version=version.fpga,
        firmware_version=version.firmware,
        dll_version=version.dll,
    )
    return DeviceSnapshot(info=info, config=config, wavelengths=wavelengths)
