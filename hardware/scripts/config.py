"""Build options shared by the schematic generators."""

# DMA (the RP2350B reading/writing the 2068's own memory after a bus grant, for
# snapshots) is a stuffing option: U8, U12, U13 and their caps are placed but
# DNP, and U9 (data direction XOR) stays fitted. Set False to delete the DMA
# parts and U9 altogether: the data transceiver then takes DIR straight from
# /RD with its A/B sides swapped, and four GPIOs come free.
DMA_OPTION = True
