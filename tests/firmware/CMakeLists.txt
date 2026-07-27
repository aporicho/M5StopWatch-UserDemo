cmake_minimum_required(VERSION 3.16)
project(ble_connection_policy_tests LANGUAGES CXX)

enable_testing()

add_executable(
    ble_connection_policy_test
    ble_connection_policy_test.cpp
    ../../main/apps/app_ble_hid_remote/model/ble_connection_policy.cpp
)
target_compile_features(ble_connection_policy_test PRIVATE cxx_std_17)
target_include_directories(
    ble_connection_policy_test
    PRIVATE ../../main/apps/app_ble_hid_remote/model
)
target_compile_options(ble_connection_policy_test PRIVATE -Wall -Wextra -Werror)

add_test(NAME ble_connection_policy COMMAND ble_connection_policy_test)
