# 排障指南

先跑一遍环境自检：

```bash
python -c "import pyavaspec; print(pyavaspec.__version__)"
python -c "from pyavaspec import list_devices; print(list_devices())"
```

如果枚举都失败，问题几乎都在 DLL 或驱动侧。

能枚举但打不开，通常是设备被占用。

## DLL 找不到（`DllNotFoundError`）

库按以下顺序定位 DLL：

1. 传给 `Spectrometer(dll_path=...)`、`DriverSession(dll_path=...)` 的路径，可以是 DLL 文件，也可以是 AvaSoftX 安装目录；
2. `AVASPEC_DLL` 环境变量，同样支持文件或目录；
3. 从注册表读取 AvaSoftX 的安装位置。

排查步骤：

- 确认已安装 **AvaSoftX**，而不只是插上了设备；
- 确认系统是 **64 位**，库里加载的是 `avaspecx64.dll`，32 位同名 DLL 不通用；
- 手动搜索：

  ```python
  from pyavaspec._lowlevel._loader import find_dll
  print(find_dll())
  ```

- 仍找不到时显式指定：

  ```bash
  set AVASPEC_DLL=C:\Program Files\Avantes\AvaSoftX\avaspecx64.dll
  ```

  或在 Python 里调用 `Spectrometer(dll_path=r"path\to\avaspecx64.dll")`。

## 非 Windows 平台（`UnsupportedPlatformError`）

本库只支持 Windows x64，因为似乎只有 Windows 平台才有 `avaspecx64.dll`。在 Linux、macOS 上 **可以** `import pyavaspec`，但任何需要 DLL 的调用都会抛 `UnsupportedPlatformError`。

## 找不到设备（`DeviceNotFoundError`）

- 确认没有另一个 Python 脚本、进程正在采集：设备被占用时，驱动可能直接返回空设备列表，表现为 `DeviceNotFoundError` 而不是 `DeviceBusyError`；
- 用 AvaSoftX 确认设备能被官方软件识别；
- USB 设备换口、换线，避免经过扩展坞；
- 刚插拔过设备、或上一个进程刚刚异常退出时，等 1~2 秒再重新枚举：设备列表为空时，`list_devices()` 会自动调用 `AVS_UpdateUSBDevices` 并重试 3 次（间隔 0.5 s）；
- 自动化脚本里可以加一个短暂的轮询，避免设备还在重新枚举时就放弃：

  ```python
  import time
  from pyavaspec import list_devices

  devices = []
  for _ in range(5):
      devices = list_devices()
      if devices:
          break
      time.sleep(1)
  ```

- 如果新进程仍然枚举不到，基本可以判定设备被旧进程残留状态卡住：关闭所有 Python、AvaSoft 进程后拔插一次 USB（或断电重启设备）。

## 设备被占用（`DeviceBusyError`）

同一台光谱仪在同一时间只能被一个进程激活。常见占用者：

- AvaSoftX、AvaSoft 正在运行；
- 上一次 Python 进程异常退出，句柄没释放；
- 同一进程里另一个 `Spectrometer` 已经打开了这台设备（可用 `DriverSession` 复用会话，但设备句柄仍然只能有一个）。

关掉占用程序后重试；仍不行时拔插 USB 或重启电脑。
本库在解释器正常退出时会兜底停止采集并 `Deactivate` 仍打开的 `Spectrometer`，但对 `os._exit()`、任务管理器结束进程、断电这类硬退出无能为力，只能重新插拔设备。

## DLL 已加载（`DllAlreadyLoadedError`）

同一进程内已从某个路径加载过 DLL，又尝试从**另一个路径**加载。统一使用一个 DLL 路径，
或复用已打开的 `DriverSession`。不要在同一个进程里混用不同版本的 DLL。

## 程序没有任何输出就退出

如果连 `print()` 的第一行都没出现就静默退出，通常是 `avaspecx64.dll` 内部的原生崩溃，Python 异常一定会打印 traceback。先用 faulthandler 确认：

```bash
uv run python -X faulthandler -u 你的脚本.py
```

如果看到 `Windows fatal exception: access violation`，或者进程退出码非 0 但没有 Python traceback，排查方向是 USB、驱动而不是本库：

- 拔插设备后等待 Windows 识别到设备，再等 1~2 秒；
- 避免经过扩展坞，直接插主板 USB 口；
- 确认 AvaSoftX、AvaSoft 没有同时运行。

## 采集失败、超时（`MeasurementError`、`MeasurementTimeoutError`）

- 超时后库会先 `StopMeasure`，再随 `with` 退出释放设备句柄。**尽量不要**在采集过程中用 Ctrl+C 连按、关终端或任务管理器强杀，这类硬退出会让设备停留在忙状态；
- 触发配置为外部触发但没接触发源：检查 `Trigger` / `TriggerSource`；
- 平均次数或 RAM 采集参数超出设备能力：会抛 `InvalidParameterError`；
- 连续采集时在流未结束时修改配置：会抛 `MeasurementInProgressError`。
