import ctypes
from typing import Any

import numpy as np

from ._constants import MAX_PIXELS


def _cstr(raw: Any) -> str:
    """C 字符串缓冲区解码为 str"""
    return bytes(raw).split(b"\0", 1)[0].decode("ascii", errors="replace")


def _as_double_array(values: Any, size: int = MAX_PIXELS):
    """一维序列转 `double[size]` ctypes 数组，超出部分截断"""
    src = np.asarray(values, dtype=np.float64).ravel()
    arr = (ctypes.c_double * size)()
    for i in range(min(src.size, size)):
        arr[i] = float(src[i])
    return arr


def _as_u32_array(values: Any, size: int = MAX_PIXELS):
    """一维序列转 `uint32[size]` ctypes 数组，超出部分截断"""
    src = np.asarray(values, dtype=np.uint32).ravel()
    arr = (ctypes.c_uint32 * size)()
    for i in range(min(src.size, size)):
        arr[i] = int(src[i])
    return arr
