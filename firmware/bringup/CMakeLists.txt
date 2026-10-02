cmake_minimum_required(VERSION 3.13)

set(PICO_PLATFORM rp2350-arm-s CACHE STRING "Platform")
set(PICO_BOARD tspico_v3 CACHE STRING "Board type")
list(APPEND PICO_BOARD_HEADER_DIRS ${CMAKE_CURRENT_LIST_DIR}/boards)

include(pico_sdk_import.cmake)

project(tspico_bringup C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

pico_sdk_init()

add_executable(bringup main.c board.c)

target_link_libraries(bringup
	pico_stdlib
	pico_unique_id
	pico_flash
	hardware_adc
	hardware_flash
	hardware_i2c
	hardware_pwm
	hardware_spi
	hardware_uart
)

pico_enable_stdio_usb(bringup 1)
pico_enable_stdio_uart(bringup 0)
pico_add_extra_outputs(bringup)

# USB-serial bridge to the ESP32-C3 (flashing Zimodem, talking to it).
add_executable(esp_bridge esp_bridge.c board.c)

target_link_libraries(esp_bridge
	pico_stdlib
	hardware_i2c
	hardware_uart
)

target_compile_definitions(esp_bridge PRIVATE
	# esptool talks to the ROM loader with DTR deasserted; keep USB output flowing.
	PICO_STDIO_USB_CONNECTION_WITHOUT_DTR=1
	# Zimodem's default speed is 1200, the SDK's reboot-to-BOOTSEL magic rate.
	PICO_STDIO_USB_ENABLE_RESET_VIA_BAUD_RATE=0
	# Drop module output quickly when nothing on the host is reading.
	PICO_STDIO_USB_STDOUT_TIMEOUT_US=20000
	PICO_STDIO_DEFAULT_CRLF=0
)

pico_enable_stdio_usb(esp_bridge 1)
pico_enable_stdio_uart(esp_bridge 0)
pico_add_extra_outputs(esp_bridge)
