# benchprog.py - write the TS-Pico v2.5 flash from the Pico, card out of the 2068.
# DRAFT, untested on hardware (the board has not been built). MicroPython on the Pico.
#
# Setup: card OUT of the computer, SW4 in PROG, USB to the Pico. Copy the 512K image
# (flash/README.md in tspico-firmware-build: tools/build-flash.py build) to the Pico as
# /flash.rom, then:  import benchprog; benchprog.program("/flash.rom")
# Afterwards put SW4 back to RUN before the card goes into the 2068.
#
# Hardware (hardware-v2.5, sheet "Bench Programming"): three 74HCT595s, SER = GP3,
# SRCLK = GP2 (SPI0 TX/SCK, shared with the SD card and Pico data bus D1_L/D0_L),
# RCLK = GP28 (SD_CS). Shifted MSB first, 3 bytes: [D7..D0] [nWE nRD A13..A8] [A7..A0].
# A14/A15 go through U8 (GP22 = A14_B, GP15 = A15_B; /ROSCS is pulled high off the bus),
# A16-A18 = GP16-GP18, flash /CE = GP19, SRAM /CE = GP20, U6 /OE = GP12.
# Read-back: data bits shifted out high, /RD low, U6 enabled (its DIR is A->B with /IORQ
# pulled high), byte read on GP2-GP9.
import time
from machine import Pin, SPI

RCLK = Pin(28, Pin.OUT, value=1)    # also SD /CS: idles high so the card stays deselected
FCE = Pin(19, Pin.OUT, value=1)
SCE = Pin(20, Pin.OUT, value=1)
U6EN = Pin(12, Pin.OUT, value=1)
A14, A15 = Pin(22, Pin.OUT, value=0), Pin(15, Pin.OUT, value=0)
AHI = [Pin(n, Pin.OUT, value=0) for n in (16, 17, 18)]
NRD, NWE = 0x40, 0x80
_buf = bytearray(3)
_spi = None


def _spi_on():
    global _spi
    _spi = SPI(0, baudrate=8_000_000, polarity=0, phase=0, sck=Pin(2), mosi=Pin(3), miso=Pin(4))


def _latch(addr, data, ctl):
    _buf[0] = data
    _buf[1] = ((addr >> 8) & 0x3F) | ctl
    _buf[2] = addr & 0xFF
    A14.value((addr >> 14) & 1)
    A15.value((addr >> 15) & 1)
    for i, p in enumerate(AHI):
        p.value((addr >> (16 + i)) & 1)
    _spi.write(_buf)
    RCLK.value(0)
    RCLK.value(1)                      # the 595s latch on the rising edge


def _write(addr, data):
    _latch(addr, data, NRD | NWE)      # address and data set up, /OE and /WE high
    _latch(addr, data, NRD)            # /WE low
    _latch(addr, data, NRD | NWE)      # /WE high: the flash latches the byte


def _cmd(*pairs):
    for a, d in pairs:
        _write(a, d)


def read(addr):
    _latch(addr, 0xFF, NWE)            # /RD low, data bits high (the 4.7k lets the flash win)
    FCE.value(0)
    _spi.deinit()
    pins = [Pin(n, Pin.IN) for n in range(2, 10)]
    U6EN.value(0)
    v = sum(p.value() << i for i, p in enumerate(pins))
    U6EN.value(1)
    FCE.value(1)
    _spi_on()
    return v


def chip_erase():
    FCE.value(0)
    _cmd((0x5555, 0xAA), (0x2AAA, 0x55), (0x5555, 0x80), (0x5555, 0xAA), (0x2AAA, 0x55), (0x5555, 0x10))
    FCE.value(1)
    time.sleep_ms(150)                 # SST39SF040 chip erase: 100 ms max


def program(path="/flash.rom", verify=True):
    _spi_on()
    SCE.value(1)
    U6EN.value(1)
    chip_erase()
    t0 = time.ticks_ms()
    with open(path, "rb") as f:
        addr = 0
        while True:
            block = f.read(4096)
            if not block:
                break
            FCE.value(0)
            for b in block:
                if b != 0xFF:          # erased bytes are already FF
                    _cmd((0x5555, 0xAA), (0x2AAA, 0x55), (0x5555, 0xA0), (addr, b))
                    time.sleep_us(20)  # byte program: 20 us max
                addr += 1
            FCE.value(1)
            if addr % 65536 == 0:
                print("written", addr // 1024, "K")
    print("programmed", addr, "bytes in", time.ticks_diff(time.ticks_ms(), t0) // 1000, "s")
    if verify:
        bad = 0
        with open(path, "rb") as f:
            addr = 0
            while True:
                block = f.read(4096)
                if not block:
                    break
                for b in block:
                    if read(addr) != b:
                        bad += 1
                        if bad <= 10:
                            print("mismatch at %05X" % addr)
                    addr += 1
        print("verify:", "OK" if not bad else "%d bad bytes" % bad)
