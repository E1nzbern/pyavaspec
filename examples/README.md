# 示例

## 运行

```bash
uv run python examples/01_hello_spectrum.py
uv run python examples/03_auto_exposure.py --target 0.6
uv run python examples/06_transmittance.py --integration 100 --frames 20
```

输出文件将统一存储至 `examples/output/`。

## 列表

| 文件                                                   | 内容                                      | 需要人工操作     |
|--------------------------------------------------------|-------------------------------------------|------------------|
| [01_hello_spectrum.py](01_hello_spectrum.py)           | 打开设备、读信息、配置、采集一帧          | 无               |
| [02_save_and_load.py](02_save_and_load.py)             | 保存 CSV、JSON、NPZ                       | 无               |
| [03_auto_exposure.py](03_auto_exposure.py)             | 自动搜索积分时间并查看搜索过程            | 无               |
| [04_stream.py](04_stream.py)                           | 连续采集、实时帧率、Ctrl+C 退出           | 无               |
| [05_averaging.py](05_averaging.py)                     | 比较多帧平均前后的噪声                    | 无               |
| [06_transmittance.py](06_transmittance.py)             | 暗谱、亮谱、透射比、吸光度、参考谱        | 遮光、参考、样品 |
| [07_measurement_session.py](07_measurement_session.py) | `MeasurementSession` 组织参考谱和批量样品 | 遮光、参考、样品 |
| [08_ram_batch.py](08_ram_batch.py)                     | 板载 RAM 高速批量采集并保存               | 无               |
| [09_diagnostics_io.py](09_diagnostics_io.py)           | 设备报告、自检、温度、数字和模拟 IO       | 可选确认         |
| [10_driver_session.py](10_driver_session.py)           | 枚举设备、查看状态、共享 `DriverSession`  | 无               |
| [11_stray_light.py](11_stray_light.py)                 | 杂散光抑制前后对比                        | 无               |
