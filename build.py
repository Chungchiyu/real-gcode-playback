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
    THREE / "examples/js/lines/LineSegmentsGeometry.js",
    THREE / "examples/js/lines/LineMaterial.js",
    THREE / "examples/js/lines/LineSegments2.js",
]
vendor = "\n;\n".join(p.read_text(encoding="utf-8") for p in VENDOR_FILES)
vendor = "/* three.js r147 (MIT License, Copyright 2010-2022 Three.js Authors) */\n" + vendor

# export: video muxers and encoders, the GIF encoder (see README for licences)
NM = ROOT / "node_modules"
gifenc = (NM / "gifenc/dist/gifenc.js").read_text(encoding="utf-8")   # CommonJS: give it an exports object
def strip_map(js):
    return "\n".join(l for l in js.split("\n") if not l.startswith("//# sourceMappingURL="))
# an ES module: drop the export line, keep the factory it defines
webm_glue = strip_map((NM / "webm-wasm/dist/webm-wasm.js").read_text(encoding="utf-8")).replace("export default Module;", "")
EXPORT_LIBS = [
    "/* mp4-muxer 5.2.2 (MIT License, Copyright (c) 2023 Vanilagy) */\n" + (NM / "mp4-muxer/build/mp4-muxer.js").read_text(encoding="utf-8"),
    "/* webm-muxer 5.1.4 (MIT License, Copyright (c) 2022 Vanilagy) */\n" + (NM / "webm-muxer/build/webm-muxer.js").read_text(encoding="utf-8"),
    "/* gifenc 1.0.3 (MIT License, Copyright (c) 2017 Matt DesLauriers) */\n"
    "window.gifenc = (function () { var exports = {}, module = { exports: exports };\n" + gifenc + "\nreturn module.exports; })();",
]
# The video encoders are big (~2 MB). OrcaSlicer loads the page with WebView2's NavigateToString,
# which takes at most 2 MB of HTML, so in the plugin they are not part of the page: the page asks
# the plugin for them the first time an MP4/WebM is exported. The standalone page has them inline.
ENCODER_LIBS = [
    # H.264 MP4 without WebCodecs (OrcaSlicer's page): minih264 (public domain) + libmp4v2 (MPL 1.1)
    "/* h264-mp4-encoder 1.0.12 (MIT License, Copyright (c) 2020 Trevor Sundberg); includes minih264 (CC0/public domain)"
    " and libmp4v2 (Mozilla Public License 1.1, source: https://github.com/TrevorSundberg/libmp4v2) */\n"
    + strip_map((NM / "h264-mp4-encoder/embuild/dist/h264-mp4-encoder.web.js").read_text(encoding="utf-8")),
    # VP8 WebM without WebCodecs: libvpx (BSD) + libwebm (BSD), wrapped by webm-wasm (Apache-2.0)
    "/* webm-wasm 0.4.1 (Apache License 2.0, Copyright 2018 Google Inc.); includes libvpx and libwebm (BSD-3-Clause) */\n"
    "window.webmWasmFactory = (function () {\n" + webm_glue + "\nreturn Module; })();\n"
    "window.WEBM_WASM_B64 = '" + base64.b64encode((NM / "webm-wasm/dist/webm-wasm.wasm").read_bytes()).decode("ascii") + "';",
]
vendor = vendor + "\n;\n" + "\n;\n".join(EXPORT_LIBS)
encoders = "\n;\n".join(ENCODER_LIBS)
assert "</script" not in encoders.lower(), "encoders contain a closing script tag"
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


(DIST / "playback.html").write_text(assemble(vendor + "\n;\n" + encoders), encoding="utf-8")

# ---- plugin: the page template and app code stay readable; three.js ships compressed
template = page.replace("/*@@CORE@@*/", core).replace("/*@@APP@@*/", app)
assert "'''" not in template and '"""' not in template
vendor_b64 = base64.b64encode(zlib.compress(vendor.encode("utf-8"), 9)).decode("ascii")
vendor_wrapped = "\n".join(vendor_b64[i:i + 100] for i in range(0, len(vendor_b64), 100))
enc_b64 = base64.b64encode(zlib.compress(encoders.encode("utf-8"), 9)).decode("ascii")
enc_wrapped = "\n".join(enc_b64[i:i + 100] for i in range(0, len(enc_b64), 100))
page_bytes = len(template.replace("/*@@VENDOR@@*/", vendor, 1).encode("utf-8"))
PAGE_LIMIT = 1_900_000      # WebView2 NavigateToString refuses more than 2 MB; keep a margin
assert page_bytes < PAGE_LIMIT, f"the plugin page is {page_bytes} bytes; WebView2 loads at most 2 MB"

import json
log = json.loads((SRC / "changelog.json").read_text(encoding="utf-8"))
log_text = "\n".join(f"{e['version']} ({e['date']})\n" + "\n".join(f"  - {c}" for c in e["changes"]) for e in log["entries"])
plugin = (SRC / "plugin.py").read_text(encoding="utf-8")
plugin = (plugin.replace("@@VERSION@@", log["version"])
                .replace("@@CHANGELOG_TEXT@@", log_text)
                .replace("@@CHANGELOG_JSON@@", json.dumps(log, ensure_ascii=False, indent=1)))
plugin = plugin.replace("@@PAGE_TEMPLATE@@", template).replace("@@VENDOR_B64@@", vendor_wrapped).replace("@@ENCODERS_B64@@", enc_wrapped)
out = DIST / "orca_playback.py"
out.write_text(plugin, encoding="utf-8")
print("wrote", DIST / "playback.html", (DIST / "playback.html").stat().st_size, "bytes")
print("wrote", out, out.stat().st_size, "bytes; its page is", page_bytes, "bytes (limit 2 MB)")
