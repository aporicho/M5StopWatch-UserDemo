# ESP-IDF esp_hid 本地覆盖

ESP-IDF 5.5 在 NimBLE HOGP 实现中固定声明 `RemoteWake` 和
`NormallyConnectable`。本产品没有实现 HID Suspend/Remote Wake，并采用
`NormallyConnectable=false` 的有界重连策略，因此通过一个极小包装复用
上游源码，只把这两个 HID Information flags 设为 `0`。

升级 ESP-IDF 时必须重新核对上游 `nimble_hidd.c`；若上游已提供正式配置
接口，应删除这个覆盖并改用上游 API。
