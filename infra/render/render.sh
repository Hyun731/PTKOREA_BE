#!/bin/sh
# usage: render.sh <input.pptx> <outdir> [dpi]
set -e
IN="$1"; OUT="$2"; DPI="${3:-96}"
mkdir -p "$OUT"
PDF="$OUT/$(basename "${IN%.*}").pdf"
export HOME=/tmp
"${UNO_PYTHON:-python3}" /usr/local/bin/convert.py "$(readlink -f "$IN")" "$(readlink -f "$OUT")/$(basename "$PDF")"
pdftoppm -r "$DPI" -png "$PDF" "$OUT/page"
ls "$OUT"
