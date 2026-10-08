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

# Phase 1 bus shadow test (docs/v3-firmware-port-plan.md): follows every 2068
# memory read without driving the bus. Needs the stock 2068 ROM images.
set(TSPICO_ROM_DIR "$ENV{HOME}/Documents/github/tspico-firmware-build/ROMs" CACHE PATH
	"Directory holding GENUINE-2068-home.bin and GENUINE-2068-exrom.bin")

# Embeds a binary file as `const unsigned char NAME[]` and `const unsigned NAME_len`.
function(embed_binary TARGET NAME FILE)
	if(NOT EXISTS ${FILE})
		message(FATAL_ERROR "${FILE} not found; set TSPICO_ROM_DIR")
	endif()
	set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${FILE})
	file(READ ${FILE} hex HEX)
	string(REGEX REPLACE "([0-9a-f][0-9a-f])" "0x\\1," bytes "${hex}")
	file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/${NAME}.c
		"const unsigned char ${NAME}[] = {${bytes}};\nconst unsigned ${NAME}_len = sizeof ${NAME};\n")
	target_sources(${TARGET} PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/${NAME}.c)
endfunction()

add_executable(bus_shadow bus_shadow.c board.c)
pico_generate_pio_header(bus_shadow ${CMAKE_CURRENT_LIST_DIR}/bus.pio)
embed_binary(bus_shadow rom_home ${TSPICO_ROM_DIR}/GENUINE-2068-home.bin)
embed_binary(bus_shadow rom_exrom ${TSPICO_ROM_DIR}/GENUINE-2068-exrom.bin)

target_link_libraries(bus_shadow
	pico_stdlib
	pico_multicore
	hardware_vreg
	hardware_dma
	hardware_i2c
	hardware_pio
)

# Keeps the C runtime in the lower 256 KB of SRAM; the byte images sit above it.
pico_set_linker_script(bus_shadow ${CMAKE_CURRENT_LIST_DIR}/memmap_bus.ld)
pico_enable_stdio_usb(bus_shadow 1)
pico_enable_stdio_uart(bus_shadow 0)
pico_add_extra_outputs(bus_shadow)

# Bus test, second design: class from the bank-register shadow, early /BE.
add_executable(bus_card bus_card.c board.c)
pico_generate_pio_header(bus_card ${CMAKE_CURRENT_LIST_DIR}/bus_card.pio)
embed_binary(bus_card rom_home ${TSPICO_ROM_DIR}/GENUINE-2068-home.bin)
embed_binary(bus_card rom_exrom ${TSPICO_ROM_DIR}/GENUINE-2068-exrom.bin)

# The TS-Pico ROM (32K: HOME, then the 16K EXROM). By default the newest
# src/rom/TSPICO-NN.ROM on the firmware repo's origin/main, taken with `git
# show`, so the checkout is left alone.
set(TSPICO_FIRMWARE_REPO "$ENV{HOME}/Documents/github/tspico-firmware-build" CACHE PATH
	"The TS-Pico firmware repo, for the TS-Pico ROM")
set(TSPICO_ROM "" CACHE FILEPATH "The TS-Pico ROM image; empty takes the newest TSPICO-NN.ROM from origin/main")
if(TSPICO_ROM)
	set(tspico_rom_file ${TSPICO_ROM})
else()
	execute_process(COMMAND git -C ${TSPICO_FIRMWARE_REPO} ls-tree --name-only origin/main src/rom/
		OUTPUT_VARIABLE rom_list RESULT_VARIABLE git_result)
	string(REGEX MATCHALL "TSPICO-[0-9][0-9]\\.ROM" roms "${rom_list}")
	list(SORT roms)
	list(LENGTH roms n_roms)
	if(NOT git_result EQUAL 0 OR n_roms EQUAL 0)
		message(FATAL_ERROR "no TSPICO-NN.ROM on origin/main in ${TSPICO_FIRMWARE_REPO}; set TSPICO_ROM")
	endif()
	list(GET roms -1 rom_name)
	set(tspico_rom_file ${CMAKE_CURRENT_BINARY_DIR}/${rom_name})
	execute_process(COMMAND git -C ${TSPICO_FIRMWARE_REPO} show origin/main:src/rom/${rom_name}
		OUTPUT_FILE ${tspico_rom_file} RESULT_VARIABLE git_result)
	if(NOT git_result EQUAL 0)
		message(FATAL_ERROR "couldn't take ${rom_name} from ${TSPICO_FIRMWARE_REPO}")
	endif()
	message(STATUS "TS-Pico ROM: ${rom_name} from origin/main")
endif()
embed_binary(bus_card rom_tspico ${tspico_rom_file})
target_link_libraries(bus_card
	pico_stdlib
	pico_multicore
	hardware_dma
	hardware_i2c
	hardware_pio
	hardware_vreg
)
pico_set_linker_script(bus_card ${CMAKE_CURRENT_LIST_DIR}/memmap_bus.ld)
pico_enable_stdio_usb(bus_card 1)
pico_enable_stdio_uart(bus_card 0)
pico_add_extra_outputs(bus_card)
