# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Real G-code Playback"
# description = "Real-time playback of the sliced G-code in its own tab: a motion-planned, accelerations-and-corners timeline of the print, synced to the slicer's own time estimate."
# author = "NickChung"
# version = "@@VERSION@@"
# ///
"""Real G-code Playback — watch the sliced G-code print in real time, in an OrcaSlicer tab.

Changelog
---------
@@CHANGELOG_TEXT@@

Two capabilities:

  * "Playback" (Pages) — the tab. A self-contained HTML page with a G-code parser, a motion planner
    (trapezoidal accel/decel with jerk or junction-deviation corners, lookahead) and a Three.js
    viewer. Timing is synced to the slicer's estimate using the M73 progress markers OrcaSlicer
    writes, so the playback clock matches the time OrcaSlicer shows.

  * "Playback capture" (Slicing pipeline) — optional, recommended. When it is selected under
    Process > Others > Slicing Pipeline Plugin, it copies the G-code at the post-processing step into
    this plugin's folder so the tab can load it without any permission prompt. For Bambu Lab
    printers that step runs on every slice; for other printers it runs when you export or send.
    It never changes the G-code.

Without the capture capability the tab falls back to finding OrcaSlicer's temporary G-code for
the last slice; OrcaSlicer asks once for read permission on those files.

Files this plugin writes: only inside its own folder (.captures/latest.gcode + latest.json).
No network access, no processes started.
"""

import base64
import glob
import json
import os
import tempfile
import threading
import time
import zlib

import orca

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
# dot-prefixed so OrcaSlicer's plugin scanner never treats it as a plugin folder
CAPTURE_DIR = os.path.join(PLUGIN_DIR, ".captures")
CAPTURE_FILE = os.path.join(CAPTURE_DIR, "latest.gcode")
CAPTURE_META = os.path.join(CAPTURE_DIR, "latest.json")
CHUNK_CHARS = 384 * 1024            # per message; each is one RunScript call into the page
CAPTURE_NAME = "Playback capture"

DEFAULT_PREFS = {"speed": 10, "color": "feature", "travel": False, "layerOnly": False, "follow": False,
                 "motion": "auto", "lines": "fat", "timing": "aligned", "head": True, "gantry": True, "shade": "tube"}

SETUP_HINT = {
    "title": "One-time setup for automatic loading",
    "steps": [
        "Open the <b>Process</b> settings and switch to <b>Advanced</b> mode.",
        "Go to <b>Others</b> → <b>Slicing Pipeline Plugin</b> and add <b>Playback capture</b>.",
        "Slice again. Bambu Lab printers are captured on every slice; other printers when you export or send.",
    ],
}

CHANGELOG = @@CHANGELOG_JSON@@

# The live page capability, so the capture capability can tell the tab a new slice arrived.
_PAGE = None
_PAGE_HTML = None
_CAPTURE_SEEN = {"t": 0.0}          # when the capture capability last ran
SESSION_START = time.time()         # a capture older than this OrcaSlicer session is not "new"


# --------------------------------------------------------------------------- #
# page
# --------------------------------------------------------------------------- #
PAGE_TEMPLATE = r'''@@PAGE_TEMPLATE@@'''

VENDOR_B64 = """
@@VENDOR_B64@@
"""


def page_html():
    """Three.js ships compressed in this file; the page template and app code stay readable."""
    global _PAGE_HTML
    if _PAGE_HTML is None:
        vendor = zlib.decompress(base64.b64decode("".join(VENDOR_B64.split()))).decode("utf-8")
        _PAGE_HTML = PAGE_TEMPLATE.replace("/*@@VENDOR@@*/", vendor, 1)
    return _PAGE_HTML


# --------------------------------------------------------------------------- #
# finding the G-code of the last slice
# --------------------------------------------------------------------------- #
def read_capture_meta():
    try:
        with open(CAPTURE_META, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
        if os.path.isfile(CAPTURE_FILE):
            meta["mtime"] = os.path.getmtime(CAPTURE_FILE)
            meta["size"] = os.path.getsize(CAPTURE_FILE)
            return meta
    except Exception:
        pass
    return None


def temp_roots():
    base = tempfile.gettempdir()
    roots = [base]
    if hasattr(os, "getuid"):
        roots.insert(0, os.path.join(base, f"orcaslicer_{os.getuid()}"))
    return roots


def find_temp_gcode():
    """OrcaSlicer keeps each plate's sliced G-code at
    <temp>/orcaslicer_model/<day>/<time>#<pid>#<model>/Metadata/.<pid>.<n>.gcode
    (see PartPlate::get_tmp_gcode_path). The plugin runs inside that same process, so the pid
    narrows it to this session. Reading there makes OrcaSlicer ask once for permission."""
    pid = os.getpid()
    best = None
    for root in temp_roots():
        pattern = os.path.join(root, "orcaslicer_model", "*", f"*#{pid}#*", "Metadata", f".{pid}.*.gcode")
        for path in glob.glob(pattern):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if best is None or mtime > best[1]:
                best = (path, mtime)
    return best


def stable(path, wait=4.0):
    """Wait until a file stops growing (the slicer may still be writing it)."""
    deadline = time.time() + wait
    last = -1
    while time.time() < deadline:
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        if size == last and size > 0:
            return True
        last = size
        time.sleep(0.25)
    return last > 0


def when_text(mtime):
    age = max(0, time.time() - mtime)
    if age < 90:
        return "sliced just now"
    if age < 3600:
        return f"sliced {int(age // 60)} min ago"
    return "sliced " + time.strftime("%H:%M", time.localtime(mtime))


# --------------------------------------------------------------------------- #
# the tab
# --------------------------------------------------------------------------- #
class PlaybackPage(orca.pages.PagesPluginCapabilityBase):
    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.transfer_id = 0
        self.slice_done_at = 0.0
        self.loading = False
        global _PAGE
        _PAGE = self

    def get_name(self):
        return "Playback"

    def get_icon(self):
        return "tab_preview_active"      # resources/images/tab_preview_active.svg, ships with OrcaSlicer

    def get_ui(self):
        return page_html()

    def on_load(self):
        global _PAGE
        _PAGE = self

    def on_unload(self):
        global _PAGE
        if _PAGE is self:
            _PAGE = None

    def get_default_config(self):
        return {"prefs": dict(DEFAULT_PREFS)}

    # ---- helpers ------------------------------------------------------------
    def post(self, payload):
        try:
            self.post_message(payload)
        except Exception:
            pass

    def prefs(self):
        try:
            cfg = json.loads(self.get_config() or "{}")
        except Exception:
            cfg = {}
        out = dict(DEFAULT_PREFS)
        stored = cfg.get("prefs") if isinstance(cfg, dict) else None
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULT_PREFS and isinstance(value, type(DEFAULT_PREFS[key])):
                    out[key] = value
                elif key == "speed" and isinstance(value, (int, float)):
                    out[key] = value
        return out

    def latest(self):
        """Identify the newest slice of this session without reading it.
        The stamp is what the page compares with the G-code it shows."""
        meta = read_capture_meta()
        fresh_capture = meta and meta["mtime"] >= SESSION_START - 5 and \
            (not self.slice_done_at or meta["mtime"] >= self.slice_done_at - 30)
        if fresh_capture:
            return {"stamp": f"c{meta['mtime']:.3f}", "name": meta.get("name", ""), "when": when_text(meta["mtime"])}
        if self.slice_done_at:
            return {"stamp": f"s{self.slice_done_at:.3f}", "name": "", "when": when_text(self.slice_done_at)}
        return None

    def status(self, cmd="status"):
        meta = read_capture_meta()
        payload = {"cmd": cmd, "capture_enabled": bool(meta) or _CAPTURE_SEEN["t"] > 0, "hint": SETUP_HINT,
                   "latest": self.latest()}
        if cmd == "status":
            payload["prefs"] = self.prefs()
            payload["about"] = CHANGELOG
        return payload

    # ---- page messages (UI thread: keep quick) ------------------------------
    def on_message(self, msg):
        if not isinstance(msg, dict):
            return
        cmd = msg.get("cmd")
        try:
            if cmd == "hello":
                self.post(self.status())
            elif cmd == "check_latest":
                self.post(self.status("latest_info"))
            elif cmd == "load_latest":
                if not self.loading:
                    self.loading = True
                    threading.Thread(target=self.send_latest, args=(bool(msg.get("quiet")),), daemon=True).start()
            elif cmd == "save_prefs":
                prefs = msg.get("prefs")
                if isinstance(prefs, dict):
                    clean = {k: prefs[k] for k in DEFAULT_PREFS if k in prefs}
                    self.save_config(json.dumps({"prefs": clean}))
        except Exception as exc:
            self.post({"cmd": "error", "message": str(exc)[:300]})

    # ---- lifecycle: a slice finished somewhere in OrcaSlicer ----------------
    def on_lifecycle_event(self, event, ctx):
        try:
            if event == orca.LifecycleEvent.SlicingJobComplete and ctx.code == orca.LifecycleEvtCode.Ok:
                self.slice_done_at = time.time()
                threading.Thread(target=self.announce_slice, daemon=True).start()
        except Exception:
            pass

    def announce_slice(self):
        # give the capture step a moment to finish copying (it runs on the slicing thread)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            meta = read_capture_meta()
            if meta and meta.get("mtime", 0) >= self.slice_done_at - 30:
                break
            time.sleep(0.25)
        self.post(self.status("slice_ready"))

    # ---- sending G-code to the page (worker thread) --------------------------
    def pick_source(self, allow_temp=True):  # -> (path, mtime, name, how, stamp)
        """Return (path, mtime, name, how) for the newest G-code of the current session.
        The temp-folder fallback can raise OrcaSlicer's permission prompt, so it only runs when the
        user pressed the button, never for an automatic reload."""
        meta = read_capture_meta()
        fresh_capture = meta and (not self.slice_done_at or meta["mtime"] >= self.slice_done_at - 30)
        if fresh_capture:
            return CAPTURE_FILE, meta["mtime"], meta.get("name") or "Latest slice", "capture", f"c{meta['mtime']:.3f}"
        temp = None
        try:
            temp = find_temp_gcode() if allow_temp else None
        except Exception:
            temp = None          # permission declined or nothing there
        if temp and (not meta or temp[1] > meta["mtime"]):
            stamp = f"s{self.slice_done_at:.3f}" if self.slice_done_at else f"t{temp[1]:.3f}"
            return temp[0], temp[1], "Latest slice", "temp", stamp
        if meta:
            return CAPTURE_FILE, meta["mtime"], meta.get("name") or "Latest slice", "capture", f"c{meta['mtime']:.3f}"
        return None

    def send_latest(self, quiet):
        try:
            # every load is a direct result of the user opening the tab or pressing the button,
            # so the temp-folder fallback (which may show OrcaSlicer's permission prompt) is fine
            src = self.pick_source(allow_temp=True)
            if not src:
                self.post({"cmd": "error", "quiet": quiet, "setup": True, "capture_enabled": False, "hint": SETUP_HINT,
                           "message": "No sliced G-code found yet. Slice a plate first"
                                      " (or set up Playback capture, see the tab)."})
                return
            path, mtime, name, how, stamp = src
            stable(path)
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            with self.lock:
                self.transfer_id += 1
                tid = self.transfer_id
            chunks = [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)] or [""]
            self.post({"cmd": "gcode_begin", "id": tid, "name": name, "size": len(text),
                       "chunks": len(chunks), "when": when_text(mtime), "source": how, "stamp": stamp})
            for index, part in enumerate(chunks):
                with self.lock:
                    if tid != self.transfer_id:
                        return            # a newer request superseded this one
                self.post({"cmd": "gcode_chunk", "id": tid, "i": index, "data": part})
            self.post({"cmd": "gcode_end", "id": tid, "reload": quiet})
        except PermissionError:
            latest = self.latest() or {}
            self.post({"cmd": "error", "quiet": False, "setup": True, "capture_enabled": False, "hint": SETUP_HINT,
                       "stamp": latest.get("stamp"),
                       "message": "OrcaSlicer did not allow reading the temporary G-code."
                                  " Set up Playback capture to load slices without asking."})
        except Exception as exc:
            self.post({"cmd": "error", "quiet": quiet, "message": f"Could not load the slice: {str(exc)[:240]}"})
        finally:
            self.loading = False


# --------------------------------------------------------------------------- #
# the capture step
# --------------------------------------------------------------------------- #
class PlaybackCapture(orca.slicing.SlicingPipelineCapabilityBase):
    """Copies the finished G-code into this plugin's folder. Read-only on the G-code itself."""

    def get_name(self):
        return CAPTURE_NAME

    def execute(self, ctx):
        if ctx.step != orca.slicing.Step.psGCodePostProcess:
            return orca.ExecutionResult.success()
        try:
            src = ctx.gcode_path
            if not src or not os.path.isfile(src):
                return orca.ExecutionResult.success("no G-code to capture")
            os.makedirs(CAPTURE_DIR, exist_ok=True)
            part = CAPTURE_FILE + ".part"
            with open(src, "rb") as reader, open(part, "wb") as writer:
                while True:
                    block = reader.read(1024 * 1024)
                    if not block:
                        break
                    writer.write(block)
            os.replace(part, CAPTURE_FILE)
            name = ctx.output_name or os.path.basename(src)
            for suffix in (".gcode.3mf", ".3mf", ".gcode"):
                if name.lower().endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            with open(CAPTURE_META + ".part", "w", encoding="utf-8") as handle:
                json.dump({"name": name, "host": ctx.host, "time": time.time()}, handle)
            os.replace(CAPTURE_META + ".part", CAPTURE_META)
            _CAPTURE_SEEN["t"] = time.time()
            page = _PAGE
            if page is not None:
                # post_message is thread-safe; never call orca.host.ui from this slicing thread
                payload = page.status("slice_ready")
                page.post(payload)
            return orca.ExecutionResult.success("captured for Playback")
        except Exception as exc:
            # never fail the slice because of playback
            return orca.ExecutionResult.success(f"Playback capture skipped: {str(exc)[:200]}")


@orca.plugin
class PlaybackPlugin(orca.base):
    def register_capabilities(self):
        orca.register_capability(PlaybackPage)
        orca.register_capability(PlaybackCapture)
