# TS-Pico v3 architecture (RP2350B, emulated memory)

Status: proposal for review with the firmware maintainers; the interface and local-bus sheets are drawn from it. Supersedes the Pico 2 variant in `archive/v3-pico2-architecture.md` and the earlier RP2350B variant with real flash and SRAM.

## 1. Summary

The card is an RP2350B on the TS2068 rear connector. The RP2350B serves the card's memory itself: DCK and ROM images live in its internal SRAM while active, and PIO plus DMA answer Z80 memory cycles with no CPU involvement. There is no parallel flash or SRAM chip. Images are files on the RP2350's own 16 MB QSPI flash (present without an SD card) or on the SD card, cached through 8 MB of PSRAM, and a slot map file replaces the old fixed flash banks.

Everything between the Z80 bus and the RP2350B travels over one 8-bit local bus, MD0 to MD7: the Z80 address (in two bytes through a pair of muxes), the Z80 data (through a transceiver), and the card's four registers. That is what keeps the design inside 48 GPIOs with room to spare.

Other functions: Z80 I/O port decode entirely in PIO ($0E/$0F and the wishlist ports, Kempston at $1F, an emulated AY-3-8910 at the Spectrum 128 ports, an emulated Intel 8251 at $73/$77 bridged to an ESP32-C3 running Zimodem), /WAIT generation, a Pico-controlled 2068 reset,  tape EAR out and SPK/TAP in, a 128x96 SPI OLED, a DE-9 joystick, and stereo audio mixed with the 2068 SOUND line.

## 2. Block diagram

```
TS2068 edge connector (5 V)                                        RP2350B (3.3 V)
  A0-A7  -> 74LVC245 (/OE = nAEN_LO) --+
  A8-A15 -> 74LVC245 (/OE = nAEN_HI) --+--> MD0-MD7 <--> GP0-GP7     nAEN_LO, nAEN_HI <-- GP8, GP9
  D0-D7  <-> 74LVC245 (DIR = /RD, /OE = nDATA_OE) <--> MD0-MD7
  control -> 74LVC245 -> nROSCS_L nEXROM_L nINT_L Z80_A14 Z80_A15 TAPE_IN nBUSAK_L -> GPIO / expander
  /MREQ, /IORQ, /RD, /WR -> 74LVC32 -> nMEMRD, nMEMWR, nIORD, nIOWR -> GPIO
  /BE /WAIT /BUSRQ /NMI /RESET <-- 74LVC06 open-drain <-- BE_REQ, WAIT_REQ (PIO), BUSRQ, NMI_REQ (expander), RESET_HOLD (GPIO, pull-up)
  EAR <-- divider <-- TAPE_OUT ; SOUND -> audio mixer
Slow I/O: XL9555 16-bit I2C expander (I2C0 on GP24/GP25, /INT on GP35)
  out: BUSRQ, NMI_REQ, nOLED_RST, WIFI_EN, WIFI_DL, nLED      in: joystick x6, nBUSAK_L, SD_CD
RP2350B support: GD25Q128E QSPI (16 MB, W25Q128 pinout), APS6404L PSRAM footprint (CS1 = GP47, not fitted on the prototype), 12 MHz, USB-C (data, VBUS to the diode-OR), BOOTSEL/RUN
SD on SPI0, OLED on SPI1, ESP32-C3-WROOM-02 (Zimodem) on UART, PWM stereo -> op-amp mixer -> 3.5 mm jack, DE-9 -> expander
```

The two address buffers are the byte mux: their output enables put one address byte at a time on MD. U1 delivers A0-A7 on MD0-MD7 and U2 delivers A8-A15 on MD0-MD7, so the PIO's two reads are the plain low and high byte and its 16-bit word is the Z80 address as it is. (The edge connector's finger order splits the low byte's fingers either side of the high byte's; that is absorbed in the board routing, not in the firmware.)

## 3. Bus cycles

### 3.1 Z80 memory cycle (served by PIO and DMA)

1. PIO waits for nMEMRD or nMEMWR low. These are /MREQ ORed with /RD and /WR, so refresh cycles, which assert neither, never trigger it.
2. It drives nAEN_HI low and samples MD0-MD7 (A15-A8), then nAEN_HI high, nAEN_LO low, sample again (A7-A0), nAEN_LO high. One PIO cycle separates the two enables so the buffers never drive MD together. About 40 ns.
3. It decides the class from nROSCS_L, nEXROM_L, Z80_A15/A14 and which strobe fired, exactly the rule the shipped `set_ctrl` state machine applies:

| nROSCS | nEXROM | A15 = A14 = 0 and read | Class | Served from | /BE |
|---|---|---|---|---|---|
| low | x | x | DOCK | DCK image, full 64 KB, Z80 address unchanged | asserted if the DCK slot is enabled |
| high | low | x | EXROM | second 16 KB of the ROM slot | asserted if EN_EX |
| high | high | yes | HOME ROM | first 16 KB of the ROM slot | asserted if EN_HOME |
| otherwise | | | not ours | nothing | released |

   HOME is the first 16 KB of a 32 KB ROM slot, EXROM the second, as today.
4. For a read: the PIO shifts the chosen image base (held in a scratch register per class) in front of the 16-bit address to form a 32-bit SRAM pointer, pushes it, and a two-channel DMA chain fetches the byte into the PIO TX FIFO. The PIO sets MD0-MD7 as outputs, drives the byte, asserts nDATA_OE and BE_REQ, and holds until nMEMRD rises. About 100 to 150 ns from the strobe to data on the Z80 bus.
5. For a write: the PIO enables the data transceiver inward, captures MD0-MD7 on nMEMWR rising, and pushes address plus data; a DMA channel stores the byte into the image. Writes to a DCK slot are the "DCK RAM" of today; writes to a ROM slot are what the existing update TAPs do, and the firmware decides whether to persist them (section 5).

Timing budget: the tightest case is an opcode fetch, about 375 ns from /MREQ low to data valid at the Z80 after transceiver delays. The path above uses well under half of it. Regular reads allow about 550 ns.

### 3.2 Z80 I/O cycle

PIO waits for nIORD or nIOWR (/IORQ ORed with /RD and /WR; an interrupt acknowledge asserts neither), reads the address the same way, and classifies:

| Port | Function |
|---|---|
| $0E / $0F | TS-Pico data / status (legacy pair; current ROMs) |
| $1C / $1D / $1E | TS-Pico data / command / memory control (firmware wishlist; optional) |
| $1F | Kempston joystick, answered from a byte the main loop refreshes from the expander when its /INT line reports a change |
| $73 / $77 | Intel 8251 data / status (TS2050 layout), bridged to the ESP32-C3 UART running Zimodem |
| $FFFD / $BFFD | AY-3-8910 register select / data (Spectrum 128 layout, A15 and A14 decoded); the low byte $FD does not collide with the 2068's $F5/$F6 PSG |
| anything else | ignored |

Which ports are enabled is a firmware setting; there is no port jumper. WAIT_REQ is a PIO side-set: asserted as soon as a served read is recognised, released once data is on the bus, so blocking FIFO pulls are safe. Whether to use it is a firmware flag.

### 3.3 DMA mode (removed)

An earlier revision could take the 2068's bus after BUSRQ and read or write its memory (for snapshots) through two address latches and a bus-driver chip. It cost six RP2350B pins in the most congested part of the fan-out and was dropped on 2026-09-17. `DMA_OPTION = True` in `hardware/scripts/config.py` restores the schematic side; the board would then need a new layout. BUSRQ and nBUSAK stay wired (expander bits), so the firmware can still halt the Z80 cleanly.

## 4. Slow I/O: the I2C expander

One XL9555 (PCA9555 pinout, address 0x20) replaces the CTL register, its power-on clear and the STAT buffer.

| Port | Bits |
|---|---|
| 0 (outputs) | 0 BUSRQ, 1 NMI_REQ, 2 nOLED_RST, 3 WIFI_EN, 4 WIFI_DL (1 = ESP32 download mode; an open-drain gate pulls IO9 low), 5 nLED (low = on), 6-7 spare |
| 1 (inputs) | 0-3 joystick up/down/left/right, 4 fire, 5 fire 2, 6 nBUSAK_L, 7 SD card detect |

The expander powers up with every pin an input and weak pull-ups. 10 k pull-downs on the five active-high outputs give the same safe start the cleared CTL register did: no bus request, no NMI, OLED in reset, ESP32 off, normal ESP32 boot, LED off. /INT (GP35) fires on any input change, so the firmware reads the joystick only when it moves. A read takes about 100 us at 400 kHz.

## 5. Images, slots and persistence

- The active set (one DCK image up to 64 KB, one ROM slot of 32 KB, and whatever the firmware wants ready for fast switching) lives in RP2350 internal SRAM. 520 KB total leaves ample room for MicroPython.
- A slot map file (on the QSPI filesystem, mirrored or overridden from SD) lists named slots: type (DCK or ROM), image file, size, checksum. The firmware keeps today's slot numbering (8 DCK banks, 16 ROM halves) so `tpi:memboot`, `tpi:memdock` and existing ROMs keep working, and extends it with names and as many slots as storage allows. "What's in the flash" is a listing of the map. A v2.2 512 KB flash image imports and exports as a file conversion.
- Loading an image into SRAM takes about 1 ms from PSRAM, about 2 ms from QSPI flash, and 30 to 50 ms from SD. Switching cartridges is instant from the user's point of view; the ROM boots with no SD card present.
- Z80 writes into a ROM slot are captured in SRAM. The firmware either recognises the SST39SF040 command sequence the existing update TAPs issue and commits the result to the slot's file, or offers a save command; both keep the current user workflow.

## 6. Reset, buttons, power

- RESET_HOLD is an RP2350 GPIO with a 4.7k pull-up into a 74LVC06 open-drain inverter on the 2068 /RESET line. Floating (RP2350 booting or absent) means high, so the 2068 is held in reset; the firmware drives it low to release and pulses it high to reset the 2068. Same behaviour the 555 gave, under firmware control.
- TS Reset and NMI buttons pull the bus lines directly, as today. BOOTSEL and RUN buttons for the RP2350B.
- Power: the card's 5 V rail is a Schottky diode-OR (SS34) of edge pin B4 and USB-C VBUS, so it runs from the 2068 or the expansion bus, from USB alone on the bench for programming, or both at once while debugging, without back-feeding either source. Budget about 250 mA average plus ESP32-C3 transmit bursts of up to about 350 mA at 3.3 V; 2 x 220 uF bulk on 5 V, 100 uF at the module, radio in modem-sleep unless in use. Two TLV1117LV33 LDOs (0.35 V dropout, needed because of the diode drop): logic and RP2350B, and the ESP32 module. When USB-powered with the card in an unpowered 2068, only the open-drain lines and the address transceivers (inputs) face the bus, so nothing drives the dead machine.

## 7. GPIO map (RP2350B)

| GPIO | Signal | Dir | Notes |
|---|---|---|---|
| 0-7 | MD0-MD7 | bidir | Local bus. PIO in/out base. |
| 8 | nAEN_LO | out | Low address byte (A0-A7) buffer enable (PIO side-set). |
| 9 | nAEN_HI | out | High address byte (A8-A15) buffer enable (PIO side-set). |
| 10 | nDATA_OE | out | Data transceiver enable (PIO side-set). |
| 11 | BE_REQ | out | Asserts /BE through the 74LVC06 (PIO). |
| 12 | WAIT_REQ | out | Asserts /WAIT (PIO side-set). |
| 13, 14 | Z80_A14, Z80_A15 | in | Direct copies for the class decision before the byte read completes. |
| 15, 16 | nMEMRD, nMEMWR | in | /MREQ ORed with /RD, /WR. PIO wait pins. |
| 17, 18 | nIORD, nIOWR | in | /IORQ ORed with /RD, /WR. |
| 19, 20 | nROSCS_L, nEXROM_L | in | GP13-GP20 contiguous for `in pins`. |
| 21 | nINT_L | in | 2068 frame interrupt, AY timing. |
| 22 | TAPE_IN | in | SPK/TAP from the 2068 (through the control transceiver). |
| 23 | TAPE_OUT | out | To EAR via divider. |
| 24, 25 | I2C_SDA, I2C_SCL | | I2C0 to the XL9555 expander, 4.7 k pull-ups. |
| 29 | RESET_HOLD | out | Pull-up 4.7k; high = 2068 held in reset. |
| 30 | AUDIO_R (PWM) | out | |
| 35 | nIOX_INT | in | Expander change interrupt, 10 k pull-up. |
| 26-28, 31, 33, 36, 40 | spare | | Seven spares. |
| 32 | SD MISO | in | SPI0 RX (GP32 instead of GP36: the GP36 pad has no routable exit on the placed board). |
| 37-39 | SD CS, SCK, MOSI | out | SPI0 pin group. |
| 34 | OLED DC | out | Plain GPIO; moved from GP40, whose pad is boxed in on the board. |
| 41-43 | OLED CS, SCK, MOSI | out | SPI1 pin group; OLED reset from the expander. |
| 44, 45 | WIFI_TX, WIFI_RX | | ESP32-C3 UART0 (module GPIO20/21). XON/XOFF flow control; EN and IO9 from the expander. |
| 46 | AUDIO_L (PWM) | out | |
| 47 | PSRAM CS1 | | QMI CS1n (options GP0, 8, 19, 47). |

41 used, 7 spare. Slow signals go through the expander, which has two spare bits.

## 8. Chip list (interface and local bus)

| Qty | Part | Role |
|---|---|---|
| 2 | 74LVC245 | Z80 address low byte and high byte onto MD; the output enables are the byte mux |
| 1 | 74LVC245 | Z80 D0-D7 to MD0-MD7 |
| 1 | 74LVC245 | Control inputs, 5 V tolerant |
| 1 | 74LVC32 | nMEMRD, nMEMWR, nIORD, nIOWR strobes |
| 1 | 74LVC06 | Open-drain: /BE, /WAIT, /BUSRQ, /NMI, /RESET, ESP32 IO9 |
| 1 | XL9555 | I2C expander: control outputs, joystick, status |

Seven packages, four part numbers (down from 16 packages in the first v3 schematic), all 74LVC because every one of them touches the 5 V bus. The data transceiver takes its direction straight from /RD. No memory chips. MCU support: RP2350B, GD25Q128E, APS6404L-3SQR footprint (not fitted on the prototype), 12 MHz crystal, two 3.3 V LDOs, USB-C, buttons, SWD pads. WiFi: ESP32-C3-WROOM-02 (castellated SMT, 4 MB, on-board antenna; stock Zimodem firmware).

## 9. Firmware impact

- Memory: the `sel_bank`/`set_ctrl` state machines become one PIO program that reads the address bytes, picks a base pointer, and hands off to a DMA chain. PIO and DMA are configurable from MicroPython; the cycle itself needs no CPU. The image-load, slot-map and persistence logic replaces the flash-bank commands' hardware side while keeping their names.
- Ports: `TS_IO` becomes a classifier over the address byte plus A14/A15, with WAIT side-set; the 8251 and AY emulations are new responders. AY audio generation runs in C on core 1.
- SD on its own SPI; reset is RESET_HOLD; ESP32 control, LED, OLED reset and joystick through the I2C expander, joystick reads driven by its /INT line.

## 10. Risks

- **Emulated-memory timing** is the one hardware risk. It is proven on RP2040-class ROM emulators, but validate on a breadboard (Pico 2 plus three 74LVC245s on a 2068, serve a 16 KB ROM, scope the fetch) before layout is final.
- **SRAM budget**: about 100 KB for the active set plus buffers must coexist with MicroPython's heap. Fine on 520 KB, but the firmware build has to reserve it explicitly.
- **DMA onto 2068 RAM** was dropped from the hardware (section 3.3).
- **Edge connector fit**, **JLC stock** (RP2350B, ESP32-C3 module, SD socket), **chip-down MCU layout**: as before.

## 11. Open questions for review

1. Confirm the class table in 3.1 against the current `set_ctrl`, including the DCK "device none" case, and whether DOCK writes should be gated by a RAM write-protect bit (the wishlist asks for one; it is a CTL spare bit).
2. Enable $1C to $1E from the start, or only the legacy pair until the ROM is updated?
3. AY at the Spectrum 128 ports, or a TS-specific port; ABC or ACB stereo mixing?
4. Persistence of Z80 writes into a ROM slot: emulate the SST39SF040 command sequence, or a save command, or both?
