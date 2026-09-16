# TS-Pico v3 interface architecture (Pico 2 variant, superseded)

Status: ARCHIVED. Superseded by ../v3-architecture.md (RP2350B). Kept for the register-file reasoning.

Original status: proposal for review with the firmware maintainers before schematic capture. Everything here is a contract the firmware will be written against.

## 1. Design goals

1. Z80 data path to the Pico is always connected; nothing is shared with the SD card.
2. The Pico can read and write every byte of the flash and the SRAM, in addition to the Z80's existing read and write access to both.
3. The per-memory-cycle bank decision (DOCK vs ROM, HOME vs EXROM) is made by hardware from Pico-written registers, not by PIO in the cycle.
4. Z80 I/O accesses to the card can be stretched with /WAIT until the Pico responds.
5. Reset of the 2068 is under Pico control and defaults to "held in reset" until the Pico releases it.
6. Everything fits in the Pico 2's 26 GPIOs with the register interface absorbing all growth.

## 2. Block diagram

```
TS2068 edge connector (5 V)
  A0-A15 ──► 74HCT541 x2 (tri-state, /OE = BUS_OWN) ──► MA0-MA13 ─────────────────────┐
                                        A14,A15 ──► ┐                                   │
  /ROSCS, /EXROM, /MREQ, /RD, /WR, /RFSH, /M1, /IORQ ──► decode logic                   │
                                                    │                                   │
  D0-D7 ◄──► 74HCT245 (Z80 data, DIR=/RD, /OE from decode) ◄──► MD0-MD7 (local bus) ◄──┼──► Flash SST39SF040 (TSOP-32)
                                                                     ▲                  │    SRAM  AS6C4008   (SOP-32)
  /BE, /WAIT, /BUSRQ, /NMI, /RESET ◄── open-drain drivers (74HCT07, 2N7002)              │                  MA14-MA18 ◄─┐
                                                                     │                  │                              │
Pico 2 (3.3 V)                                                       │                  │   74HCT257 x2 (tri-state mux) │
  GP0-GP7  ◄──► 74LVC245 (Pico data, DIR from strobes) ◄─────────────┘                  │     sel = /ROSCS              │
  GP12-GP15 ──► 74HCT138 register select ──► /WR_ALO /WR_AHI /WR_ACTL /WR_DCK /WR_ROM /RD_STAT │  A: {Z80 A14, A15, DCK bank}  │
                                                │        │       │        │      │      │  B: {EXROM-derived A14,       │
                                         74HCT574 x2  74HCT273 74HCT273 74HCT273  74HCT541 │      ROM A15, ROM bank}       │
                                         MA0-MA15    ctrl reg   DCK reg  ROM reg  status  │  /OE = BUS_OWN                │
                                         (/OE=!BUS_OWN)  │                                │                              │
                                                         └── MA16-18 + PFCE/PSCE (Pico mode, /OE = !BUS_OWN) ────────────┘
  GP16-GP19 ◄──► micro SD socket (SPI0), GP20 card detect
  GP8 /IOSEL, GP9 IO_WR, GP10 A0, GP11 /WAIT_ACK  (via 74LVC245 from 5 V decode)
  GP21 /MRD, GP22 /MWR
  GP26 RESET_REQ (pull-down), GP27 A1 or spare, GP28 /NMI_OUT or spare
```

## 3. Bus-cycle behaviour

### 3.1 Z80 mode (BUS_OWN = 0)

Z80 address buffers and the MA14 to MA18 mux drive the local address bus. The Pico address latches are tri-stated.

Per memory cycle (/MREQ low, /RFSH high, /RD or /WR low), hardware selects:

| Condition (from 2068 signals) | Access class | MA14, MA15 | MA16 to MA18 | Device | /BE |
|---|---|---|---|---|---|
| /ROSCS low | DOCK | Z80 A14, A15 | DCK reg bank | DCK reg device (flash / SRAM / none) | asserted if DCK reg EN |
| /ROSCS high, /EXROM low | EXROM | EXROM half select, ROM reg A15 | ROM reg bank | ROM reg device | asserted if ROM reg EN_EX |
| /ROSCS high, /EXROM high, A15 = A14 = 0, /RD low | HOME ROM | HOME half select, ROM reg A15 | ROM reg bank | ROM reg device | asserted if ROM reg EN_HOME |
| otherwise | none | - | - | none | released |

This is the rule the current `set_ctrl` and `sel_bank` PIO programs implement (firmware: `tspico_io.py`), moved into a 74HCT257 pair and a few gates. Which 16 KB half of the 32 KB ROM slot is HOME and which is EXROM is fixed in hardware. The shipped firmware (`set_ctrl`) drives A14_B = 0 for HOME and A14_B = 1 for EXROM, so HOME is the first 16 KB and EXROM the second: MA14 = NOT /EXROM. (An earlier 2023 test readme proposed the opposite; that was never the shipped arrangement.)

Chip selects: /FCE and /SCE assert only for a class whose register selects that device and whose EN bit is set. /MOE follows Z80 /RD; /FWE and /SWE both follow Z80 /WR, so the Z80 can write SRAM and program flash exactly as it does today with P10 closed. The existing Z80-side update routines (SST39SF040 unlock sequence at $5555/$2AAA) keep working unchanged.

The Z80 data transceiver is enabled for any selected memory cycle and for any card I/O cycle, direction from /RD.

### 3.2 I/O cycles

Port compare (74HCT688): {A7, A6, A5, A4, A3, A2, A1, /M1} against {0, 0, 0, J, 1, 1, 1, 1}, enabled by /IORQ. J is the port-pair solder jumper (0 selects $0E/$0F, 1 selects $1E/$1F). Output /IOSEL goes to the Pico and to the wait flip-flop.

- Pico sees /IOSEL, IO_WR (buffered /WR: low = Z80 is writing to the card), and A0 (0 = data port, 1 = status/command port). This is the same trio the current `TS_IO` PIO program uses (/PICOSEL on GP14, discriminator on GP11, A0 on GP10), so the PIO changes are pin numbers plus the wait acknowledge.
- On /IOSEL falling, the 74HCT74 sets and /WAIT is asserted through an open-drain driver, if the wait-enable jumper is closed. The Pico clears it by pulsing /WAIT_ACK once its data is on the bus (read) or captured (write). With the jumper open the card behaves exactly as today: no /WAIT, Pico must answer within the cycle.
- Pico data transceiver direction: Pico drives the bus while /IOSEL is low and IO_WR is high (Z80 read), while any register write strobe is active, and while /MWR is active; otherwise it listens.

Option, one comparator bit and one GPIO: drop A1 from the compare and route A1 to GP27. The card then answers $0C to $0F (or $1C to $1F), which is the four-port layout the firmware wishlist describes (data, command, memory control, joystick). The firmware can ignore A1 to behave as two ports. Decide at review.

### 3.3 Pico mode (BUS_OWN = 1)

Set BUS_OWN in the control register. The Z80 address buffers and the bank mux tri-state; the three Pico latches drive MA0 to MA18 and the chip selects PFCE/PSCE come from the control register. The Z80 data transceiver is disabled.

Read: write ALO, AHI, ACTL; set GP0 to GP7 as inputs; pulse /MRD low (memory drives MD, LVC245 passes it to the Pico); sample; release.
Write: write ALO, AHI, ACTL; set GP0 to GP7 as outputs with data; pulse /MWR low; release. /MWR drives /FWE or /SWE according to PFCE/PSCE.

Flash programming is the SST39SF040 JEDEC sequence (writes to $5555/$2AAA, then sector erase or byte program) issued this way from the Pico. Expect around 1 to 2 µs per byte through PIO or tight C; MicroPython viper code is adequate for occasional ROM updates.

When to enter Pico mode safely:

- While the 2068 is held in reset (power-up, or a Pico-initiated reset). The Z80 tri-states its buses in reset, and the Z80 address buffers are disabled anyway.
- At runtime, by setting BUSRQ in the control register, polling /BUSAK in the status register, then setting BUS_OWN. Release in the reverse order. The 2068's SCLD keeps refreshing video RAM during bus grant, so short grants are safe; keep them short.

Firmware must never set BUS_OWN while the Z80 might access the card's memory without a bus grant.

## 4. Register map

All registers are written by putting a byte on GP0 to GP7 and pulsing /REG_STB with REG_SEL0 to REG_SEL2 selecting the register (74HCT138). Reads use the same mechanism with the Pico pins as inputs.

| Sel | Name | Type | Bits |
|---|---|---|---|
| 0 | ALO | 74HCT574 (tri-state) | MA0 to MA7 (Pico mode) |
| 1 | AHI | 74HCT574 (tri-state) | MA8 to MA15 (Pico mode) |
| 2 | ACTL | 74HCT273 (clears at power-up) | 0-2 MA16 to MA18 (Pico mode); 3 PFCE; 4 PSCE; 5 BUS_OWN; 6 BUSRQ; 7 LED/spare |
| 3 | DCK | 74HCT273 | 0-2 bank (A16 to A18); 3 DEV_F; 4 DEV_S; 5 EN; 6-7 spare |
| 4 | ROM | 74HCT273 | 0-2 bank (A16 to A18); 3 A15 half; 4 DEV_F; 5 DEV_S; 6 EN_HOME; 7 EN_EX |
| 5 | STAT (read) | 74HCT541 | 0 /BUSAK; 1 /ROSCS; 2 /EXROM; 3 /BE (bus); 4 WAIT_PENDING; 5 port jumper J; 6 /NMI button; 7 SD card detect |
| 6, 7 | spare | | future input port (joystick) or output register |

Power-up: ACTL, DCK and ROM are cleared by an RC power-on reset on the 74HCT273 /MR pins. Cleared means BUS_OWN = 0, BUSRQ = 0, all EN = 0, so the card is invisible to the 2068 until the Pico configures it. The 2068 will boot its own ROM if the Pico never comes up (once reset is released, see 5).

Correspondence to today's firmware: `ROM.put(ic_bits)` becomes the DEV bits of the DCK and ROM registers; `BANK.put(DCK_SLOT*16 + ROM_SLOT)` becomes the bank bits (DCK: slot/2 into bank; ROM: slot bit 0 into A15 half, slot bits 1 to 3 into bank).

## 5. Reset, NMI, buttons

- RESET_REQ (GP26) has a 10k pull-down. 74HCT14 inverts it into a 2N7002 that pulls the 2068 /RESET line low. Pico booting or held in reset: pin floats low, 2068 held in reset. Pico ready: drive high. Pico wants to reset the 2068: drive low for 100 ms or more. The RP2350 also enables its internal pull-down on GPIO at reset, so behaviour is defined even before the pad is configured.
- TS Reset button pulls /RESET low directly, as today. Pico Reset button pulls the Pico's RUN pin low, as today.
- NMI button pulls /NMI low directly, as today, and its state is readable in STAT. Optionally GP28 drives /NMI through the open-drain driver so the firmware can raise an NMI itself.
- The 555, its passives, Q1 and JP1/JP2/JP3/JP5/P10 are gone. If a switch-disable is still wanted, it is a solder jumper.

## 6. GPIO map (Pico 2)

| GPIO | Signal | Dir | Notes |
|---|---|---|---|
| GP0-GP7 | D0-D7 | bidir | Via 74LVC245 to the local bus. Contiguous for PIO. |
| GP8 | /IOSEL | in | Card I/O port selected (decoded, /M1-gated). Replaces /PICOSEL. |
| GP9 | IO_WR | in | Buffered /WR: low = Z80 write. Replaces GP11 discriminator. |
| GP10 | A0 | in | Port select within the pair. Same role as today. |
| GP11 | /WAIT_ACK | out | Pulse low to release the wait flip-flop. |
| GP12-GP14 | REG_SEL0-2 | out | Register select. |
| GP15 | /REG_STB | out | Register strobe. |
| GP16 | SD_MISO | in | SPI0 RX |
| GP17 | SD_CS | out | SPI0 CSn |
| GP18 | SD_SCK | out | SPI0 SCK |
| GP19 | SD_MOSI | out | SPI0 TX |
| GP20 | SD_CD | in | Card detect (also mirrored in STAT). |
| GP21 | /MRD | out | Pico-mode memory read strobe. |
| GP22 | /MWR | out | Pico-mode memory write strobe. |
| GP25 | LED | out | On-board LED, as today. |
| GP26 | RESET_REQ | out | Pull-down; high = release 2068 reset. |
| GP27 | A1 / spare | in | Only if the four-port option is taken. |
| GP28 | /NMI_OUT / spare | out | Optional. |

26 GPIOs, 2 of them optional. Nothing else may be added as a pin; add it to a register.

Level shifting: Pico outputs drive 74HCT inputs directly (TTL threshold 2.0 V). Pico inputs from 5 V logic (/IOSEL, IO_WR, A0, A1) go through a 74LVC245 with 5 V-tolerant inputs. SD_CD is 3.3 V. If the RP2350's 5 V-tolerant-input claim is confirmed in the datasheet the LVC245 could be dropped, but keep it on the first spin.

## 7. Timing notes

- Bank mux settling from /ROSCS or /MREQ: two 74HCT gate delays plus the 257, about 30 ns worst case. Current PIO budget is about 150 ns; the Z80 at 3.5 MHz gives about 400 ns before data must be valid. Flash at 70 ns and SRAM at 55 ns leave margin.
- I/O read without wait: the Pico must put data on the bus within about 250 ns of /IOSEL. The PIO does this today at 15 MHz. With wait enabled there is no deadline.
- Wait flip-flop set-up: /WAIT must be low before the Z80 samples it in the falling edge of TW (I/O cycles always insert one TW). /IORQ to /WAIT through the comparator, flip-flop and open-drain driver is under 40 ns. Fine.
- Pico-mode access: no Z80 timing involved; limited by GPIO toggling speed.

## 8. Chip list for the interface (excluding memories, Pico, SD, power)

| Qty | Part | Role |
|---|---|---|
| 2 | 74HCT541 | Z80 A0-A15 tri-state buffers |
| 1 | 74HCT245 | Z80 data transceiver |
| 2 | 74HCT257 | MA14-MA18 bank mux, tri-state |
| 2 | 74HCT574 | ALO, AHI address latches |
| 3 | 74HCT273 | ACTL, DCK, ROM registers (with clear) |
| 1 | 74HCT541 | STAT read buffer |
| 1 | 74HCT138 | Register select decoder |
| 1 | 74HCT688 | Port compare |
| 1 | 74HCT74 | Wait flip-flop |
| 1 | 74HCT07 | Open-drain drivers: /BE, /WAIT, /BUSRQ, /NMI |
| 1 | 74HCT14 | Reset path inverter, spare Schmitt inputs |
| 2-3 | 74HCT00/08/32 | Chip-select and transceiver-enable gating |
| 2 | 74LVC245 | Pico data transceiver, Pico input level shifter |
| 1 | 2N7002 | /RESET driver |

About 20 packages in SOIC or TSSOP. All are LCSC basic or extended parts.

## 9. Open questions for review

1. Two ports ($0E/$0F) as briefed, or four ($0C-$0F) to match the firmware wishlist? One comparator bit and GP27.
2. (Resolved) HOME is the first 16 KB, EXROM the second; MA14 = NOT /EXROM.
3. Z80 writes to flash and SRAM are always enabled (the P10 jumper is gone). Should a software write-protect bit for flash, and one for RAM (the wishlist asks for one), be added to the registers? Each costs a spare register bit and one gate, and would power up as "writes allowed" so current behaviour is the default.
4. Keep the "no wait" mode jumper, or make wait always-on once the firmware supports it?
5. Any need for the Pico to observe /MREQ activity (for example to detect that the 2068 is running)? It could be a STAT bit; today it is a GPIO.
