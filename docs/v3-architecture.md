# TS-Pico v3 architecture (RP2350B)

Status: proposal for review with the firmware maintainers before schematic capture. Supersedes the Pico 2 variant in `archive/v3-pico2-architecture.md`.

## 1. Why RP2350B, and what it buys

The Pico 2 has 26 GPIOs; the feature set now includes WiFi, a 128x96 SPI display, a Kempston joystick port, AY-3-8910 emulation with stereo audio, and direct memory access, on top of the Z80 bus. The RP2350B (QFN-80) exposes 48 GPIOs. Putting it on the board directly ("chip-down") rather than on a module means:

- Every signal that is time-critical gets its own pin. Slow signals go through one input buffer and one output latch on the data bus.
- The per-cycle bank logic stays in PIO, as in the shipped firmware. No bank mux, no bank registers, no comparator, no wait flip-flop: the PIO drives those lines directly.
- 16 MB QSPI flash and 8 MB PSRAM on the board. PSRAM is where TAP/DCK/ROM images get cached instead of the Pico's own flash.
- USB-C stays for firmware updates and the REPL, exactly as the web-updater expects.

Cost: the board carries the MCU support circuit (flash, PSRAM, crystal, regulators, USB, BOOTSEL) and needs a MicroPython board definition. Both are well-trodden; JLCPCB stocks the RP2350B and every support part.

## 2. Block diagram

```
TS2068 edge connector (5 V)
  A0-A15 ◄─► 74LVC245 x2 (Z80 address; DIR out of the card only in DMA mode) ◄─► MA0-MA13 local bus ──┬─► Flash 512K x 8 (TSOP-32)
                                       A14, A15 ──────────────────────────────► RP2350B GP13, GP14      ├─► SRAM  512K x 8 (SOP-32)
  D0-D7  ◄─► 74LVC245 (Z80 data; OE from PIO, DIR = /RD) ◄─────────────────► MD0-MD7 ◄──────────────────┤   MA14-MA18 from RP2350B GP8-GP12
  /MREQ /IORQ /RD /WR /RFSH /M1 /ROSCS /EXROM /BUSAK ─► 74LVC245 (5 V-tolerant in) ─► RP2350B          │   /FCE /SCE from RP2350B GP21, GP22
  /BE /WAIT /BUSRQ /NMI ◄── RP2350B pseudo open-drain (or 74LVC07)                                       │   /MOE /MWE via 74LVC157: Z80 /RD,/WR or RP2350B /MRD,/MWR
  /RESET ◄── 2N7002 ◄── inverter ◄── RP2350B RESET_REQ (pull-down)                                        │
  /MREQ /RD /WR ◄── 74LVC125 (driven only in DMA mode)                                                    │
  EAR ◄── divider ◄── RP2350B TAPE_OUT ;  SPK/TAP ─► divider ─► RP2350B TAPE_IN                          │
  SOUND ─► analog mixer                                                                                   │
                                                                                                          │
RP2350B + W25Q128 (QSPI) + APS6404L PSRAM (CS1 = GP47) + 12 MHz + USB-C + BOOTSEL/RUN                   │
  GP0-GP7  MD0-MD7 (bidir) ◄────────────────────────────────────────────────────────────────────────────┘
  local-bus registers on MD0-MD7 via 74LVC139 (2 select + strobe):
     ALO  74LVC574  MA0-MA7  (Pico/DMA mode, tri-state, /OE = !BUS_OWN)
     AHI  74LVC574  MA8-MA13 + spare (Pico/DMA mode)
     CTL  74LVC574  BUS_OWN, DMA_EN, /BUSRQ, /NMI_OUT, OLED_RST, WIFI_EN, LED, spare
     STAT 74LVC541  joystick x5 (+fire2), /BUSAK, /INT, SD_CD
  SD micro socket on SPI0 (GP36-GP39)
  1.27" 128x96 SSD1351 OLED header on SPI1 (GP40-GP43)
  ESP32-C3 WiFi module running Zimodem on UART0 (GP44, GP45); EN and BOOT (IO9) from CTL so the RP2350 can flash it over USB
  AY emulation on core 1 -> PWM stereo (GP35, GP46) -> RC filter -> op-amp mixer with 2068 SOUND -> 3.5 mm jack
  Kempston DE-9 -> STAT buffer (and PIO-served IN $1F reads on the Z80 side)
```

## 3. Bus behaviour

### 3.1 Z80 mode (BUS_OWN = 0), memory cycles

Local bus address MA0 to MA13 comes from the Z80 through the address transceivers. MA14 to MA18 are driven by PIO on every /MREQ cycle, with the same rule the shipped `sel_bank` / `set_ctrl` state machines apply today:

| /ROSCS | /EXROM | Z80 A15,A14 and /RD | Class | MA14, MA15 | MA16-18 | /FCE or /SCE | /BE |
|---|---|---|---|---|---|---|---|
| low | x | x | DOCK | copy of Z80 A14, A15 | DCK slot | DCK device | asserted |
| high | low | x | EXROM | MA14 = 1, MA15 = ROM half | ROM slot | ROM device | asserted |
| high | high | A15 = A14 = 0, /RD low | HOME ROM | MA14 = 0, MA15 = ROM half | ROM slot | ROM device | asserted |
| otherwise | | | none | | | released | released |

HOME is the first 16 KB of the 32 KB ROM slot and EXROM the second, as the shipped firmware does (`A14_B` = 0 for HOME, 1 for EXROM). The PIO sees A14, A15, /RD, /ROSCS, /EXROM and /MREQ directly, so the old hardware-decoded `/RDROM` signal is no longer needed. A 74LVC157 pass-through for MA14/MA15 in DOCK mode is an option if PIO latency for the copy turns out to matter; budget in section 7 says it does not.

/MOE follows Z80 /RD and /MWE follows Z80 /WR through the 74LVC157 (select = BUS_OWN), so the Z80 reads and writes both flash and SRAM exactly as today, including the SST39SF040-style command sequences the ROM update TAPs use.

The Z80 data transceiver is enabled by PIO for every cycle the card serves (memory hit or I/O hit); direction follows /RD in hardware.

### 3.2 I/O cycles: all decode in PIO

A hardware block-decode strobe is not needed. The PIO waits for /IORQ (gated with /M1 in a single gate so interrupt-acknowledge cycles never trigger), samples A0 to A7 from MA0 to MA7 (the Z80 address is already on the local bus) plus A14, A15, and classifies:

| Port | Function | Notes |
|---|---|---|
| $0E / $0F | TS-Pico data / status | Legacy pair; current ROMs use these |
| $1C / $1D / $1E | TS-Pico data / command / memory-control | Firmware wishlist layout; optional |
| $1F | Kempston joystick | Answered by PIO from a joystick byte the main loop refreshes from STAT every 1 to 2 ms |
| $FFFD / $BFFD | AY-3-8910 register select / data (Spectrum 128 layout, A15,A14 decoded) | Emulated PSG. Low byte $FD does not collide with the 2068's own $F5/$F6 PSG |
| $73 / $77 | Intel 8251 USART data / status (TS2050 modem layout) | Emulated in the RP2350 as in the TS-2050-Wifi project, bridged to the ESP32-C3 running Zimodem, so existing 2068 terminal software sees a TS2050 with a Hayes modem behind it |
| anything else | ignored | |

Which pairs are enabled is a firmware setting, so the port-pair jumper is gone. /WAIT is asserted by PIO side-set as soon as a served I/O read is detected and released once data is on the bus, so blocking pulls become safe; for writes the PIO captures the byte and clears /WAIT immediately. Whether to assert /WAIT at all is a firmware flag. Timing margins are in section 7.

### 3.3 Pico mode (BUS_OWN = 1): direct memory access to the card's own memories

Set BUS_OWN in CTL. The Z80 address transceivers tri-state, ALO/AHI drive MA0 to MA13, GP8 to GP12 drive MA14 to MA18 under software control, /FCE and /SCE come from GP21/GP22, and /MRD, /MWR go through the 74LVC157 to /MOE, /MWE.

Read: write ALO, AHI; set MA14-18 and chip select; pulse /MRD; sample GP0-GP7. Write: same with GP0-GP7 as outputs and /MWR. A byte in about 100 ns from C; flash programming runs the SST39SF040 JEDEC sequence from the Pico. Entry is safe while the 2068 is in reset or after a /BUSRQ//BUSAK grant.

### 3.4 DMA mode (BUS_OWN = 1, DMA_EN = 1): access to the 2068's own memory

Same as Pico mode, plus: the Z80 address transceivers turn around and drive the latched address onto the Z80 bus, the data transceiver is enabled outward for writes, and a 74LVC125 drives /MREQ, /RD, /WR from the Pico (/MREQ derived as /MRD AND /MWR in a gate). Only ever after /BUSAK is seen in STAT. This is what makes snapshot load/save (.SNA/.Z80), screen capture over WiFi, and memory pokes possible with no ROM support. The SCLD's DRAM timing during bus grant must be validated on the prototype before the feature is relied on; the hardware cost is one chip, so it is included regardless.

## 4. Registers on the local data bus

Selected by 74LVC139 (REG_SEL0, REG_SEL1, /REG_STB).

| Sel | Name | Chip | Bits |
|---|---|---|---|
| 0 | ALO (write) | 74LVC574, tri-state | MA0-MA7 for Pico/DMA mode |
| 1 | AHI (write) | 74LVC574, tri-state | MA8-MA13, 2 spare |
| 2 | CTL (write) | 74LVC273 (has /MR, cleared by the power-on RC) | 0 BUS_OWN, 1 DMA_EN, 2 /BUSRQ, 3 /NMI_OUT, 4 OLED_RST, 5 WIFI_EN, 6 LED, 7 WIFI_BOOT (ESP32-C3 IO9, low = download mode) |
| 3 | STAT (read) | 74LVC541 | 0-4 joystick U/D/L/R/F, 5 fire 2, 6 /BUSAK, 7 SD card detect (or /INT) |

CTL must power up with BUS_OWN = DMA_EN = 0 and /BUSRQ, /NMI_OUT inactive. Use a 74LVC273 (has /MR) tied to the power-on-reset RC.

## 5. Reset, buttons, power

- RESET_REQ (GPIO, 10k pull-down) into a single-gate inverter and 2N7002 pulling 2068 /RESET low. Pico booting or absent: 2068 held in reset. Pico ready: drive high. Pico can pulse it low to reset the 2068. Same behaviour as the 555 today, under firmware control.
- TS Reset and NMI buttons wired to the bus lines directly as today; NMI state is also visible to the PIO/STAT if wanted. Pico RUN and BOOTSEL buttons on the board.
- Power: the 2068's 5 V rail comes from a 78S40 switching regulator rated 200 mA to 1 A in total, most of which the 2068 itself uses; the v2.2 card drew roughly 100 to 150 mA. The v3 card budget is about 250 mA average (RP2350B and PSRAM about 100 mA, memories and logic about 40 mA, OLED up to 60 mA, SD up to 100 mA on writes) plus ESP32-C3 radio bursts of up to about 350 mA at 3.3 V for a few ms when transmitting (datasheet typical: 802.11b at 21 dBm 350 mA, 802.11g 285 mA, receive 84 mA, modem-sleep about 20 mA). Design: the card takes +5 V only from edge pin B4; the expansion bus it plugs into chooses between the 2068 rail and an external barrel supply. USB-C VBUS is not connected to the 5 V rail in either direction (the port is a data link to the PC; VBUS may feed a detect divider only). 3.3 V LDO for logic and a separate 3.3 V LDO for the ESP32 module, 2 x 220 uF bulk on the 5 V input and 100 uF at the module. Firmware keeps the radio in modem-sleep unless a network feature is active.

## 6. GPIO map (RP2350B, 48 GPIO)

Grouped for PIO contiguity. Pins marked (FT) are 5 V-tolerant digital pins on the RP2350 while IOVDD is present; the design does not rely on this, every Z80-facing line goes through a 74LVC245 or a divider.

| GPIO | Signal | Dir | Notes |
|---|---|---|---|
| 0-7 | MD0-MD7 | bidir | Local data bus. PIO in/out base. |
| 8-12 | MA14-MA18 | out | Bank bits (PIO in Z80 mode, GPIO in Pico mode). |
| 13, 14 | Z80 A14, A15 | in | From the address transceiver. |
| 15 | /MREQ_V | in | /MREQ gated with /RFSH (one gate). |
| 16 | /IORQ_V | in | /IORQ gated with /M1 (one gate). |
| 17, 18 | /RD, /WR | in | |
| 19, 20 | /ROSCS, /EXROM | in | GP15-GP20 contiguous for `in pins`. |
| 21, 22 | /FCE, /SCE | out | PIO side-set pair. |
| 23 | DATA_OE | out | Z80 data transceiver enable (PIO side-set). |
| 24 | /WAIT | out (pseudo open-drain) | PIO side-set. |
| 25 | /BE | out (pseudo open-drain) | PIO set. |
| 26, 27 | REG_SEL0, REG_SEL1 | out | 74LVC139 select. |
| 28 | /REG_STB | out | |
| 29 | /MRD | out | Pico/DMA read strobe. |
| 30 | /MWR | out | Pico/DMA write strobe. |
| 31 | RESET_REQ | out | Pull-down. |
| 32 | TAPE_OUT | out | To 2068 EAR via divider (PIO-timed TZX/TAP playback). |
| 33 | TAPE_IN | in | From 2068 SPK/TAP via divider (capture SAVEs). |
| 34 | /INT | in | 2068 frame interrupt, for AY timing sync. |
| 35 | AUDIO_R (PWM) | out | |
| 36-39 | SD MISO, CS, SCK, MOSI | | SPI0 pin group. |
| 40-43 | OLED DC, CS, SCK, MOSI | | SPI1 pin group. OLED reset from CTL. |
| 44, 45 | WIFI_TX, WIFI_RX | | UART to the ESP32-C3's UART0 (C3 GPIO20/21). Zimodem supports XON/XOFF, so RTS/CTS pins are not routed; WIFI_EN and WIFI_BOOT from CTL. |
| 46 | AUDIO_L (PWM) | out | |
| 47 | PSRAM CS1 | | QMI CS1n (options are GP0, 8, 19, 47). |

Net: all 48 used, none spare. Everything slow lives in CTL/STAT, so adding a feature later costs a register bit, not a pin.

## 7. Timing budget (2068 Z80 at 3.53 MHz, T = 283 ns)

- Memory read, opcode fetch (tightest): /MREQ low at T1 falling edge, data sampled at T3 rising edge: about 425 ns minus 35 ns setup. PIO decision (wait on /MREQ, jump on /ROSCS, copy or output 5 bits, set chip select) is 5 to 7 PIO cycles at 150 MHz, under 50 ns, plus 10 ns transceiver, plus 70 ns flash access: about 130 ns. Margin over 250 ns.
- Memory write: /MWE mirrors Z80 /WR through the 74LVC157 (about 5 ns), so write timing is the Z80's own. Chip select from PIO is asserted well before /WR falls.
- I/O read: /IORQ low at T2 rising edge, one TW always inserted, data sampled at T3 falling edge: about 700 ns. PIO address classification about 10 cycles (67 ns) then data out, or /WAIT asserted within about 50 ns, well before the TW falling-edge sample at about 425 ns.
- Kempston read: the joystick lives in STAT, which the PIO cannot read inside a Z80 cycle, so the main loop refreshes the joystick byte into the port state machine's scratch register every 1 to 2 ms and the PIO answers $1F from there. Latency equals the port-read path above; a 2 ms poll is far below what games notice.
- Pico/DMA mode: not Z80-timed.

## 8. Chip list (excluding MCU support and analog)

| Qty | Part | Role |
|---|---|---|
| 2 | 74LVC245 | Z80 A0-A15, bidirectional for DMA mode |
| 1 | 74LVC245 | Z80 D0-D7 |
| 1 | 74LVC245 | Z80 control inputs (8), 5 V tolerant |
| 2 | 74LVC574 | ALO, AHI |
| 1 | 74LVC273 | CTL (with clear) |
| 1 | 74LVC541 | STAT |
| 1 | 74LVC139 | Register select |
| 1 | 74LVC157 | /MOE, /MWE source select |
| 1 | 74LVC125 | DMA drivers for /MREQ, /RD, /WR |
| 1 | 74LVC08 or 3 single gates | /MREQ&/RFSH, /IORQ&/M1, /MRD&/MWR |
| 1 | 74LVC07 (optional) | Open-drain drivers if pseudo open-drain GPIO is not wanted |
| 1 | 2N7002 + single-gate inverter | /RESET driver |

12 logic packages, down from about 20 in the Pico 2 plan and all 74LVC (3.3 V, 5 V-tolerant inputs). Memories run on the 3.3 V local bus: AS6C4008 (already 2.7 to 5.5 V) and a 3.3 V flash such as SST39VF040 or MX29LV040C in TSOP-32. If a 3.3 V flash is not stockable at JLC at order time, keep the 5 V SST39SF040 and run the local bus at 5 V with 74AHCT parts; the RP2350 outputs drive TTL thresholds fine and its FT inputs read 5 V.

MCU support: RP2350B, W25Q128JV (16 MB), APS6404L-3SQR (8 MB PSRAM), 12 MHz crystal, 3.3 V LDO, USB-C, BOOTSEL and RUN buttons, SWD test pads.

WiFi: ESP32-C3-MINI-1 (4 MB flash) running Zimodem, which has an explicit ESP32-C3 build target (`ARDUINO_ESP32C3_DEV`, "Esp32C3 4MB Dev Board" in `zimodem.ino`; that target disables the SD shell, which the card does not need). Zimodem talks over the C3's UART0 with its own Hayes AT command set and provides telnet, SSH, PPP/SLIP, FTP, IRC and HTTP fetches, so the RP2350 does not need an AT library of its own; it bridges the emulated 8251 at $73/$77 to that UART and can use the same link for its own downloads. The C3's modem-status pins that Zimodem drives (DCD on GPIO8, RI 1, DSR 4, DTR 5, RTS/CTS 2/3) are not routed; the 8251 emulation reports carrier from Zimodem's CONNECT/NO CARRIER responses. Programming the C3: the RP2350 acts as a USB-to-UART bridge with EN and IO9 driven from CTL, so Zimodem is flashed through the card's USB-C with esptool. Check before layout: on the C3 the Arduino `Serial` object can be the USB CDC instead of UART0 depending on the core's "USB CDC on boot" option; Zimodem's `HWSerial` must be on UART0 (GPIO20/21) for this wiring. Audio: dual op-amp, RC filters, 3.5 mm jack. Joystick: DE-9 with ESD array. Display: 7-pin header for the Waveshare 1.27" 128x96 SSD1351 module.

## 9. The part-count endgame: memory emulated in the RP2350B

Worth stating because the question was asked. With the RP2350B fast enough to serve a Z80 bus directly, the flash, SRAM, ALO/AHI latches, 74LVC157 and bank pins disappear: the RP2350B becomes the memory. Z80 A0 to A15 and D0 to D7 go through three 74LVC245s into GPIO, PIO captures the address on /MREQ and a DMA channel fetches the byte from internal SRAM (520 KB holds an active DCK plus ROM slot plus buffers; PSRAM and QSPI flash hold the library) and PIO puts it on the bus. RP2040-class ROM emulators do this in 90 to 150 ns, inside the 390 ns fetch budget. Z80 writes land in the emulated memory and the Pico persists them, so the ROM-update TAPs still work by intercepting the flash command sequence in software.

What it costs: the firmware becomes C on core 1 with PIO and DMA (the AY emulation needs that anyway), and the flash/SRAM bank model the team has documented becomes a software abstraction rather than chips. Glue drops to about 6 packages. GPIO use is similar to section 6 (16 address in instead of 5 bank out plus 14 shared).

Recommendation: build v3 as sections 2 to 8 (real memories, PIO bank logic, direct Pico access) because it keeps the shipped firmware model and every tool the group has. Before v3 layout is final, spend a weekend with a Pico 2 on a breadboard against a 2068 to measure the emulated-memory latency; if it holds, v4 can drop the memory subsystem.

## 10. Other features enabled by the pin budget (pick deliberately)

Included in the map above: PSRAM cache, tape EAR out and SPK/TAP in (TZX and custom loaders, capture of SAVEs), /INT for AY sync, DMA to the 2068 for snapshots, WiFi with BLE.

Cheap to add later through CTL/STAT bits or existing buses: I2C RTC (or NTP over WiFi with none), second joystick on STAT spare bits, activity LEDs, an I2C/Qwiic header, a UART header for the REPL.

Not recommended on this card: video (the PicoVideo project covers it), USB host (needs a second connector and 5 V sourcing; a BLE gamepad through the ESP32 gets the same result).

## 11. Open questions for review

1. Confirm the DOCK/EXROM/HOME rule table in 3.1 against the current `set_ctrl`, including the DCK "device none" case.
2. Enable $1C to $1E in addition to $0E/$0F from the start, or keep only the legacy pair until the ROM is updated?
3. AY-3-8910 at the Spectrum 128 ports, or a TS-specific port? Stereo mixing scheme (ABC vs ACB)?
4. (Resolved) Power from edge +5 V only; USB is data only; no +15 V buck.
5. (Resolved) Chip-down RP2350B.
