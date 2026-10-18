"""avaspecx64.h 的尺寸常量"""

# 字符串长度
AVS_SERIAL_LEN = 10  # AvsIdentityType.SerialNumber
USER_ID_LEN = 64  # AvsIdentityType.UserFriendlyName / DeviceConfigType.m_aUserFriendlyId
VERSION_LEN = 16  # AVS_GetVersionInfo 的三个版本字符串

# 缓冲区尺寸
MAX_PIXELS = 4096  # AVS_GetLambda / GetScopeData 等的最大像素数
DEVICE_CONFIG_LEN = 63484  # DeviceConfigType（EEPROM 镜像）固定字节数
