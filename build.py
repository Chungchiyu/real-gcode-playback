"""Assemble the standalone page and the OrcaSlicer plugin file from src/.

  npm install                -> fetches three.js r147 into node_modules/
  python build.py            -> dist/playback.html (standalone) and dist/orca_playback.py (plugin)
"""
import base64
import pathlib
import zlib

ROOT = pathlib.Path(__file__).parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

THREE = ROOT / "node_modules" / "three"   # npm install (three@0.147.0, pinned in package.json)
VENDOR_FILES = [
    THREE / "build/three.min.js",
    THREE / "examples/js/controls/OrbitControls.js",
    THREE / "examples/js/lines/LineSegmentsGeometry.js",
    THREE / "examples/js/lines/LineMaterial.js",
    THREE / "examples/js/lines/LineSegments2.js",
]
vendor = "\n;\n".join(p.read_text(encoding="utf-8") for p in VENDOR_FILES)
vendor = "/* three.js r147 (MIT License, Copyright 2010-2022 Three.js Authors) */\n" + vendor
import json as _json
core = (SRC / "core.js").read_text(encoding="utf-8")
core = "window.PLAYBACK_ABOUT = " + _json.dumps(_json.loads((SRC / "changelog.json").read_text(encoding="utf-8")), ensure_ascii=False) + ";\n" + core
app = (SRC / "app.js").read_text(encoding="utf-8")
page = (SRC / "page.html").read_text(encoding="utf-8")

for name, text in (("vendor", vendor), ("core", core), ("app", app)):
    assert "</script" not in text.lower(), f"{name} contains a closing script tag"


def assemble(vendor_js):
    return (page.replace("/*@@VENDOR@@*/", vendor_js)
                .replace("/*@@CORE@@*/", core)
                .replace("/*@@APP@@*/", app))


(DIST / "playback.html").write_text(assemble(vendor), encoding="utf-8")

# ---- plugin: the page template and app code stay readable; three.js ships compressed
template = page.replace("/*@@CORE@@*/", core).replace("/*@@APP@@*/", app)
assert "'''" not in template and '"""' not in template
vendor_b64 = base64.b64encode(zlib.compress(vendor.encode("utf-8"), 9)).decode("ascii")
vendor_wrapped = "\n".join(vendor_b64[i:i + 100] for i in range(0, len(vendor_b64), 100))

import json
log = json.loads((SRC / "changelog.json").read_text(encoding="utf-8"))
log_text = "\n".join(f"{e['version']} ({e['date']})\n" + "\n".join(f"  - {c}" for c in e["changes"]) for e in log["entries"])
plugin = (SRC / "plugin.py").read_text(encoding="utf-8")
plugin = (plugin.replace("@@VERSION@@", log["version"])
                .replace("@@CHANGELOG_TEXT@@", log_text)
                .replace("@@CHANGELOG_JSON@@", json.dumps(log, ensure_ascii=False, indent=1)))
plugin = plugin.replace("@@PAGE_TEMPLATE@@", template).replace("@@VENDOR_B64@@", vendor_wrapped)
out = DIST / "orca_playback.py"
out.write_text(plugin, encoding="utf-8")
print("wrote", DIST / "playback.html", (DIST / "playback.html").stat().st_size, "bytes")
print("wrote", out, out.stat().st_size, "bytes")
