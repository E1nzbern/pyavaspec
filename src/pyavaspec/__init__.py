"""pyavaspec - Avantes AvaSpecx 光谱仪控制库

分层结构（依赖自上而下）::

    pyavaspec     # 公共 API
    ├─ core        # 数据模型、设备 API、采集、IO
    ├─ features    # 组合能力，如参考谱、自动曝光
    └─ _lowlevel   # 映射 avaspecx64.dll

示例::

    from pyavaspec import Spectrometer

    with Spectrometer() as spec:
        spec.configure(integration_ms=100, averages=2)
        frame = spec.measure()
        print(frame.peak_wavelength_nm, frame.peak_counts)
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from . import core as core
from . import features as features
from .core import *
from .core import __all__ as _core_all
from .features import *
from .features import __all__ as _features_all

try:
    __version__ = version("pyavaspec")
except PackageNotFoundError:  # 直接从源码目录导入（未安装）时
    __version__ = "0.0.0+unknown"

__all__ = [
    "__version__",
    "core",
    "features",
    *_core_all,
    *_features_all,
]
