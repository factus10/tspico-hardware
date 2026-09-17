"""Build options shared by the schematic generators."""

# DMA (the RP2350B reading/writing the 2068's own memory after a bus grant, for
# snapshots). False since 2026-09-17: the option cost six RP2350B pins in the most
# congested part of the QFN fan-out and two of its nets could not be routed.
# True places U8, U12, U13 and their caps as DNP parts, adds U9 (data direction
# XOR) and six GPIOs; the board then needs a new layout.
DMA_OPTION = False
