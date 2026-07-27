# Project-local behavioral override for ESP-IDF's esp_hid component.
#
# ESP-IDF 5.5 hard-codes RemoteWake and NormallyConnectable in the NimBLE
# HOGP HID Information characteristic.  This product implements neither, so
# build the upstream component unchanged except for the small wrapper below.
set(upstream "${IDF_PATH}/components/esp_hid")

idf_build_get_property(target IDF_TARGET)
if(${target} STREQUAL "linux")
    return()
endif()

set(srcs
    "${upstream}/src/esp_hidd.c"
    "${upstream}/src/esp_hidh.c"
    "${upstream}/src/esp_hid_common.c"
)

if(CONFIG_BT_ENABLED)
    if(CONFIG_BT_BLUEDROID_ENABLED)
        list(APPEND srcs
            "${upstream}/src/ble_hidd.c"
            "${upstream}/src/ble_hidh.c"
            "${upstream}/src/bt_hidh.c"
            "${upstream}/src/bt_hidd.c"
        )
    endif()
    if(CONFIG_BT_NIMBLE_ENABLED)
        list(APPEND srcs
            "m5_nimble_hidd.c"
            "${upstream}/src/nimble_hidh.c"
        )
    endif()
endif()

idf_component_register(
    SRCS "${srcs}"
    INCLUDE_DIRS "${upstream}/include"
    PRIV_INCLUDE_DIRS "${upstream}/private"
    REQUIRES esp_event bt
)

target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE M5_UPSTREAM_NIMBLE_HIDD="${upstream}/src/nimble_hidd.c"
)
target_compile_options(${COMPONENT_LIB} PRIVATE "-Wno-format")
