#!/usr/bin/env bash
# Пересборка схем аудита 2026-10: SVG (источник) -> PNG 2400x1350.
# Требования: python3, node >= 18, пакет @resvg/resvg-js (npm i @resvg/resvg-js в любом каталоге,
# затем NODE_PATH=<тот каталог>/node_modules bash scripts/audit_schemes/build.sh),
# шрифты DejaVu (/usr/share/fonts/truetype/dejavu) — используются для кириллицы.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/../../assets/audit"
mkdir -p "$OUT"
declare -A MAP=(
  [make_d1_thyroid.py]=01-tireotoksicheskiy-kriz-4v1
  [make_d2_nms.py]=02-kriterii-nzs
  [make_d3_mh.py]=03-zlokachestvennaya-gipertermiya-priznaki
  [make_d4_infant.py]=04-likhoradka-mladenec-do-3-mes
  [make_d5_seizure.py]=05-sudorogi-lestnica-terapii
  [make_d6_thermo.py]=06-dve-modeli-termoregulyacii
  [make_d7_spectrum.py]=07-spektr-teplovyh-porazheniy
  [make_d8_map.py]=08-karta-audita
)
for script in "${!MAP[@]}"; do
  name="${MAP[$script]}"
  python3 "$HERE/$script" "$OUT/$name.svg"
  node "$HERE/render.js" "$OUT/$name.svg" "$OUT/$name.png" 2400
done
