# PyAvaSpec: Pythonic wrapper for Avantes AvaSpec spectrometers

Avantes AvaSpec 光谱仪的 Pythonic 控制库。
执行连接设备、采集光谱、扣除暗谱、计算吸光度等操作。

> **状态：Alpha（0.1.x）。** 核心采集、参考谱、自动曝光、多帧平均与设备诊断已可用；
> 0.x 阶段的公开 API 仍可能调整，破坏性变更会在 GitHub Release 中说明。

## 快速上手

```python
from pyavaspec import Spectrometer

with Spectrometer() as spec:                        # 打开发现的第一个光谱仪设备
    spec.configure(integration_ms=100)              # 只改积分时间，其余参数保持不变
    frame = spec.measure()                          # 采集一帧
    wavelengths, counts = frame.wavelengths, frame.counts  # numpy.float64
    print(frame.peak_wavelength_nm, frame.peak_counts)
```

`Spectrometer()` 默认选择总线上第一个光谱仪；多台设备时传入序列号：`Spectrometer("*********")`。设备对象会在离开 `with` 时自动释放。

`frame.counts` 的单位是 ADU/counts，`frame.saturated` 和 `frame.saturated_mask` 可用于判断是否过曝。

## 安装和依赖

```bash
uv add pyavaspec
# 或
pip install pyavaspec
```

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows x64 |
| Python | >= 3.12 |
| 运行时依赖 | `numpy` |
| 设备驱动 | AvaSoftX，可登录 [My Avantes](https://myavantes.avantes.com/) 下载 |

本库发布的是纯 Python wheel（`py3-none-any`），因此可以在任意平台安装和 import。但连接光谱仪需要 **Windows x64**。在 Linux、macOS 上可以正常导入，调用设备 API 时会抛出 `UnsupportedPlatformError`，不会静默失败。

如果已经安装 AvaSoftX，通常无需额外配置。

本库所有对设备的直接操作均基于 `avaspecx64.dll`。该 DLL 由 Avantes 提供，通常随官方软件 AvaSoftX 一起安装。库会按以下顺序定位它：

1. 调用时传入的 `dll_path`
2. `AVASPEC_DLL` 环境变量
3. AvaSoftX 的注册表条目

理论上支持所有 AvaSpec 系列 USB 设备。

## 典型场景

### 自动积分时间

先把信号调到合适区间

```python
from pyavaspec import Spectrometer, auto_exposure

with Spectrometer() as spec:
    result = auto_exposure(spec, target_fraction=0.7)   # 把峰值调到满量程约 70%
    print(result.integration_ms, result.peak_fraction, result.converged)
```

只调整积分时间，失败时会回滚到调用前的配置。

### 参考谱和暗背景扣除

```python
from pyavaspec import MeasurementSession, Spectrometer

with Spectrometer() as spec:
    session = MeasurementSession(spec)      # 默认 policy="warn"，提示但不阻塞
    session.capture_dark(frames=20)         # 遮光
    session.capture_bright(frames=5)        # 白参考

    m = session.measure()
    print(m.spectrum)                       # 原始谱永远可用
    print(m.corrected)                      # 条件漂移时为 None，原因见 m.status.message
    absorbance = session.absorbance(m)      # 吸光度，也有 transmittance / reflectance
```

参考谱会记录积分时间、平均次数、像素范围、ADC 与平滑条件。条件不一致或参考谱过期时，库不会静默使用。无人值守场景可用 `policy="strict"` 直接抛出异常。

### 高速板载 RAM 采集

```python
with Spectrometer() as spec:
    spec.configure(averages=1)              # RAM 采集要求设备端平均为 1、软件触发
    frames = spec.acquire_to_ram(100)       # 结束后自动恢复原配置
```

### 多设备与共享驱动会话

日常使用 `Spectrometer()` 即可。需要反复枚举设备，或让枚举与采集共享一次驱动初始化时，则使用 `DriverSession`：

```python
from pyavaspec import DriverSession, Spectrometer, list_devices

with DriverSession() as session:
    for device in list_devices(session=session):
        print(device.serial)
    with Spectrometer(session=session) as spec:
        frame = spec.measure()
```

`DriverSession` 持有进程级驱动运行时，`Spectrometer` 持有单台设备句柄。使用会话时，`DriverSession`必须比 `Spectrometer` 活得更久，且不能再同时指定 `dll_path`、`port`。

### 连续采集、IO 和诊断

```python
with Spectrometer() as spec, spec.stream() as stream:
    for frame in stream:
        print(frame.sequence, frame.max)
        if frame.sequence >= 10:
            break
```

`spec.io.digital_out(...)`、`spec.io.board_temperature()`、`device_report(spec)`、`self_test(spec)` 等能力见示例脚本。

## 示例

[`examples/`](https://github.com/E1nzbern/pyavaspec/tree/main/examples) 提供 11 个可直接运行的真机脚本，覆盖单帧采集、保存、自动曝光、连续采集、多帧平均、参考谱、透射比、面向对象的工作流、RAM 批量采集、诊断和 IO、多设备枚举和杂散光抑制等常见场景。

```bash
uv run python examples/01_hello_spectrum.py
uv run python examples/06_transmittance.py --integration 100 --frames 20
```

完整列表和说明见 [examples/README.md](https://github.com/E1nzbern/pyavaspec/blob/main/examples/README.md)。

## 架构

库分为三层，依赖方向自上而下：

- **`pyavaspec.core`**：高层设备控制、数据模型、采集编排与 IO，日常使用的 `Spectrometer` 在这里。
- **`pyavaspec.features`**：参考谱、测量会话、自动曝光、多帧平均和诊断等能力。
- **`pyavaspec._lowlevel`**：`avaspecx64.dll` 的 C-ABI 映射与驱动会话，属于内部模块，不承诺 API 稳定。

## 常见故障

- `DllNotFoundError`：未安装 AvaSoftX、位数不对，或 DLL 不在搜索范围内。
- `DeviceBusyError`：AvaSoftX 或另一个进程仍占用设备，同一时间只允许一个进程激活光谱仪。
- `Measurement.corrected is None`：暗谱条件与当前配置不一致，查看 `status.message` 后重新采集参考谱。

详见 [Troubleshooting](https://github.com/E1nzbern/pyavaspec/blob/main/docs/troubleshooting.md)。

## 许可证与免责声明

本项目以 Apache 2.0 许可发布，详见 [LICENSE](https://github.com/E1nzbern/pyavaspec/blob/main/LICENSE)。

本项目是社区项目，与 Avantes 无隶属、赞助或背书关系。"Avantes"、"AvaSpec"、"AvaSoft"等名称和商标归各自所有者。`avaspecx64.dll` 不在本仓库内，其权利归 Avantes 所有。

使用本库仍需遵守 Avantes 的软件许可。
