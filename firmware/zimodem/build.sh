#!/bin/sh
# Build Zimodem for the TS-Pico v3's ESP32-C3 module. Needs PlatformIO.
#   ./build.sh                 build
#   ./build.sh upload PORT     build and flash through the card (esp_bridge running)
set -e
cd "$(dirname "$0")"

ZIMODEM_REPO=https://github.com/bozimmerman/Zimodem.git
ZIMODEM_REV=a24225cc1b6c219e6c0764a4e6b1a388356a1dd5   # 4.0.3, 2026-08-30

[ -d Zimodem/.git ] || git clone -q "$ZIMODEM_REPO" Zimodem
git -C Zimodem cat-file -e "$ZIMODEM_REV^{commit}" 2>/dev/null || git -C Zimodem fetch -q origin
git -C Zimodem checkout -q --force "$ZIMODEM_REV"

# The C3 configuration reads DTR on IO5 and the pulse-dial line on IO7, which
# are unconnected on this card. Pull them up (inactive) so a floating input
# cannot hang up a connection.
perl -pi -e 's/pinMode\(pinDTR,INPUT\)/pinMode(pinDTR,INPUT_PULLUP)/; s/pinMode\(pinOTH,INPUT\)/pinMode(pinOTH,INPUT_PULLUP)/' \
    Zimodem/zimodem/zcommand.ino

if [ "$1" = upload ]; then
    pio run -t upload --upload-port "${2:?usage: build.sh upload PORT}"
else
    pio run
fi
