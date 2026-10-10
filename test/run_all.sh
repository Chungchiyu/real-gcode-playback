#!/usr/bin/env bash
# Runs every test. Needs: node, python3, playwright (pip install playwright && playwright install chromium),
# and a built dist/ (python build.py from the repo root).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p shots
python3 gen_gcode.py bambu bambu.gcode
python3 gen_gcode.py marlin marlin.gcode
python3 gen_flags.py
node gen_big.js
node gen_orca_timing.js
node gen_bead.js
echo "== core";        node unit.js; node core_test.js; node flags_test.js; node timing_test.js; node bead_test.js
echo "== page";        python3 ui_test.py; python3 code_test.py; python3 center_test.py; python3 flags_ui.py; python3 speed_test.py; python3 blur_test.py; python3 bead_ui.py; python3 controls_test.py; python3 export_test.py; python3 export_host_test.py; python3 export_orca_env_test.py
echo "== plugin";      python3 plugin_harness.py; python3 harness2.py; python3 plugin_export_test.py
