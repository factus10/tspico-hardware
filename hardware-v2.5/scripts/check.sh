#!/bin/sh
# Run ERC and DRC with kicad-cli. Exit non-zero on any violation.
set -e
cd "$(dirname "$0")/.."
KC=${KICAD_CLI:-/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli}
"$KC" sch erc --output erc.rpt --severity-all --exit-code-violations tspico-v2.5.kicad_sch
"$KC" pcb drc --output drc.rpt --severity-all --exit-code-violations tspico-v2.5.kicad_pcb
echo "ERC and DRC clean"
