# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Real G-code Playback"
# description = "Real-time playback of the sliced G-code in its own tab: a motion-planned, accelerations-and-corners timeline of the print, synced to the slicer's own time estimate."
# author = "NickChung"
# version = "1.5.0"
# ///
"""Real G-code Playback — watch the sliced G-code print in real time, in an OrcaSlicer tab.

Changelog
---------
1.5.0 (2026-10-10)
  - Lines are drawn with their actual width and height from the G-code, so scarf seams, Z contouring and variable-width walls look as they print
  - Colour by line height or line width; the readout shows the current line's width × height
  - Rotating turns about the middle of the screen, at the print straight ahead, and can go straight overhead without flickering; the wheel zooms toward the cursor
  - Fixed zooming sometimes getting stuck until you clicked
  - A new slice keeps the camera and the time
1.4.3 (2026-10-09)
  - Fixed playback running far too fast in the first part of Bambu Lab prints with bed leveling (since 1.3.0)
1.4.2 (2026-10-09)
  - Pausing when you click another tab now works in OrcaSlicer
1.4.1 (2026-10-09)
  - Clearer setup instructions on the start screen
1.4.0 (2026-10-09)
  - Custom playback speed, including slow motion (0.1×, 0.25×, 0.5× or any value)
  - Option to keep playing when you leave the Playback tab
1.3.0 (2026-10-09)
  - Print options: choose bed leveling, flow calibration, timelapse and the other printer flags in the G-code; blocks the printer would skip are not drawn or timed
  - Bed leveling counts as 260 s, as in OrcaSlicer's estimate
1.2.1 (2026-10-09)
  - G-code panel keeps the running line centred while playing
  - G-code panel button moved to the front of the current line
1.2.0 (2026-10-09)
  - G-code panel: expand the current-line readout to scroll through the whole file; it follows playback, and clicking a line jumps to that moment
1.1.1 (2026-10-09)
  - Packaging aligned with the OrcaSlicer plugin rules for Orca Cloud upload
1.1.0 (2026-10-08)
  - Opening the tab loads a new slice automatically when nothing is loaded, and asks before replacing one that is
  - Playback pauses when you leave the tab
  - Shading options: round lit lines, layer contrast, height shading, flat colours
  - Hot end and gantry can be shown or hidden separately
  - Playback controls centred in the bottom bar
1.0.0 (2026-10-08)
  - Playback tab: real-time playback of the sliced G-code
  - Motion planner with acceleration and cornering, synced to the slicer's time estimate
  - Timeline with layer bands and filament change, pause and heating markers
  - Colour by line type, actual speed, set speed, volumetric flow, layer time or filament
  - Moving-bed view for bed slingers such as the A1 mini
  - Loads the latest slice, or a .gcode / .gcode.3mf file
  - Playback capture step for loading slices without permission prompts

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

Files this plugin writes: only inside its own folder (.captures/latest.gcode + latest.json, and
exports/ for videos and pictures when OrcaSlicer's page can't show a Save dialog).
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
# videos and pictures from the Export dialog, when the page can't open the system's Save dialog
EXPORT_DIR = os.path.join(PLUGIN_DIR, "exports")
EXPORT_EXTS = {".mp4", ".webm", ".gif", ".png", ".jpg", ".jpeg", ".webp"}
EXPORT_MAX = 4 * 1024 * 1024 * 1024

DEFAULT_PREFS = {"speed": 10, "color": "feature", "travel": False, "layerOnly": False, "follow": False,
                 "motion": "auto", "lines": "fat", "timing": "aligned", "head": True, "gantry": True, "shade": "tube", "flags": {}, "pauseOnLeave": True}

SETUP_HINT = {
    "title": "One-time setup for automatic loading",
    "steps": [
        "Open the <b>Process</b> settings and switch to <b>Advanced</b> mode.",
        "Go to <b>Others</b> → <b>Slicing Pipeline Plugin</b> and add <b>Playback capture</b>.",
        "Slice again. Bambu Lab printers are captured on every slice; other printers when you export or send.",
    ],
}

CHANGELOG = {
 "version": "1.5.0",
 "entries": [
  {
   "version": "1.5.0",
   "date": "2026-10-10",
   "changes": [
    "Lines are drawn with their actual width and height from the G-code, so scarf seams, Z contouring and variable-width walls look as they print",
    "Colour by line height or line width; the readout shows the current line's width × height",
    "Rotating turns about the middle of the screen, at the print straight ahead, and can go straight overhead without flickering; the wheel zooms toward the cursor",
    "Fixed zooming sometimes getting stuck until you clicked",
    "A new slice keeps the camera and the time"
   ]
  },
  {
   "version": "1.4.3",
   "date": "2026-10-09",
   "changes": [
    "Fixed playback running far too fast in the first part of Bambu Lab prints with bed leveling (since 1.3.0)"
   ]
  },
  {
   "version": "1.4.2",
   "date": "2026-10-09",
   "changes": [
    "Pausing when you click another tab now works in OrcaSlicer"
   ]
  },
  {
   "version": "1.4.1",
   "date": "2026-10-09",
   "changes": [
    "Clearer setup instructions on the start screen"
   ]
  },
  {
   "version": "1.4.0",
   "date": "2026-10-09",
   "changes": [
    "Custom playback speed, including slow motion (0.1×, 0.25×, 0.5× or any value)",
    "Option to keep playing when you leave the Playback tab"
   ]
  },
  {
   "version": "1.3.0",
   "date": "2026-10-09",
   "changes": [
    "Print options: choose bed leveling, flow calibration, timelapse and the other printer flags in the G-code; blocks the printer would skip are not drawn or timed",
    "Bed leveling counts as 260 s, as in OrcaSlicer's estimate"
   ]
  },
  {
   "version": "1.2.1",
   "date": "2026-10-09",
   "changes": [
    "G-code panel keeps the running line centred while playing",
    "G-code panel button moved to the front of the current line"
   ]
  },
  {
   "version": "1.2.0",
   "date": "2026-10-09",
   "changes": [
    "G-code panel: expand the current-line readout to scroll through the whole file; it follows playback, and clicking a line jumps to that moment"
   ]
  },
  {
   "version": "1.1.1",
   "date": "2026-10-09",
   "changes": [
    "Packaging aligned with the OrcaSlicer plugin rules for Orca Cloud upload"
   ]
  },
  {
   "version": "1.1.0",
   "date": "2026-10-08",
   "changes": [
    "Opening the tab loads a new slice automatically when nothing is loaded, and asks before replacing one that is",
    "Playback pauses when you leave the tab",
    "Shading options: round lit lines, layer contrast, height shading, flat colours",
    "Hot end and gantry can be shown or hidden separately",
    "Playback controls centred in the bottom bar"
   ]
  },
  {
   "version": "1.0.0",
   "date": "2026-10-08",
   "changes": [
    "Playback tab: real-time playback of the sliced G-code",
    "Motion planner with acceleration and cornering, synced to the slicer's time estimate",
    "Timeline with layer bands and filament change, pause and heating markers",
    "Colour by line type, actual speed, set speed, volumetric flow, layer time or filament",
    "Moving-bed view for bed slingers such as the A1 mini",
    "Loads the latest slice, or a .gcode / .gcode.3mf file",
    "Playback capture step for loading slices without permission prompts"
   ]
  }
 ]
}

# The live page capability, so the capture capability can tell the tab a new slice arrived.
_PAGE = None
_PAGE_HTML = None
_CAPTURE_SEEN = {"t": 0.0}          # when the capture capability last ran
SESSION_START = time.time()         # a capture older than this OrcaSlicer session is not "new"


# --------------------------------------------------------------------------- #
# page
# --------------------------------------------------------------------------- #
PAGE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Real G-code Playback</title>
<style>
:root {
  --bg: var(--orca-bg, #1e2023); --fg: var(--orca-fg, #e6e8ea); --muted: var(--orca-muted, #98a0a8);
  --border: var(--orca-border, #3a3e43); --accent: var(--orca-accent, #009688); --accent-fg: var(--orca-accent-fg, #fff);
  --ui: var(--orca-font, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif);
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --panel: color-mix(in srgb, var(--bg) 86%, #000 14%);
  --glass: color-mix(in srgb, var(--bg) 78%, transparent);
  --surface: rgba(127,137,142,.10); --surface-2: rgba(127,137,142,.18);
  --warn: #e0913a; --bad: #d9534f;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg); font: 12.5px/1.4 var(--ui); overflow: hidden; }
button, select, input { font: inherit; color: var(--fg); }
button { background: var(--surface); border: 1px solid transparent; border-radius: 7px; padding: 5px 10px; cursor: pointer;
         display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
button:hover:not(:disabled) { background: var(--surface-2); }
button:disabled { opacity: .45; cursor: default; }
button.primary { background: var(--accent); color: var(--accent-fg); }
button.primary:hover:not(:disabled) { filter: brightness(1.08); background: var(--accent); }
button.on { background: color-mix(in srgb, var(--accent) 24%, transparent); border-color: color-mix(in srgb, var(--accent) 70%, transparent); }
button.icon { padding: 5px 7px; }
select, input[type=number] { background: var(--bg); border: 1px solid var(--border); border-radius: 7px; padding: 4px 7px; }
select:focus, input:focus, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
svg { display: block; }
.sep { width: 1px; align-self: stretch; background: var(--border); margin: 2px 4px; }
.muted { color: var(--muted); }

#app { position: absolute; inset: 0; display: flex; flex-direction: column; }
#top { flex: none; display: flex; align-items: center; gap: 6px; padding: 7px 10px; border-bottom: 1px solid var(--border);
       background: var(--panel); flex-wrap: wrap; user-select: none; }
#file { display: flex; flex-direction: column; min-width: 0; max-width: 34ch; margin: 0 4px; }
#file b { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#file span { font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 10.5px; padding: 1px 7px; border-radius: 99px; background: var(--surface-2); color: var(--muted); }
.badge.ok { background: color-mix(in srgb, var(--accent) 22%, transparent); color: var(--fg); }
.grow { flex: 1; }
.group { display: flex; gap: 4px; align-items: center; }
label.inline { display: inline-flex; align-items: center; gap: 5px; color: var(--muted); font-size: 11.5px; }

#stage { position: relative; flex: 1; min-height: 0; }
#gl { position: absolute; inset: 0; width: 100%; height: 100%; display: block; outline: none; }
.overlay { position: absolute; pointer-events: none; }
#hud { left: 10px; top: 10px; background: var(--glass); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
       border: 1px solid var(--border); border-radius: 10px; padding: 9px 12px; min-width: 250px; pointer-events: auto; }
#hud .t { font: 600 20px/1.1 var(--mono); letter-spacing: -.01em; }
#hud .t small { font-size: 12px; color: var(--muted); font-weight: 400; }
#hud table { border-collapse: collapse; margin-top: 7px; font-size: 12px; }
#hud td { padding: 1.5px 0; vertical-align: baseline; }
#hud td:first-child { color: var(--muted); padding-right: 14px; white-space: nowrap; }
#hud td.v { font-family: var(--mono); font-size: 11.5px; }
#hud .dot { display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; border: 1px solid rgba(0,0,0,.25); }
#hud .srcRow { display: flex; align-items: center; gap: 6px; margin-top: 7px; }
#hud .src { flex: 1; font: 11px/1.35 var(--mono); color: var(--muted); max-width: 330px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#codeToggle { padding: 3px 5px; border-radius: 6px; }
#codeToggle svg { transition: transform .22s ease; }
#codeToggle[aria-expanded="true"] svg { transform: rotate(180deg); }
#codePanel { width: 0; min-width: 100%; max-width: calc(100vw - 60px); max-height: 0; opacity: 0; overflow: hidden;
             transition: max-height .28s cubic-bezier(.2,.7,.3,1), opacity .2s ease, margin-top .28s ease, width .28s cubic-bezier(.2,.7,.3,1); margin-top: 0; }
#codePanel.open { width: 440px; max-height: 330px; opacity: 1; margin-top: 8px; }
#codePanel .codeHead { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11px; margin-bottom: 5px; }
#codePanel .codeHead button { padding: 2px 9px; font-size: 11px; }
#codeScroll { position: relative; height: 288px; overflow-y: auto; overflow-x: hidden; border-radius: 8px;
              background: color-mix(in srgb, var(--bg) 70%, #000 30%); border: 1px solid var(--border);
              font: 11px/18px var(--mono); overscroll-behavior: contain; }
#codeScroll:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
#codeRows { position: absolute; left: 0; right: 0; top: 0; will-change: transform; }
#codeRows .ln { height: 18px; display: flex; gap: 10px; padding: 0 8px 0 0; cursor: pointer; white-space: pre; position: relative;
                transition: background-color .25s ease; }
#codeRows .ln:hover { background: var(--surface-2); }
#codeRows .ln .no { flex: none; width: 58px; text-align: right; color: var(--muted); opacity: .6; user-select: none; }
#codeRows .ln .tx { overflow: hidden; text-overflow: ellipsis; color: var(--fg); }
#codeRows .ln.past .tx { opacity: .55; }
#codeRows .ln.cur { background: color-mix(in srgb, var(--accent) 26%, transparent); }
#codeRows .ln.cur::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); }
#codeRows .ln.cur .no { opacity: 1; color: var(--fg); }
#codeRows .ln.flash { animation: lnflash .6s ease; }
@keyframes lnflash { 0% { background: color-mix(in srgb, var(--accent) 60%, transparent); } 100% { background: transparent; } }
#codeRows .c { color: var(--muted); font-style: italic; }
#codeRows .k { color: #5fb3ff; font-weight: 600; }
#codeRows .km { color: #e0a85a; font-weight: 600; }
#codeRows .a { color: #7fd0a8; }
@media (prefers-reduced-motion: reduce) { #codePanel, #codeToggle svg { transition: none; } }
#hud .bar { height: 4px; border-radius: 3px; background: var(--surface-2); margin-top: 3px; overflow: hidden; width: 120px; display: inline-block; vertical-align: middle; margin-left: 6px; }
#hud .bar i { display: block; height: 100%; background: var(--accent); width: 0; }
#legend { right: 10px; bottom: 10px; background: var(--glass); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
          border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; font-size: 11.5px; max-height: 60%; overflow: auto; pointer-events: auto; }
#legend h4 { margin: 0 0 5px; font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
#legend .row { display: flex; align-items: center; gap: 7px; padding: 1px 0; }
#legend .sw { width: 12px; height: 12px; border-radius: 3px; border: 1px solid rgba(0,0,0,.25); flex: none; }
#legend .grad { width: 160px; height: 10px; border-radius: 5px; }
#legend .ends { display: flex; justify-content: space-between; font-family: var(--mono); font-size: 10.5px; color: var(--muted); margin-top: 3px; }
#legend .row.off { opacity: .35; }
#legend .row.click { cursor: pointer; }
#viewbtns { right: 10px; top: 10px; display: flex; flex-direction: column; gap: 4px; pointer-events: auto; }
#viewbtns button { background: var(--glass); border: 1px solid var(--border); backdrop-filter: blur(8px); justify-content: center; min-width: 34px; font-size: 11px; }
#viewbtns button.on { border-color: var(--accent); }

#empty { inset: 0; display: grid; place-items: center; pointer-events: auto; background: var(--bg); overflow: auto; }
#empty .box { width: 100%; max-width: 520px; box-sizing: border-box; text-align: center; padding: 26px; }
#empty h2 { margin: 12px 0 6px; font-size: 17px; }
#empty p { color: var(--muted); margin: 0 0 14px; }
#empty .steps { text-align: left; background: var(--surface); border-radius: 10px; padding: 12px 14px; margin: 16px 0 6px;
                font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
#empty .steps[hidden] { display: none; }
#empty .steps .title { font-weight: 600; color: var(--fg); margin: 0 0 8px; }
#empty .steps .step { display: flex; align-items: flex-start; gap: 9px; margin: 6px 0 0; color: var(--fg); }
#empty .steps .num { flex: none; width: 19px; height: 19px; border-radius: 50%; display: grid; place-items: center;
                     background: color-mix(in srgb, var(--accent) 28%, transparent); font-size: 11px; font-weight: 700; line-height: 1; }
#empty .steps .txt { flex: 1; min-width: 0; padding-top: 1px; }
#empty .actions { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
#drop { inset: 0; display: none; place-items: center; background: color-mix(in srgb, var(--accent) 16%, transparent);
        border: 2px dashed var(--accent); font-size: 16px; font-weight: 600; pointer-events: none; }
#busy { inset: 0; display: none; place-items: center; background: color-mix(in srgb, var(--bg) 70%, transparent); pointer-events: auto; }
#busy .box { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; min-width: 280px; }
#busy .pb { height: 5px; background: var(--surface-2); border-radius: 3px; overflow: hidden; margin-top: 10px; }
#busy .pb i { display: block; height: 100%; background: var(--accent); width: 0; transition: width .1s; }
#toast { left: 50%; bottom: 14px; transform: translateX(-50%); background: var(--panel); border: 1px solid var(--border);
         border-radius: 9px; padding: 7px 13px; opacity: 0; transition: opacity .2s; max-width: 70%; }
#toast.show { opacity: 1; }
#toast.err { border-color: var(--bad); }
#newSlice { left: 50%; top: 10px; transform: translateX(-50%); z-index: 4; pointer-events: auto; display: flex; align-items: center; gap: 10px;
            background: var(--panel); border: 1px solid var(--accent); border-radius: 10px; padding: 7px 8px 7px 12px;
            box-shadow: 0 10px 28px rgba(0,0,0,.35); white-space: nowrap; }
#newSlice[hidden] { display: none; }
#optPanel { right: 10px; top: 8px; z-index: 5; pointer-events: auto; background: var(--panel); border: 1px solid var(--border);
            border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 9px; width: 290px;
            box-shadow: 0 10px 28px rgba(0,0,0,.35); }
#optPanel[hidden] { display: none; }
#optPanel label { display: flex; flex-direction: column; gap: 4px; font-size: 11.5px; color: var(--muted); }
#optPanel label.check { flex-direction: row; align-items: center; gap: 7px; color: var(--fg); font-size: 12px; }
#optPanel select { width: 100%; }
#optPanel { max-height: calc(100% - 20px); overflow-y: auto; }
#flagList { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 8px 0; }
#flagList[hidden] { display: none; }
#flagList .flagHead { font-size: 11.5px; color: var(--muted); }
#flagList .flagNote { font-size: 10.5px; color: var(--muted); }
#optPanel .about { border-top: 1px solid var(--border); padding-top: 8px; font-size: 11.5px; color: var(--muted); }
#optPanel .about a { color: var(--accent); text-decoration: none; }
#changelog { max-height: 260px; overflow: auto; font-size: 11.5px; }
#changelog h5 { margin: 8px 0 3px; font-size: 11.5px; }
#changelog h5 span { color: var(--muted); font-weight: 400; }
#changelog ul { margin: 0; padding-left: 16px; color: var(--muted); }
#changelog li { margin: 2px 0; }

#bottom { flex: none; border-top: 1px solid var(--border); background: var(--panel); padding: 6px 10px 8px; user-select: none; }
#tl { position: relative; height: 34px; cursor: pointer; margin-bottom: 6px; }
#tl canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
#tip { position: absolute; bottom: 38px; transform: translateX(-50%); background: var(--panel); border: 1px solid var(--border);
       border-radius: 7px; padding: 3px 8px; font: 11px var(--mono); white-space: nowrap; display: none; pointer-events: none; z-index: 3; }
#controls { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 10px; }
#controls .side { display: flex; align-items: center; gap: 8px; min-width: 0; }
#controls .side.right { justify-content: flex-end; }
#controls .transport { display: flex; align-items: center; gap: 5px; }
#controls .keys { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 980px) { #controls .keys { display: none; } }
#controls .time { font: 12px var(--mono); color: var(--muted); white-space: nowrap; text-align: right; }
#controls .time b { color: var(--fg); font-weight: 600; }
#play { width: 40px; justify-content: center; }
#layerIn { width: 66px; }
#speedCustomWrap { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-size: 11.5px; }
#speedCustomWrap[hidden] { display: none; }
#speedCustom { width: 72px; }
kbd { font: 10.5px var(--mono); background: var(--surface-2); border-radius: 4px; padding: 0 4px; }

/* export dialog */
#expDlg { inset: 0; z-index: 20; display: grid; place-items: center; pointer-events: auto;
          background: color-mix(in srgb, var(--bg) 55%, transparent); }
#expDlg[hidden] { display: none; }
#expDlg .box { width: min(420px, calc(100% - 32px)); max-height: calc(100% - 32px); overflow: auto; background: var(--panel);
               border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 12px 40px rgba(0,0,0,.35); padding: 12px 14px 12px; }
#expDlg .head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
#expDlg .head b { font-size: 13.5px; }
#expDlg .tabs { display: inline-flex; background: var(--surface); border-radius: 8px; padding: 2px; margin-right: auto; }
#expDlg .tabs button { border: 0; background: transparent; padding: 3px 12px; border-radius: 6px; }
#expDlg .tabs button.on { background: var(--surface-2); color: var(--fg); }
#expDlg .row { display: flex; align-items: center; gap: 10px; margin: 7px 0; min-width: 0; }
#expDlg .row[hidden] { display: none; }
#expDlg .row .k { flex: none; width: 76px; color: var(--muted); }
#expDlg .row > select { flex: 1; min-width: 0; }
#expDlg .row.sub { margin-top: -2px; }
#expDlg .pair { flex: 1; min-width: 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; color: var(--muted); }
#expDlg .pair.stack { flex-direction: column; align-items: stretch; }
#expDlg .pair input[type=number] { width: 72px; }
#expDlg .pair input[type=text] { width: 82px; background: var(--bg); border: 1px solid var(--border); border-radius: 7px; padding: 4px 7px; font-family: var(--mono); }
#expDlg .pair input.bad { border-color: var(--bad); }
#expDlg .radios { display: flex; flex-direction: column; gap: 4px; }
#expDlg .radios label { display: flex; align-items: center; gap: 6px; }
#expDlg .sum { margin: 10px 0 0; padding: 8px 10px; background: var(--surface); border-radius: 8px; color: var(--muted); font-size: 11.5px; line-height: 1.5; }
#expDlg .sum b { color: var(--fg); font-weight: 600; }
#expDlg .sum .warn { color: var(--warn); }
#expDlg .prog { margin-top: 10px; display: flex; flex-direction: column; gap: 5px; font-size: 11.5px; color: var(--muted); }
#expDlg .prog[hidden] { display: none; }
#expDlg .pb { height: 5px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
#expDlg .pb i { display: block; height: 100%; background: var(--accent); width: 0; }
#expDlg .foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
#expDlg .result { margin-top: 10px; padding: 8px 10px; border-radius: 8px; background: color-mix(in srgb, var(--accent) 16%, transparent); font-size: 11.5px; }
#expDlg .result[hidden] { display: none; }
#expDlg .result.err { background: color-mix(in srgb, var(--bad) 18%, transparent); color: var(--fg); }
#expDlg .pathRow { display: flex; align-items: center; gap: 8px; margin-top: 5px; }
#expDlg .pathRow code { flex: 1; min-width: 0; font: 11px/1.35 var(--mono); word-break: break-all; user-select: text; }
#expDlg .pathRow code[hidden], #expDlg .pathRow button[hidden] { display: none; }
#expBtn svg { vertical-align: -1px; }
</style>
</head>
<body>
<div id="app">
  <div id="top">
    <button id="btnLatest" class="primary" title="Load the G-code OrcaSlicer produced for the last slice">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></svg>
      Latest slice</button>
    <button id="btnOpen" title="Open a .gcode or .gcode.3mf file">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
      Open…</button>
    <input type="file" id="file-in" accept=".gcode,.gco,.g,.3mf,.txt" hidden>
    <select id="plateSel" title="Plate" hidden></select>
    <div id="file"><b id="fileName">No G-code loaded</b><span id="fileInfo">Slice a plate, then press Latest slice</span></div>
    <span id="timingBadge" class="badge" hidden></span>
    <div class="grow"></div>
    <label class="inline">Color
      <select id="colorSel">
        <option value="feature">Line type</option>
        <option value="speed">Actual speed</option>
        <option value="fcmd">Set speed</option>
        <option value="flow">Volumetric flow</option>
        <option value="beadh">Line height</option>
        <option value="beadw">Line width</option>
        <option value="layertime">Layer time</option>
        <option value="filament">Filament</option>
      </select></label>
    <div class="sep"></div>
    <div class="group">
      <button id="tTravel" title="Show travel moves of the current layer (T)">Travel</button>
      <button id="tLayer" title="Show only the layer being printed (L)">Layer only</button>
      <button id="tFollow" title="Keep the camera on the nozzle (F)">Follow</button>
      <button id="expBtn" title="Export a video or an image (E)" disabled>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/></svg>
        Export</button>
      <button id="optBtn" title="More options">Options
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button>
    </div>
  </div>

  <div id="stage">
    <canvas id="gl" tabindex="0"></canvas>
    <div id="hud" class="overlay" hidden>
      <div class="t"><span id="hTime">0:00</span> <small>/ <span id="hTotal">0:00</span></small></div>
      <table>
        <tr><td>Layer</td><td class="v"><span id="hLayer">–</span><span class="bar"><i id="hLayerBar"></i></span></td></tr>
        <tr><td>Z</td><td class="v" id="hZ">–</td></tr>
        <tr><td>Line type</td><td id="hFeat">–</td></tr>
        <tr><td>Speed</td><td class="v"><span id="hSpeed">–</span> <span class="muted" id="hSpeedSet"></span></td></tr>
        <tr><td>Flow</td><td class="v" id="hFlow">–</td></tr>
        <tr><td>Line</td><td class="v" id="hBead" title="Width × height of the line being printed, from the G-code">–</td></tr>
        <tr><td>Accel</td><td class="v" id="hAcc">–</td></tr>
        <tr><td>Filament</td><td id="hTool">–</td></tr>
        <tr><td>Remaining</td><td class="v" id="hRemain">–</td></tr>
      </table>
      <div class="srcRow">
        <button class="icon" id="codeToggle" aria-expanded="false" aria-controls="codePanel" title="Show the G-code (G)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></button>
        <div class="src" id="hSrc"></div>
      </div>
      <div id="codePanel" aria-hidden="true">
        <div class="codeHead">
          <span id="codeInfo" class="muted"></span>
          <button id="codeFollow" class="on" title="Keep the running line in view">Follow</button>
        </div>
        <div id="codeScroll" tabindex="0" aria-label="G-code; click a line to jump to it">
          <div id="codeSpacer"></div>
          <div id="codeRows"></div>
        </div>
      </div>
    </div>
    <div id="viewbtns" class="overlay" hidden>
      <button id="vIso" title="Isometric view">Iso</button>
      <button id="vTop" title="Top view">Top</button>
      <button id="vFront" title="Front view">Front</button>
      <button id="vFit" title="Frame the print">Fit</button>
    </div>
    <div id="legend" class="overlay" hidden></div>
    <div id="empty" class="overlay">
      <div class="box">
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" style="margin:0 auto;opacity:.55">
          <path d="M10 44 L32 54 L54 44 L32 34 Z" fill="currentColor" fill-opacity=".15"/>
          <path d="M10 37 L32 47 L54 37"/><path d="M10 30 L32 40 L54 30"/>
          <path d="M27 9 L42 18 L27 27 Z" fill="currentColor" fill-opacity=".35"/>
        </svg>
        <h2>Watch your print in real time</h2>
        <p>Plays the sliced G-code with the timing a printer would take — accelerations, corners and all.</p>
        <div class="actions">
          <button class="primary" id="eLatest">Load latest slice</button>
          <button id="eOpen">Open a G-code file…</button>
        </div>
        <div class="steps" id="setupSteps" hidden></div>
        <p style="margin-top:10px;font-size:11.5px">You can also drop a <b>.gcode</b> or <b>.gcode.3mf</b> file here.</p>
      </div>
    </div>
    <div id="drop" class="overlay">Drop G-code to play it</div>
    <div id="expDlg" class="overlay" hidden>
      <div class="box" role="dialog" aria-modal="true" aria-labelledby="expTitle">
        <div class="head">
          <b id="expTitle">Export</b>
          <div class="tabs" role="tablist">
            <button role="tab" id="xTabVideo" class="on" aria-selected="true">Video</button>
            <button role="tab" id="xTabImage" aria-selected="false">Image</button>
          </div>
          <button class="icon" id="xClose" title="Close (Esc)" aria-label="Close">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
        </div>
        <div id="xVideo" class="pane">
          <div class="row"><span class="k">Range</span>
            <select id="xRange">
              <option value="all">Whole print</option>
              <option value="layer">Current layer</option>
              <option value="layers">Layers…</option>
              <option value="events">Between events…</option>
              <option value="time">Custom time…</option>
            </select></div>
          <div class="row sub" id="xLayersRow" hidden><span class="k"></span>
            <span class="pair">from <input type="number" id="xL0" min="1" step="1"> to <input type="number" id="xL1" min="1" step="1"></span></div>
          <div class="row sub" id="xEventsRow" hidden><span class="k"></span>
            <span class="pair stack"><select id="xEv0" aria-label="Start event"></select><select id="xEv1" aria-label="End event"></select></span></div>
          <div class="row sub" id="xTimeRow" hidden><span class="k"></span>
            <span class="pair"><input type="text" id="xT0" spellcheck="false" aria-label="Start time"> to <input type="text" id="xT1" spellcheck="false" aria-label="End time">
              <button id="xNow" title="Start at the current playback time">Now</button></span></div>
          <div class="row"><span class="k">Format</span>
            <select id="xFmt">
              <option value="mp4">MP4</option>
              <option value="webm">WebM</option>
              <option value="gif">GIF</option>
            </select></div>
          <div class="row"><span class="k">Speed</span>
            <select id="xSpeed">
              <option value="1">1× (real time)</option><option value="2">2×</option><option value="5">5×</option><option value="10">10×</option>
              <option value="25">25×</option><option value="50">50×</option><option value="100">100×</option><option value="250">250×</option>
              <option value="500">500×</option><option value="1000">1000×</option>
              <option value="fit15">Fit into 15 s</option><option value="fit30">Fit into 30 s</option><option value="fit60">Fit into 1 min</option>
            </select></div>
          <div class="row"><span class="k">Size</span>
            <select id="xSize">
              <option value="window">Window</option><option value="480">480p</option><option value="720">720p</option>
              <option value="1080">1080p</option><option value="1440">1440p</option><option value="2160">4K</option>
            </select></div>
          <div class="row"><span class="k">Frame rate</span>
            <select id="xFps"><option value="15">15 fps</option><option value="24">24 fps</option><option value="30">30 fps</option><option value="60">60 fps</option></select></div>
        </div>
        <div id="xImage" class="pane" hidden>
          <div class="row"><span class="k">Content</span>
            <span class="radios">
              <label><input type="radio" name="xWhat" value="render" checked> 3D view only</label>
              <label><input type="radio" name="xWhat" value="window"> Whole window, with panels</label>
            </span></div>
          <div class="row"><span class="k">Format</span>
            <select id="xImgFmt"><option value="png">PNG</option><option value="jpeg">JPEG</option><option value="webp">WebP</option></select></div>
          <div class="row"><span class="k">Size</span>
            <select id="xImgSize"><option value="1">Window</option><option value="2">2× window</option><option value="2160">4K</option></select></div>
        </div>
        <div class="sum" id="xSum"></div>
        <div class="prog" id="xProg" hidden><div class="pb"><i id="xBar"></i></div><span id="xProgText"></span></div>
        <div class="result" id="xResult" hidden>
          <div id="xResultText"></div>
          <div class="pathRow"><code id="xResultPath" hidden></code><button id="xCopy" hidden>Copy path</button></div>
        </div>
        <div class="foot">
          <button id="xCancel">Cancel</button>
          <button class="primary" id="xGo">Export</button>
        </div>
      </div>
    </div>
    <div id="busy" class="overlay"><div class="box"><div id="busyText">Loading…</div><div class="pb"><i id="busyBar"></i></div></div></div>
    <div id="toast" class="overlay"></div>
    <div id="newSlice" class="overlay" hidden>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></svg>
      <span><b>A newer slice is available</b> <span class="muted" id="newSliceWhen"></span></span>
      <button class="primary" id="nsLoad">Load it</button>
      <button id="nsKeep">Keep current</button>
    </div>
    <div id="optPanel" class="overlay" hidden>
      <label>Printer motion
        <select id="motionSel">
          <option value="auto">Auto (from printer profile)</option>
          <option value="bed">Bed moves in Y (A1, A1 mini, i3)</option>
          <option value="head">Head moves in XY (CoreXY)</option>
        </select></label>
      <label>Line style
        <select id="lineSel">
          <option value="fat">Actual cross-section (width × height from the G-code)</option>
          <option value="uniform">Uniform width</option>
          <option value="thin">Thin lines (faster on huge prints)</option>
        </select></label>
      <label>Timing
        <select id="timingSel">
          <option value="aligned">Match the slicer's time estimate</option>
          <option value="planner">Motion planner only</option>
        </select></label>
      <label>Shading
        <select id="shadeSel">
          <option value="tube">Round lines (lit)</option>
          <option value="layers">Round lines + layer contrast</option>
          <option value="height">Height shading</option>
          <option value="flat">Flat colours</option>
        </select></label>
      <div id="flagList" hidden></div>
      <label class="check"><input type="checkbox" id="headChk"> Show the hot end</label>
      <label class="check"><input type="checkbox" id="gantryChk"> Show the gantry</label>
      <label class="check" title="Pauses when you click another tab or another window takes the focus"><input type="checkbox" id="pauseLeaveChk"> Pause when leaving the Playback tab</label>
      <div class="about"><span id="verText">Playback</span> · <a href="#" id="logLink">What's new</a></div>
      <div id="changelog" hidden></div>
    </div>
  </div>

  <div id="bottom">
    <div id="tl"><canvas id="tlc"></canvas><div id="tip"></div></div>
    <div id="controls">
      <div class="side left">
        <label class="inline">Speed
          <select id="speedSel" title="Playback speed (− / +)">
            <option value="0.1">0.1×</option><option value="0.25">0.25×</option><option value="0.5">0.5×</option>
            <option value="1">1×</option><option value="2">2×</option><option value="5">5×</option><option value="10">10×</option>
            <option value="25">25×</option><option value="50">50×</option><option value="100">100×</option><option value="250">250×</option>
            <option value="500">500×</option><option value="1000">1000×</option><option value="2500">2500×</option>
            <option value="custom">Custom…</option>
          </select></label>
        <span id="speedCustomWrap" class="inline" hidden>
          <input type="number" id="speedCustom" min="0.01" max="10000" step="any" aria-label="Custom playback speed">×
        </span>
        <label class="inline">Layer <input type="number" id="layerIn" min="1" step="1"></label>
      </div>
      <div class="transport">
      <button class="icon" id="bStart" title="Start (Home)"><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="5" width="2.6" height="14" rx="1"/><path d="M20 5.5v13a1 1 0 0 1-1.5.86L8.5 13a1.1 1.1 0 0 1 0-1.9l10-6.4A1 1 0 0 1 20 5.5z"/></svg></button>
      <button class="icon" id="bPrevL" title="Previous layer (↓)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 6l-6 6 6 6"/><path d="M19 6l-6 6 6 6"/></svg></button>
      <button class="icon" id="bPrevM" title="Previous move (←)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg></button>
      <button class="primary" id="play" title="Play / pause (Space)"><svg id="playIco" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg></button>
      <button class="icon" id="bNextM" title="Next move (→)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg></button>
      <button class="icon" id="bNextL" title="Next layer (↑)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6l6 6-6 6"/><path d="M13 6l6 6-6 6"/></svg></button>
      <button class="icon" id="bEnd" title="End (End)"><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="17.4" y="5" width="2.6" height="14" rx="1"/><path d="M4 5.5v13a1 1 0 0 0 1.5.86l10-6.4a1.1 1.1 0 0 0 0-1.9l-10-6.4A1 1 0 0 0 4 5.5z"/></svg></button>
      </div>
      <div class="side right">
        <span class="muted keys" title="Keyboard"><kbd>Space</kbd> play <kbd>←→</kbd> move <kbd>↑↓</kbd> layer <kbd>±</kbd> speed <kbd>G</kbd> G-code</span>
        <div class="time"><b id="cTime">0:00</b> / <span id="cTotal">0:00</span> · <span id="cPct">0%</span></div>
      </div>
    </div>
  </div>
</div>

<script>/*@@VENDOR@@*/</script>
<script>window.PLAYBACK_ABOUT = {"version": "1.5.0", "entries": [{"version": "1.5.0", "date": "2026-10-10", "changes": ["Lines are drawn with their actual width and height from the G-code, so scarf seams, Z contouring and variable-width walls look as they print", "Colour by line height or line width; the readout shows the current line's width × height", "Rotating turns about the middle of the screen, at the print straight ahead, and can go straight overhead without flickering; the wheel zooms toward the cursor", "Fixed zooming sometimes getting stuck until you clicked", "A new slice keeps the camera and the time"]}, {"version": "1.4.3", "date": "2026-10-09", "changes": ["Fixed playback running far too fast in the first part of Bambu Lab prints with bed leveling (since 1.3.0)"]}, {"version": "1.4.2", "date": "2026-10-09", "changes": ["Pausing when you click another tab now works in OrcaSlicer"]}, {"version": "1.4.1", "date": "2026-10-09", "changes": ["Clearer setup instructions on the start screen"]}, {"version": "1.4.0", "date": "2026-10-09", "changes": ["Custom playback speed, including slow motion (0.1×, 0.25×, 0.5× or any value)", "Option to keep playing when you leave the Playback tab"]}, {"version": "1.3.0", "date": "2026-10-09", "changes": ["Print options: choose bed leveling, flow calibration, timelapse and the other printer flags in the G-code; blocks the printer would skip are not drawn or timed", "Bed leveling counts as 260 s, as in OrcaSlicer's estimate"]}, {"version": "1.2.1", "date": "2026-10-09", "changes": ["G-code panel keeps the running line centred while playing", "G-code panel button moved to the front of the current line"]}, {"version": "1.2.0", "date": "2026-10-09", "changes": ["G-code panel: expand the current-line readout to scroll through the whole file; it follows playback, and clicking a line jumps to that moment"]}, {"version": "1.1.1", "date": "2026-10-09", "changes": ["Packaging aligned with the OrcaSlicer plugin rules for Orca Cloud upload"]}, {"version": "1.1.0", "date": "2026-10-08", "changes": ["Opening the tab loads a new slice automatically when nothing is loaded, and asks before replacing one that is", "Playback pauses when you leave the tab", "Shading options: round lit lines, layer contrast, height shading, flat colours", "Hot end and gantry can be shown or hidden separately", "Playback controls centred in the bottom bar"]}, {"version": "1.0.0", "date": "2026-10-08", "changes": ["Playback tab: real-time playback of the sliced G-code", "Motion planner with acceleration and cornering, synced to the slicer's time estimate", "Timeline with layer bands and filament change, pause and heating markers", "Colour by line type, actual speed, set speed, volumetric flow, layer time or filament", "Moving-bed view for bed slingers such as the A1 mini", "Loads the latest slice, or a .gcode / .gcode.3mf file", "Playback capture step for loading slices without permission prompts"]}]};
/* Playback core: G-code parser + motion planner. Pure JS, no DOM, so it runs in node for tests.
 *
 * parseGcode(text, opts) -> Job
 *   Job.moves        number of moves (move i goes from point i to point i+1)
 *   Job.pts          Float32Array, (moves+1)*3 xyz
 *   Job.flags        Uint8Array   FL_* bits per move
 *   Job.feat         Uint8Array   feature id per move (see FEATURES)
 *   Job.layer        Uint32Array  layer index per move
 *   Job.tool         Uint8Array   tool / filament index per move
 *   Job.fcmd         Float32Array commanded feedrate (mm/s)
 *   Job.len          Float32Array path length (mm; E length for E-only moves)
 *   Job.de           Float32Array extruder delta (mm of filament)
 *   Job.acc          Float32Array acceleration in force for the move (mm/s^2)
 *   Job.wait         Float32Array fixed duration for dwell pseudo-moves (s)
 *   Job.line         Uint32Array  1-based source line number
 *   Job.hnom         Float32Array nominal line height from the slicer's HEIGHT tag in force (0 = none)
 *   Job.beadW/beadH  Float32Array actual line width / height of each extrusion (mm), from the G-code
 *   Job.layers       [{z, h, first}]   first = first move index of the layer
 *   Job.events       [{move, kind, label}]
 *   Job.m73          [{move, p}]        Orca/Bambu progress markers (percent of time)
 *   Job.config       {key: value}       slicer config found in comments
 *   Job.estimate     seconds | 0        slicer's own total estimate from the header
 *   Job.machine      resolved machine limits used by the planner
 *
 * planJob(job, {align}) adds timing:
 *   Job.t0   Float64Array start time per move (aligned to the slicer estimate when available)
 *   Job.dur  Float32Array duration per move (aligned)
 *   Job.vi / vp / vf / ac  trapezoid (entry, peak, exit, accel) in planner time
 *   Job.total total time, Job.plannerTotal raw planner total, Job.aligned bool
 */
(function (root) {
  'use strict';

  const FL_EXTRUDE = 1, FL_TRAVEL = 2, FL_EONLY = 4, FL_DWELL = 8, FL_ARC = 16, FL_STOP = 32, FL_SKIP = 64;

  /* Bambu-style conditional blocks: `M1002 judge_flag NAME` + `M622 J1|J0` … `M623`. The printer decides
     at print time from the options chosen when sending; the viewer lets the user choose instead.
     Defaults follow the usual send-dialog choices; anything else uses the file's own M622.1 default. */
  const FLAG_INFO = {
    g29_before_print_flag: { label: 'Bed leveling', def: true },
    extrude_cali_flag: { label: 'Flow dynamics calibration', def: true },
    timelapse_record_flag: { label: 'Timelapse', def: false },
    build_plate_detect_flag: { label: 'Build plate detection', def: true },
    g39_3rd_layer_detect_flag: { label: 'Nozzle clumping detection (layer 3)' },
    g39_detection_flag: { label: 'Nozzle clumping detection' },
    g39_mass_exceed_flag: { label: 'Clumping check: mass exceeded' },
    filament_need_cali_flag: { label: 'Calibrate after filament change' },
    last_extrude_cali_success: { label: 'Last flow calibration succeeded', def: true },
  };
  function flagLabel(name) { return (FLAG_INFO[name] && FLAG_INFO[name].label) || name.replace(/_flag$/, '').replace(/_/g, ' '); }

  // Canonical features. Colours follow OrcaSlicer's preview defaults so the two views read alike.
  const FEATURES = [
    ['Other', '#9aa3ab'],
    ['Inner wall', '#ffe64d'],
    ['Outer wall', '#ff7d38'],
    ['Overhang wall', '#0000ff'],
    ['Sparse infill', '#b03029'],
    ['Internal solid infill', '#9654cc'],
    ['Top surface', '#f04040'],
    ['Bottom surface', '#669999'],
    ['Bridge', '#4d80ba'],
    ['Gap infill', '#ffffff'],
    ['Skirt', '#00876e'],
    ['Brim', '#00876e'],
    ['Support', '#00ff00'],
    ['Support interface', '#008000'],
    ['Support transition', '#004000'],
    ['Prime tower', '#b3e3ab'],
    ['Ironing', '#ff8c69'],
    ['Custom', '#5ed194'],
    ['Flush / purge', '#c7a26b'],
  ];
  const FEAT_INDEX = {};
  FEATURES.forEach((f, i) => { FEAT_INDEX[f[0].toLowerCase()] = i; });
  const FEAT_ALIASES = {
    'perimeter': 1, 'internal perimeter': 1, 'inner wall': 1,
    'external perimeter': 2, 'outer wall': 2,
    'overhang perimeter': 3, 'overhang wall': 3,
    'internal infill': 4, 'sparse infill': 4, 'infill': 4, 'fill': 4,
    'solid infill': 5, 'internal solid infill': 5,
    'top solid infill': 6, 'top surface': 6, 'top': 6,
    'bottom surface': 7, 'bottom solid infill': 7, 'bottom': 7,
    'bridge infill': 8, 'bridge': 8, 'internal bridge': 8, 'internal bridge infill': 8,
    'gap fill': 9, 'gap infill': 9, 'gapfill': 9,
    'skirt': 10, 'skirt/brim': 10, 'brim': 11,
    'support': 12, 'support material': 12,
    'support interface': 13, 'support material interface': 13,
    'support transition': 14,
    'prime tower': 15, 'wipe tower': 15,
    'ironing': 16,
    'custom': 17,
  };
  function featureId(name) {
    const k = String(name || '').trim().toLowerCase();
    if (k in FEAT_ALIASES) return FEAT_ALIASES[k];
    if (k in FEAT_INDEX) return FEAT_INDEX[k];
    if (k.indexOf('support') >= 0) return k.indexOf('interface') >= 0 ? 13 : 12;
    if (k.indexOf('wall') >= 0 || k.indexOf('perimeter') >= 0) return 1;
    if (k.indexOf('infill') >= 0) return 4;
    if (k.indexOf('tower') >= 0) return 15;
    return 0;
  }

  /* ---------------------------------------------------------------- growable typed arrays */
  function Grow(Type, cap) { this.T = Type; this.a = new Type(cap); this.n = 0; }
  Grow.prototype.ensure = function (n) {
    if (n <= this.a.length) return;
    let c = this.a.length * 2; while (c < n) c *= 2;
    const b = new this.T(c); b.set(this.a); this.a = b;
  };
  Grow.prototype.out = function (n) { return this.a.slice(0, n); };

  /* ---------------------------------------------------------------- helpers */
  function num(v, d) { const x = parseFloat(v); return isFinite(x) ? x : d; }
  function first(v, d) {           // "500,200" -> 500 ; "[500, 200]" -> 500
    if (v == null) return d;
    const s = String(v).replace(/[\[\]"']/g, '').split(/[,;]/)[0];
    return num(s, d);
  }
  function parseDuration(s) {      // "1d 2h 3m 4s" / "2h3m" / "45s"
    if (!s) return 0;
    let t = 0, hit = false; const re = /(\d+(?:\.\d+)?)\s*([dhms])/gi; let m;
    while ((m = re.exec(s))) { hit = true; t += parseFloat(m[1]) * ({ d: 86400, h: 3600, m: 60, s: 1 })[m[2].toLowerCase()]; }
    return hit ? t : 0;
  }

  /* ---------------------------------------------------------------- parser */
  function parseGcode(text, opts) {
    opts = opts || {};
    const progress = opts.progress || null;
    const est = Math.max(1024, (text.length / 30) | 0);
    const P = new Grow(Float32Array, (est + 1) * 3);
    const G = {
      flags: new Grow(Uint8Array, est), feat: new Grow(Uint8Array, est), layer: new Grow(Uint32Array, est),
      tool: new Grow(Uint8Array, est), fcmd: new Grow(Float32Array, est), len: new Grow(Float32Array, est),
      de: new Grow(Float32Array, est), acc: new Grow(Float32Array, est), wait: new Grow(Float32Array, est),
      line: new Grow(Uint32Array, est), hn: new Grow(Float32Array, est),
    };
    let n = 0;                                   // move count
    const config = {}; const layers = []; const events = []; const m73 = [];
    let estimate = 0, estimateSilent = 0;

    // machine state
    let x = 0, y = 0, z = 0, e = 0;              // logical (G92-adjusted) coordinates
    let ox = 0, oy = 0, oz = 0;                   // G92 offsets for xyz
    let absXYZ = true, absE = true, fmm = 3000 / 60; // feed in mm/s
    let accPrint = 0, accTravel = 0, accRetract = 0;  // filled from config after the scan
    let curFeat = 0, curTool = 0, curLayer = 0, curH = 0;
    // Slicer layer markers, when present, are the truth; otherwise layers are inferred from Z.
    let haveLayerComments = /^;\s*(LAYER_CHANGE|CHANGE_LAYER)\s*$/m.test(text.length > 4e6 ? text.substring(0, 4e6) : text);
    let lastExtrudeZ = -1e9, lastExtrudeMove = 0;
    if (haveLayerComments) layers.push({ z: 0, h: 0, first: 0, start: true });   // start G-code, before layer 1
    let pendingStop = false;                     // a blocking command happened since the last move
    // conditional blocks
    const flagChoices = opts.flags || {};
    const flagsFound = {};                       // name -> { name, label, value, fileDefault, count }
    const blockStack = [];                       // true = this block runs
    let judged = true, nextDefault = null, skipping = false, saved = null, g29Window = false, skippedMoves = 0;
    const isBambu = text.indexOf('M1002 ') >= 0 || text.indexOf('M622 ') >= 0;
    function judge(name) {
      let def = nextDefault != null ? nextDefault : (FLAG_INFO[name] && FLAG_INFO[name].def != null ? FLAG_INFO[name].def : true);
      if (FLAG_INFO[name] && FLAG_INFO[name].def != null) def = FLAG_INFO[name].def;
      const value = name in flagChoices ? !!flagChoices[name] : def;
      const f = flagsFound[name] || (flagsFound[name] = { name, label: flagLabel(name), value, fileDefault: def, count: 0 });
      f.count++;
      nextDefault = null; judged = value;
    }
    function updateSkipping() {
      const now = blockStack.some(b => !b);
      if (now && !skipping) {
        // entering a block the printer will not run: remember the real machine state
        saved = { x, y, z, e, ox, oy, oz, absXYZ, absE, fmm, accPrint, accTravel, accRetract, curFeat, curTool,
                  px: P.a[n * 3], py: P.a[n * 3 + 1], pz: P.a[n * 3 + 2] };
        pendingStop = true;
      } else if (!now && skipping && saved) {
        // leaving it: put the head back where it really is (a zero-time, undrawn hop)
        const hx = P.a[n * 3], hy = P.a[n * 3 + 1], hz = P.a[n * 3 + 2];
        if (hx !== saved.px || hy !== saved.py || hz !== saved.pz) {
          const L = Math.hypot(saved.px - hx, saved.py - hy, saved.pz - hz);
          skipping = true; push(saved.px, saved.py, saved.pz, FL_TRAVEL, 0, fmm, L, 0, lineNo);
        }
        ({ x, y, z, e, ox, oy, oz, absXYZ, absE, fmm, accPrint, accTravel, accRetract, curFeat, curTool } = saved);
        saved = null; pendingStop = true;
      }
      skipping = now;
    }
    function addEvent(ev) { if (!skipping) events.push(ev); }
    const machineCmd = {};                       // limits set by M201/M203/M205/SET_VELOCITY_LIMIT

    P.ensure(3); P.a[0] = 0; P.a[1] = 0; P.a[2] = 0;
    let started = false;                         // first real XY position seen

    function push(nx, ny, nz, flags, dE, fcmd, length, waitS, lineNo) {
      if (n + 1 >= G.flags.a.length) for (const k in G) G[k].ensure(n + 2);
      P.ensure((n + 2) * 3);
      const p = (n + 1) * 3; P.a[p] = nx; P.a[p + 1] = ny; P.a[p + 2] = nz;
      if (pendingStop) { flags |= FL_STOP; pendingStop = false; }
      if (skipping) { flags |= FL_SKIP; skippedMoves++; }
      G.flags.a[n] = flags; G.feat.a[n] = curFeat; G.layer.a[n] = curLayer < 0 ? 0 : curLayer;
      G.tool.a[n] = curTool; G.fcmd.a[n] = fcmd; G.len.a[n] = length; G.de.a[n] = dE;
      G.acc.a[n] = (flags & FL_EXTRUDE) ? accPrint : (flags & FL_EONLY) ? (accRetract || accPrint) : (accTravel || accPrint);
      G.wait.a[n] = waitS; G.line.a[n] = lineNo; G.hn.a[n] = curH;
      n++;
    }
    function startLayer(zv, hv) {
      curLayer = layers.length;
      layers.push({ z: zv, h: hv || 0, first: n });
    }
    function phys(i) { return P.a[n * 3 + i]; }

    function linearMove(tx, ty, tz, dE, lineNo, arcFlag) {
      const cx = phys(0), cy = phys(1), cz = phys(2);
      const dx = tx - cx, dy = ty - cy, dz = tz - cz;
      const L = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (L < 1e-6) {
        if (Math.abs(dE) > 1e-7) push(cx, cy, cz, FL_EONLY, dE, fmm, Math.abs(dE), 0, lineNo);
        return;
      }
      let fl = (dE > 1e-7 && (dx * dx + dy * dy) > 1e-12) ? FL_EXTRUDE : FL_TRAVEL;
      if (arcFlag) fl |= FL_ARC;
      if (fl & FL_EXTRUDE) {
        // a layer is wherever extrusion happens at a new height, when the slicer gave us no markers
        if (!skipping) {
          if (!haveLayerComments && tz > lastExtrudeZ + 0.015) { startLayer(tz, layers.length ? tz - lastExtrudeZ : tz); }
          lastExtrudeZ = Math.max(lastExtrudeZ, tz); lastExtrudeMove = n + 1;
        }
      }
      push(tx, ty, tz, fl, dE, fmm, L, 0, lineNo);
    }

    let i = 0, lineNo = 0; const len = text.length;
    let nextReport = 200000;
    const word = { G: NaN, M: NaN, X: NaN, Y: NaN, Z: NaN, E: NaN, F: NaN, I: NaN, J: NaN, R: NaN, P: NaN, S: NaN, T: NaN, L: NaN };

    while (i < len) {
      let j = text.indexOf('\n', i); if (j < 0) j = len;
      lineNo++;
      let line = text.substring(i, j);
      i = j + 1;
      if (progress && i > nextReport) { nextReport += 200000; progress(i / len); }

      // ---- comments
      let c = line.indexOf(';');
      let comment = null;
      if (c >= 0) { comment = line.substring(c + 1); line = line.substring(0, c); }
      if (comment !== null) {
        const t = comment.trim();
        if (t.length) {
          let m;
          if ((m = /^TYPE:\s*(.+)$/.exec(t)) || (m = /^FEATURE:\s*(.+)$/.exec(t))) {
            curFeat = featureId(m[1]);
          } else if (t === 'LAYER_CHANGE' || t === 'CHANGE_LAYER') {
            if (!haveLayerComments) { haveLayerComments = true; }
            const lastL = layers[layers.length - 1];
            if (lastL && lastL.first === n) { lastL.z = phys(2); lastL.start = false; curLayer = layers.length - 1; }
            else startLayer(phys(2), 0);
          } else if ((m = /^(?:Z|Z_HEIGHT):\s*([\d.]+)/.exec(t))) {
            if (layers.length && haveLayerComments) layers[layers.length - 1].z = parseFloat(m[1]);
          } else if ((m = /^(?:HEIGHT|LAYER_HEIGHT):\s*([\d.]+)/.exec(t))) {
            curH = parseFloat(m[1]) || 0;
            if (layers.length && haveLayerComments) layers[layers.length - 1].h = curH;
          } else if ((m = /^estimated printing time \((normal|silent) mode\)\s*[=:]\s*(.+)$/i.exec(t))) {
            const d = parseDuration(m[2]);
            if (m[1].toLowerCase() === 'normal') { if (d) estimate = d; } else estimateSilent = d;
          } else if ((m = /^([A-Za-z][A-Za-z0-9_ ]*?)\s*[=:]\s*(.*)$/.exec(t))) {
            const key = m[1].trim().toLowerCase().replace(/\s+/g, '_');
            const val = m[2].trim();
            if (/^[a-z0-9_]+$/.test(key) && !(key in config)) config[key] = val;
            if (key === 'total_estimated_time' || key === 'estimated_printing_time_(normal_mode)' ||
                key === 'estimated_printing_time') { const d = parseDuration(val); if (d) estimate = d; }
            if (key === 'estimated_printing_time_(silent_mode)') estimateSilent = parseDuration(val);
            if (key === 'model_printing_time' && /total estimated time:\s*(.+)$/i.test(val)) {
              const d = parseDuration(/total estimated time:\s*(.+)$/i.exec(val)[1]); if (d) estimate = d;
            }
          } else if (t === 'FLUSH_START') { curFeat = 18; }
          else if (t === 'FLUSH_END') { curFeat = 17; }
        }
      }
      if (line.length === 0) continue;

      // ---- Klipper style commands
      const trimmed = line.trim();
      if (!trimmed) continue;
      const head = trimmed.charCodeAt(0);
      if (head !== 71 && head !== 77 && head !== 84 && head !== 103 && head !== 109 && head !== 116) { // not G/M/T
        const up = trimmed.toUpperCase();
        if (up.startsWith('SET_VELOCITY_LIMIT')) {
          let m;
          if ((m = /ACCEL=([\d.]+)/.exec(up))) { accPrint = accTravel = parseFloat(m[1]); }
          if ((m = /SQUARE_CORNER_VELOCITY=([\d.]+)/.exec(up))) machineCmd.scv = parseFloat(m[1]);
          if ((m = /\bVELOCITY=([\d.]+)/.exec(up))) machineCmd.vmax = parseFloat(m[1]);
        } else if (up.startsWith('PAUSE')) { addEvent({ move: n, kind: 'pause', label: 'Pause' }); pendingStop = true; }
        continue;
      }

      // ---- words
      for (const k in word) word[k] = NaN;
      let cmdLetter = '', cmdNum = NaN;
      const L = trimmed.length; let p = 0;
      while (p < L) {
        const ch = trimmed.charCodeAt(p);
        if (ch === 32 || ch === 9) { p++; continue; }
        const letter = String.fromCharCode(ch & ~32);
        p++;
        let q = p;
        while (q < L) { const d = trimmed.charCodeAt(q); if (d === 32 || d === 9) break; q++; }
        const v = parseFloat(trimmed.substring(p, q));
        if (!cmdLetter && (letter === 'G' || letter === 'M' || letter === 'T')) { cmdLetter = letter; cmdNum = v; }
        else if (letter in word) word[letter] = v;
        p = q;
      }

      if (cmdLetter === 'G') {
        const g = cmdNum;
        if (g === 0 || g === 1 || g === 2 || g === 3) {
          if (!isNaN(word.F) && word.F > 0) fmm = word.F / 60;
          let tx = x, ty = y, tz = z, te = e;
          if (!isNaN(word.X)) tx = absXYZ ? word.X : x + word.X;
          if (!isNaN(word.Y)) ty = absXYZ ? word.Y : y + word.Y;
          if (!isNaN(word.Z)) tz = absXYZ ? word.Z : z + word.Z;
          if (!isNaN(word.E)) te = absE ? word.E : e + word.E;
          const dE = te - e;
          if (!started && (!isNaN(word.X) || !isNaN(word.Y))) {
            // jump to the first commanded position instead of drawing a travel from 0,0
            started = true;
            P.a[n * 3] = tx + ox; P.a[n * 3 + 1] = ty + oy; P.a[n * 3 + 2] = tz + oz;
            x = tx; y = ty; z = tz; e = te;
            continue;
          }
          if (g === 2 || g === 3) {
            arcMove(g === 2, x, y, tx, ty, z, tz, dE, word.I, word.J, word.R, lineNo);
          } else {
            linearMove(tx + ox, ty + oy, tz + oz, dE, lineNo, false);
          }
          x = tx; y = ty; z = tz; e = te;
        } else if (g === 29 && isBambu && g29Window) {
          // bed leveling: no moves in the G-code; OrcaSlicer budgets 260 s for it on Bambu printers
          push(phys(0), phys(1), phys(2), FL_DWELL, 0, 0, 0, 260, lineNo);
          pendingStop = true;
        } else if (g === 4) {
          let s = 0;
          if (!isNaN(word.P)) s = word.P / 1000; else if (!isNaN(word.S)) s = word.S;
          if (s > 0) push(phys(0), phys(1), phys(2), FL_DWELL, 0, 0, 0, s, lineNo);
          pendingStop = true;
        } else if (g === 28) {
          // homing: the head goes somewhere we can't know; teleport, it is not printing anything
          if (isNaN(word.X) && isNaN(word.Y) && isNaN(word.Z)) { x = 0; y = 0; z = 0; }
          else { if (!isNaN(word.X)) x = 0; if (!isNaN(word.Y)) y = 0; if (!isNaN(word.Z)) z = 0; }
          ox = oy = oz = 0;
          pendingStop = true;
        } else if (g === 90) { absXYZ = true; absE = true; }
        else if (g === 91) { absXYZ = false; absE = false; }
        else if (g === 92) {
          if (!isNaN(word.E)) e = word.E;
          if (!isNaN(word.X)) { ox = phys(0) - word.X; x = word.X; }
          if (!isNaN(word.Y)) { oy = phys(1) - word.Y; y = word.Y; }
          if (!isNaN(word.Z)) { oz = phys(2) - word.Z; z = word.Z; }
          if (isNaN(word.E) && isNaN(word.X) && isNaN(word.Y) && isNaN(word.Z)) e = 0;
        }
      } else if (cmdLetter === 'M') {
        const mm = cmdNum;
        if (mm === 1002) {
          const m = /judge_flag\s+([A-Za-z0-9_]+)/.exec(trimmed);
          if (m) judge(m[1]);
          else if (/judge_last_extrude_cali_success/.test(trimmed)) judge('last_extrude_cali_success');
          continue;
        }
        if (mm === 622.1) { if (!isNaN(word.S)) nextDefault = word.S >= 0.5; continue; }
        if (mm === 622) {
          const want = !isNaN(word.J) ? word.J : !isNaN(word.S) ? word.S : 1;
          const runs = judged === (want >= 0.5);
          blockStack.push(runs && !skipping);
          if (want >= 0.5) g29Window = true;       // OrcaSlicer times G29 only inside "M622 J1" blocks
          updateSkipping();
          continue;
        }
        if (mm === 623) { blockStack.pop(); g29Window = false; updateSkipping(); continue; }
        if (mm === 82) absE = true;
        else if (mm === 83) absE = false;
        else if (mm === 204) {
          if (!isNaN(word.S)) { accPrint = word.S; accTravel = word.S; }
          if (!isNaN(word.P)) accPrint = word.P;
          if (!isNaN(word.T)) accTravel = word.T;
          if (!isNaN(word.R)) accRetract = word.R;
        } else if (mm === 201) {
          machineCmd.ax = isNaN(word.X) ? machineCmd.ax : word.X; machineCmd.ay = isNaN(word.Y) ? machineCmd.ay : word.Y;
          machineCmd.az = isNaN(word.Z) ? machineCmd.az : word.Z; machineCmd.ae = isNaN(word.E) ? machineCmd.ae : word.E;
        } else if (mm === 203) {
          machineCmd.vx = isNaN(word.X) ? machineCmd.vx : word.X; machineCmd.vy = isNaN(word.Y) ? machineCmd.vy : word.Y;
          machineCmd.vz = isNaN(word.Z) ? machineCmd.vz : word.Z; machineCmd.ve = isNaN(word.E) ? machineCmd.ve : word.E;
        } else if (mm === 205) {
          machineCmd.jx = isNaN(word.X) ? machineCmd.jx : word.X; machineCmd.jy = isNaN(word.Y) ? machineCmd.jy : word.Y;
          machineCmd.jz = isNaN(word.Z) ? machineCmd.jz : word.Z; machineCmd.je = isNaN(word.E) ? machineCmd.je : word.E;
          // M205 J is junction deviation on Marlin 2
          if (!isNaN(word.J)) machineCmd.jd = word.J;
        } else if (mm === 73) {
          if (!isNaN(word.P)) m73.push({ move: n, p: word.P });
        } else if (mm === 400) {
          // Bambu: "M400 S3" / "M400 P500" waits; plain M400 just drains the queue
          let s = 0; if (!isNaN(word.S)) s = word.S; else if (!isNaN(word.P)) s = word.P / 1000;
          if (s > 0) push(phys(0), phys(1), phys(2), FL_DWELL, 0, 0, 0, s, lineNo);
          pendingStop = true;
        } else if (mm === 109 || mm === 190 || mm === 191) {
          addEvent({ move: n, kind: 'heat', label: (mm === 190 ? 'Wait for bed ' : 'Wait for nozzle ') + (isNaN(word.S) ? '' : word.S + '°C') });
          pendingStop = true;
        } else if (mm === 600 || mm === 601 || mm === 0 || mm === 1 || mm === 25 || mm === 226) {
          addEvent({ move: n, kind: 'pause', label: mm === 600 ? 'Filament change (M600)' : 'Pause' });
          pendingStop = true;
        } else if (mm === 620 && !isNaN(word.S)) {
          // Bambu AMS: "M620 S1A" announces a filament change to slot 1
          const slot = word.S;
          if (slot < 255) addEvent({ move: n, kind: 'tool', label: 'Filament change → slot ' + (slot + 1), tool: slot });
          pendingStop = true;
        }
      } else if (cmdLetter === 'T') {
        if (!isNaN(cmdNum) && cmdNum < 255 && cmdNum >= 0) {
          if ((cmdNum | 0) !== curTool) {
            const prev = curTool; curTool = cmdNum | 0;
            const last = events[events.length - 1];
            // Bambu announces the change with M620 first; don't list the same change twice
            if (!(last && last.kind === 'tool' && last.move >= lastExtrudeMove)) addEvent({ move: n, kind: 'tool', label: 'Tool ' + prev + ' → ' + curTool, tool: curTool });
            else last.tool = curTool;
          }
          pendingStop = true;
        }
      }
    }

    function arcMove(cw, sx, sy, ex, ey, sz, ez, dE, I, J, R, lineNo) {
      let cx, cy;
      if (!isNaN(I) || !isNaN(J)) { cx = sx + (isNaN(I) ? 0 : I); cy = sy + (isNaN(J) ? 0 : J); }
      else if (!isNaN(R)) {
        const dx = ex - sx, dy = ey - sy, d = Math.hypot(dx, dy);
        if (d < 1e-9) { linearMove(ex + ox, ey + oy, ez + oz, dE, lineNo, false); return; }
        let h = Math.sqrt(Math.max(0, R * R - d * d / 4));
        if ((R < 0) !== !cw) h = -h;            // standard G-code R sign convention
        cx = sx + dx / 2 - h * dy / d; cy = sy + dy / 2 + h * dx / d;
      } else { linearMove(ex + ox, ey + oy, ez + oz, dE, lineNo, false); return; }
      const r = Math.hypot(sx - cx, sy - cy);
      let a0 = Math.atan2(sy - cy, sx - cx), a1 = Math.atan2(ey - cy, ex - cx);
      let sweep = a1 - a0;
      if (cw) { if (sweep >= -1e-9) sweep -= 2 * Math.PI; } else { if (sweep <= 1e-9) sweep += 2 * Math.PI; }
      const arcLen = Math.abs(sweep) * r;
      const segs = Math.max(1, Math.min(256, Math.ceil(Math.max(arcLen / 0.5, Math.abs(sweep) / (Math.PI / 24)))));
      for (let k = 1; k <= segs; k++) {
        const f = k / segs, a = a0 + sweep * f;
        const px = k === segs ? ex : cx + r * Math.cos(a);
        const py = k === segs ? ey : cy + r * Math.sin(a);
        linearMove(px + ox, py + oy, sz + (ez - sz) * f + oz, dE / segs, lineNo, true);
      }
    }

    if (progress) progress(1);
    if (!layers.length) layers.push({ z: 0, h: 0, first: 0 });

    while (blockStack.length) blockStack.pop();
    if (skipping) updateSkipping();
    const job = {
      moves: n, pts: P.out((n + 1) * 3),
      flags: G.flags.out(n), feat: G.feat.out(n), layer: G.layer.out(n), tool: G.tool.out(n),
      fcmd: G.fcmd.out(n), len: G.len.out(n), de: G.de.out(n), acc: G.acc.out(n), wait: G.wait.out(n),
      line: G.line.out(n), hnom: G.hn.out(n), layers, events, m73, config, estimate, estimateSilent, lines: lineNo,
    };
    // drop empty layers produced by consecutive markers
    job.machine = resolveMachine(config, machineCmd);
    // moves were tagged with accel values known at parse time; 0 means "not set yet": fill defaults
    const m = job.machine;
    for (let k = 0; k < n; k++) {
      if (!(job.acc[k] > 0)) {
        const f = job.flags[k];
        job.acc[k] = (f & FL_EXTRUDE) ? m.accDefault : (f & FL_EONLY) ? m.accRetract : m.accTravel;
      }
    }
    job.flagsFound = Object.values(flagsFound);
    job.skippedMoves = skippedMoves;
    job.bed = resolveBed(job);
    computeBeads(job);
    return job;
  }

  /* ---------------------------------------------------------------- line cross-section
     What each extrusion actually lays down, from the G-code alone. The cross-section area is exact:
     A = filament fed × filament area ÷ path length. The line height is the gap between the nozzle
     and the surface below: the slicer's nominal height (HEIGHT tag) plus how far this move sits above
     or below the layer's Z. That is what Z contouring (z = layer Z + z_diff, E × (h + z_diff) / h) and
     scarf seams (Z and E ramping up together) change. The width then follows from OrcaSlicer's own
     rounded-rectangle model, A = h × (w − h × (1 − π/4)), so normal lines come out at the slicer's
     line width and ramps keep their width while getting thinner. */
  const BEAD_K = 1 - Math.PI / 4;
  function computeBeads(job) {
    const n = job.moves, F = job.flags, P = job.pts, L = job.layers, m = job.machine;
    const fa = Math.PI * Math.pow((m.filamentDiameter || 1.75) / 2, 2);
    const noz = m.nozzle || 0.4;
    const spiral = /^(1|true)$/i.test(String(first(job.config.spiral_mode, 0)));
    const W = new Float32Array(n), H = new Float32Array(n);
    const isExt = (k) => (F[k] & FL_EXTRUDE) && !(F[k] & FL_SKIP) && job.len[k] > 0 && job.de[k] > 0;
    const nominal = (k) => {
      const li = job.layer[k], lay = L[li] || L[0];
      let hn = job.hnom[k] || lay.h;
      if (!(hn > 0)) {
        const prev = li > 0 ? L[li - 1] : null;
        hn = prev && lay.z > prev.z ? lay.z - prev.z : (lay.z > 0 && lay.z < noz ? lay.z : noz / 2);
      }
      return hn;
    };
    const near = noz * 0.3, CELL = 1;
    for (let li = 0; li < L.length; li++) {
      const a = L[li].first, b = li + 1 < L.length ? L[li + 1].first : n;
      const lay = L[li], useZ = !spiral && lay.z > 0;
      // segments laid below the layer's Z (scarf starts, Z-contoured lines), hashed by position:
      // a later line on top of one of them (the scarf's closing overlap) rests on it, not on the layer below
      let grid = null;
      for (let k = a; k < b; k++) {
        if (!isExt(k)) continue;
        const hn = nominal(k);
        let base = useZ ? lay.z - hn : null;
        // OrcaSlicer sizes each line's flow from its end point (z and ratios at line.b), so do the same
        const zm = P[k * 3 + 5];
        if (grid && useZ) {
          const mx = P[k * 3 + 3], my = P[k * 3 + 4];
          const cx = Math.floor(mx / CELL), cy = Math.floor(my / CELL);
          for (let gx = cx - 1; gx <= cx + 1; gx++) for (let gy = cy - 1; gy <= cy + 1; gy++) {
            const list = grid.get(gx * 65536 + gy); if (!list) continue;
            for (const j of list) {
              const ax = P[j * 3], ay = P[j * 3 + 1], bx = P[j * 3 + 3], by = P[j * 3 + 4];
              const dx = bx - ax, dy = by - ay, d2 = dx * dx + dy * dy;
              const t = d2 > 0 ? Math.min(1, Math.max(0, ((mx - ax) * dx + (my - ay) * dy) / d2)) : 0;
              const ex = ax + dx * t - mx, ey = ay + dy * t - my;
              if (ex * ex + ey * ey > near * near) continue;
              const top = P[j * 3 + 2] + (P[j * 3 + 5] - P[j * 3 + 2]) * t;
              if (top < zm - 0.005 && top > base) base = top;
            }
          }
        }
        let h = useZ ? zm - base : hn;
        h = Math.min(Math.max(h, 0.005), hn * 1.5, noz * 1.5);
        const A = job.de[k] * fa / job.len[k];
        W[k] = Math.min(Math.max(A / h + h * BEAD_K, 0.05), noz * 3);
        H[k] = h;
        if (useZ && zm < lay.z - 0.01) {
          if (!grid) grid = new Map();
          const x0 = Math.floor(Math.min(P[k * 3], P[k * 3 + 3]) / CELL), x1 = Math.floor(Math.max(P[k * 3], P[k * 3 + 3]) / CELL);
          const y0 = Math.floor(Math.min(P[k * 3 + 1], P[k * 3 + 4]) / CELL), y1 = Math.floor(Math.max(P[k * 3 + 1], P[k * 3 + 4]) / CELL);
          if ((x1 - x0 + 1) * (y1 - y0 + 1) <= 64)
            for (let gx = x0; gx <= x1; gx++) for (let gy = y0; gy <= y1; gy++) {
              const key = gx * 65536 + gy; let list = grid.get(key); if (!list) grid.set(key, list = []); list.push(k);
            }
        }
      }
    }
    job.beadW = W; job.beadH = H;
  }

  /* ---------------------------------------------------------------- machine & bed */
  function resolveMachine(cfg, cmd) {
    const g = (k, d) => first(cfg[k], d);
    const flavor = String(cfg.gcode_flavor || '').toLowerCase();
    const m = {
      vx: cmd.vx || g('machine_max_speed_x', 500), vy: cmd.vy || g('machine_max_speed_y', 500),
      vz: cmd.vz || g('machine_max_speed_z', 20), ve: cmd.ve || g('machine_max_speed_e', 60),
      ax: cmd.ax || g('machine_max_acceleration_x', 20000), ay: cmd.ay || g('machine_max_acceleration_y', 20000),
      az: cmd.az || g('machine_max_acceleration_z', 500), ae: cmd.ae || g('machine_max_acceleration_e', 5000),
      jx: cmd.jx || g('machine_max_jerk_x', 9), jy: cmd.jy || g('machine_max_jerk_y', 9),
      jz: cmd.jz || g('machine_max_jerk_z', 3), je: cmd.je || g('machine_max_jerk_e', 2.5),
      accDefault: g('default_acceleration', 0) || g('machine_max_acceleration_extruding', 5000),
      accTravel: g('travel_acceleration', 0) || g('machine_max_acceleration_travel', 0) || g('default_acceleration', 0) || 5000,
      accRetract: g('machine_max_acceleration_retracting', 0) || 3000,
      flavor,
      jd: 0, mode: 'jerk',
      filamentDiameter: g('filament_diameter', 1.75),
      nozzle: g('nozzle_diameter', 0.4),
    };
    if (cmd.vmax) { m.vx = Math.min(m.vx, cmd.vmax); m.vy = Math.min(m.vy, cmd.vmax); }
    if (flavor === 'klipper' || cmd.scv) {
      const scv = cmd.scv || 5;
      m.mode = 'jd'; m.scv = scv;          // junction deviation is derived per-move from the accel
    } else if ((cmd.jd || g('machine_max_junction_deviation', 0)) > 0) {
      m.mode = 'jd'; m.jd = cmd.jd || g('machine_max_junction_deviation', 0.013);
    }
    return m;
  }

  function resolveBed(job) {
    const cfg = job.config;
    let poly = null;
    const area = cfg.printable_area || cfg.bed_shape;
    if (area) {
      const pts = String(area).replace(/[\[\]"']/g, '').split(',').map(s => s.trim().split('x').map(parseFloat))
        .filter(p => p.length === 2 && isFinite(p[0]) && isFinite(p[1]));
      if (pts.length >= 3) poly = pts;
    }
    // bounding box of extrusions as the fallback (and to frame the camera)
    let minX = 1e9, minY = 1e9, minZ = 1e9, maxX = -1e9, maxY = -1e9, maxZ = -1e9;
    const P = job.pts, F = job.flags;
    for (let k = 0; k < job.moves; k++) {
      if (!(F[k] & FL_EXTRUDE) || (F[k] & FL_SKIP)) continue;
      for (const q of [k, k + 1]) {
        const xx = P[q * 3], yy = P[q * 3 + 1], zz = P[q * 3 + 2];
        if (xx < minX) minX = xx; if (xx > maxX) maxX = xx;
        if (yy < minY) minY = yy; if (yy > maxY) maxY = yy;
        if (zz < minZ) minZ = zz; if (zz > maxZ) maxZ = zz;
      }
    }
    if (minX > maxX) { minX = minY = minZ = 0; maxX = maxY = 100; maxZ = 1; }
    if (!poly) {
      const pad = 10;
      poly = [[Math.floor(minX - pad), Math.floor(minY - pad)], [Math.ceil(maxX + pad), Math.floor(minY - pad)],
              [Math.ceil(maxX + pad), Math.ceil(maxY + pad)], [Math.floor(minX - pad), Math.ceil(maxY + pad)]];
    }
    let bx0 = 1e9, by0 = 1e9, bx1 = -1e9, by1 = -1e9;
    for (const p of poly) { bx0 = Math.min(bx0, p[0]); by0 = Math.min(by0, p[1]); bx1 = Math.max(bx1, p[0]); by1 = Math.max(by1, p[1]); }
    const structure = String(cfg.printer_structure || '').toLowerCase();
    return {
      poly, x0: bx0, y0: by0, x1: bx1, y1: by1, height: first(cfg.printable_height, Math.max(maxZ + 10, 100)),
      model: { minX, minY, minZ, maxX, maxY, maxZ },
      structure,
      bedSlinger: structure === 'i3',
    };
  }

  /* ---------------------------------------------------------------- planner */
  function planJob(job, opts) {
    opts = opts || {};
    const n = job.moves, P = job.pts, F = job.flags, m = job.machine;
    const vnom = new Float32Array(n), acc = new Float32Array(n);
    const ux = new Float32Array(n), uy = new Float32Array(n), uz = new Float32Array(n), ue = new Float32Array(n);
    const jl = new Float32Array(n);                 // max entry speed (junction limit)
    const safe = new Float32Array(n);               // speed allowed when starting/stopping from standstill
    const vi = new Float32Array(n), vf = new Float32Array(n), vp = new Float32Array(n);
    const dur = new Float32Array(n);
    const INF = 1e9;

    for (let k = 0; k < n; k++) {
      const L = job.len[k];
      if ((F[k] & FL_DWELL) || L <= 0) { vnom[k] = 0; continue; }
      let dx, dy, dz, de = job.de[k];
      if (F[k] & FL_EONLY) { dx = dy = dz = 0; }
      else { dx = P[k * 3 + 3] - P[k * 3]; dy = P[k * 3 + 4] - P[k * 3 + 1]; dz = P[k * 3 + 5] - P[k * 3 + 2]; }
      const inv = 1 / L;
      ux[k] = dx * inv; uy[k] = dy * inv; uz[k] = dz * inv; ue[k] = de * inv;
      let v = job.fcmd[k] > 0 ? job.fcmd[k] : 50;
      const lim = (vmax, u) => (Math.abs(u) > 1e-9 ? vmax / Math.abs(u) : INF);
      v = Math.min(v, lim(m.vx, ux[k]), lim(m.vy, uy[k]), lim(m.vz, uz[k]), lim(m.ve, ue[k]));
      let a = job.acc[k] > 0 ? job.acc[k] : 1000;
      a = Math.min(a, lim(m.ax, ux[k]), lim(m.ay, uy[k]), lim(m.az, uz[k]), lim(m.ae, ue[k]));
      vnom[k] = v; acc[k] = a;
      let s = v;
      s = Math.min(s, lim(m.jx, ux[k]), lim(m.jy, uy[k]), lim(m.jz, uz[k]), lim(m.je, ue[k]));
      safe[k] = Math.max(0, s);
    }

    // junction limits
    let prev = -1;
    for (let k = 0; k < n; k++) {
      if (vnom[k] <= 0) { prev = -1; continue; }
      if (prev < 0 || (F[k] & FL_STOP) || ((F[k] ^ F[prev]) & FL_EONLY)) { jl[k] = safe[k]; prev = k; continue; }
      const vmax = Math.min(vnom[prev], vnom[k]);
      let vj;
      if (m.mode === 'jd') {
        // junction deviation: v^2 = a * jd * sin(θ/2) / (1 - sin(θ/2)), θ the angle between directions
        const cos = -(ux[prev] * ux[k] + uy[prev] * uy[k] + uz[prev] * uz[k]);
        if (cos > 0.999999) vj = Math.min(safe[k], safe[prev]);       // full reversal
        else if (cos < -0.999999) vj = vmax;                           // straight
        else {
          const sinHalf = Math.sqrt(0.5 * (1 - cos));
          const a = Math.min(acc[prev], acc[k]);
          const jd = m.jd > 0 ? m.jd : (m.scv * m.scv * (Math.SQRT2 - 1)) / a;
          vj = Math.sqrt(a * jd * sinHalf / (1 - sinHalf));
        }
      } else {
        // classic jerk: the per-axis velocity step at the corner may not exceed the jerk limit
        vj = vmax;
        const chk = (d, j) => { const ad = Math.abs(d); if (ad > 1e-9) vj = Math.min(vj, j / ad); };
        chk(ux[prev] - ux[k], m.jx); chk(uy[prev] - uy[k], m.jy); chk(uz[prev] - uz[k], m.jz);
        chk(ue[prev] - ue[k], m.je);
        vj = Math.max(vj, Math.min(safe[prev], safe[k]));
      }
      jl[k] = Math.min(vj, vmax);
      prev = k;
    }

    // exit limit of a move: entry of the next moving move, or the standstill speed before a stop
    const exitMax = new Float32Array(n);
    for (let k = 0; k < n; k++) {
      if (vnom[k] <= 0) continue;
      const nx = k + 1;
      if (nx >= n || vnom[nx] <= 0 || (F[nx] & FL_STOP) || ((F[k] ^ F[nx]) & FL_EONLY)) exitMax[k] = safe[k];
      else exitMax[k] = INF;
    }
    // backward pass
    let nextEntry = 0;
    for (let k = n - 1; k >= 0; k--) {
      if (vnom[k] <= 0) { nextEntry = 0; continue; }
      const ex = exitMax[k] < INF ? exitMax[k] : nextEntry;
      vf[k] = ex;
      const e = Math.min(jl[k], Math.sqrt(ex * ex + 2 * acc[k] * job.len[k]));
      vi[k] = e;
      nextEntry = e;
    }
    // forward pass
    for (let k = 0; k < n; k++) {
      if (vnom[k] <= 0) continue;
      const reach = Math.sqrt(vi[k] * vi[k] + 2 * acc[k] * job.len[k]);
      if (vf[k] > reach) vf[k] = reach;
      if (k + 1 < n && vnom[k + 1] > 0 && exitMax[k] >= INF) {
        if (vi[k + 1] > vf[k]) vi[k + 1] = vf[k];
        else vf[k] = vi[k + 1];
      }
    }
    // trapezoids
    let t = 0; const t0 = new Float64Array(n);
    for (let k = 0; k < n; k++) {
      t0[k] = t;
      if (F[k] & FL_DWELL) { dur[k] = job.wait[k]; t += dur[k]; continue; }
      const L = job.len[k];
      if (vnom[k] <= 0 || L <= 0) { dur[k] = 0; continue; }
      const a = acc[k], v0 = Math.min(vi[k], vnom[k]), v1 = Math.min(vf[k], vnom[k]);
      vi[k] = v0; vf[k] = v1;
      let vpk = vnom[k];
      let da = (vpk * vpk - v0 * v0) / (2 * a), dd = (vpk * vpk - v1 * v1) / (2 * a);
      if (da + dd > L) {
        vpk = Math.sqrt(Math.max(0, (2 * a * L + v0 * v0 + v1 * v1) / 2));
        vpk = Math.max(vpk, v0, v1);
        da = Math.max(0, (vpk * vpk - v0 * v0) / (2 * a)); dd = Math.max(0, L - da);
      }
      vp[k] = vpk;
      const ta = (vpk - v0) / a, td = (vpk - v1) / a;
      const tc = Math.max(0, L - da - dd) / vpk;
      dur[k] = Math.max(1e-6, ta + tc + td);
      t += dur[k];
    }
    job.vi = vi; job.vf = vf; job.vp = vp; job.ac = acc; job.vnom = vnom;
    job.plannerT0 = t0; job.plannerDur = dur; job.plannerTotal = t;
    applyTiming(job, opts.align !== false);
    return job;
  }

  /* Map planner time onto the slicer's estimate using its M73 progress markers, piecewise linearly.
     The slicer simulates the firmware more faithfully than any viewer can, so when it left markers
     we trust its clock and only use our planner for what happens *between* the markers. */
  function applyTiming(job, align) {
    const n = job.moves, t0p = job.plannerT0, dp = job.plannerDur, F = job.flags;
    /* Each stretch between two markers is fitted on its own: its motion is scaled so the stretch
       lasts what the slicer says, while fixed waits (G4, M400 S/P, the G29 budget) keep their length.
       Markers that don't leave room for a stretch's fixed waits (the slicer books a wait a few moves
       away from where it sits in the file, e.g. the 260 s for G29 lands on the moves before it)
       are dropped, merging that stretch with the previous one, so a mismatch stays local. */
    const isFixed = (k) => (F[k] & FL_DWELL) !== 0;
    const t0 = new Float64Array(n), dur = new Float32Array(n);
    // knots: [move index, slicer time at that move]
    let knots = null;
    if (align && job.estimate > 0 && job.m73.length >= 3 && n > 0) {
      knots = [[0, 0]];
      let lastP = -1;
      for (const mk of job.m73) {
        if (mk.p <= lastP || mk.p <= 0 || mk.p >= 100) continue;
        const k = Math.min(mk.move, n), tb = job.estimate * mk.p / 100;
        if (k <= knots[knots.length - 1][0]) continue;
        knots.push([k, tb]); lastP = mk.p;
      }
      if (knots[knots.length - 1][0] < n) knots.push([n, job.estimate]);
      else knots[knots.length - 1][1] = Math.max(knots[knots.length - 1][1], job.estimate);
      // per-stretch planner motion and fixed time
      const sums = (a, b) => {
        let m = 0, f = 0;
        for (let k = a; k < b; k++) { if (isFixed(k)) f += dp[k]; else m += dp[k]; }
        return [m, f];
      };
      let changed = true;
      while (changed && knots.length > 2) {
        changed = false;
        for (let i = 1; i < knots.length; i++) {
          const [a, ta] = knots[i - 1], [b, tb] = knots[i];
          const [m, f] = sums(a, b);
          if (tb - ta < f - 1e-6 || (m > 0 && tb - ta <= f + 1e-6)) {
            // not enough slicer time for this stretch's waits: the slicer booked them earlier, so
            // merge with the stretch before (drop the knot at its start); the first stretch merges forward
            knots.splice(i > 1 ? i - 1 : (knots.length > 2 ? 1 : i), 1);
            changed = true; break;
          }
        }
      }
      const fixedTotal = sums(0, n)[1], motionTotal = job.plannerTotal - fixedTotal;
      const ratio = (job.estimate - fixedTotal) / Math.max(1e-9, motionTotal);
      // wildly different totals mean the markers belong to some other clock (e.g. silent mode)
      if (knots.length < 4 || !(motionTotal > 0) || ratio < 0.3 || ratio > 3) knots = null;
    }
    if (!knots) {
      t0.set(t0p); dur.set(dp);
      job.total = job.plannerTotal; job.aligned = false;
    } else {
      let t = 0;
      for (let i = 1; i < knots.length; i++) {
        const [a, ta] = knots[i - 1], [b, tb] = knots[i];
        let m = 0, f = 0;
        for (let k = a; k < b; k++) { if (isFixed(k)) f += dp[k]; else m += dp[k]; }
        const span = Math.max(0, tb - ta);
        // motion gets what is left after the waits; a stretch of waits only is scaled as a whole
        const ms = m > 0 ? Math.max(0, span - f) / m : 0;
        const fs = m > 0 ? (span >= f ? 1 : span / Math.max(f, 1e-9)) : (f > 0 ? span / f : 1);
        for (let k = a; k < b; k++) {
          t0[k] = t;
          dur[k] = dp[k] * (isFixed(k) ? fs : ms);
          t += dur[k];
        }
      }
      job.total = t; job.aligned = true;
    }
    // blocks the printer won't run still count toward the slicer's estimate (it times every line),
    // so they are aligned like everything else and only then taken out of the clock
    if (job.skippedMoves) {
      let t = 0;
      for (let k = 0; k < n; k++) {
        if (job.flags[k] & FL_SKIP) dur[k] = 0;
        t0[k] = t; t += dur[k];
      }
      job.total = t;
    }
    job.t0 = t0; job.dur = dur;
    // layer timing
    for (let L = 0; L < job.layers.length; L++) {
      const a = job.layers[L].first, b = L + 1 < job.layers.length ? job.layers[L + 1].first : n;
      job.layers[L].t0 = a < n ? t0[a] : job.total;
      job.layers[L].t1 = b < n ? t0[b] : job.total;
    }
  }

  /* index of the move active at time t (binary search on t0) */
  function moveAt(job, t) {
    const T = job.t0; let lo = 0, hi = job.moves - 1;
    if (hi < 0) return 0;
    if (t <= T[0]) return 0;
    if (t >= T[hi]) return hi;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (T[mid] <= t) lo = mid; else hi = mid - 1; }
    return lo;
  }

  /* position along move k (0..L) and instantaneous speed, given time t inside it */
  function stateIn(job, k, t) {
    const L = job.len[k];
    const D = job.dur[k], Dp = job.plannerDur[k];
    if (!(D > 0) || !(Dp > 0) || !(L > 0) || (job.flags[k] & FL_DWELL)) return { frac: t >= job.t0[k] + D ? 1 : 0, v: 0 };
    let tau = (t - job.t0[k]) / D * Dp;                // planner-time inside the move
    if (tau < 0) tau = 0; if (tau > Dp) tau = Dp;
    const a = job.ac[k], v0 = job.vi[k], v1 = job.vf[k], vpk = job.vp[k];
    const ta = (vpk - v0) / a, td = (vpk - v1) / a, tc = Math.max(0, Dp - ta - td);
    let s, v;
    if (tau < ta) { s = v0 * tau + 0.5 * a * tau * tau; v = v0 + a * tau; }
    else if (tau < ta + tc) { const da = v0 * ta + 0.5 * a * ta * ta; s = da + vpk * (tau - ta); v = vpk; }
    else {
      const da = v0 * ta + 0.5 * a * ta * ta, dc = vpk * tc, u = tau - ta - tc;
      s = da + dc + vpk * u - 0.5 * a * u * u; v = vpk - a * u;
    }
    return { frac: Math.max(0, Math.min(1, s / L)), v: Math.max(0, v) };
  }

  const api = { parseGcode, planJob, computeBeads, applyTiming, moveAt, stateIn, FEATURES, featureId, parseDuration,
                FL_EXTRUDE, FL_TRAVEL, FL_EONLY, FL_DWELL, FL_ARC, FL_STOP, FL_SKIP, FLAG_INFO, flagLabel };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PlaybackCore = api;
})(typeof self !== 'undefined' ? self : this);
</script>
<script>/* Playback page: loads G-code, plans it (core.js) and plays it back in real time with Three.js. */
(function () {
  'use strict';
  const C = window.PlaybackCore;
  const $ = (id) => document.getElementById(id);
  const host = (window.orca && typeof window.orca.postMessage === 'function') ? window.orca : null;
  const send = (msg) => { if (host) host.postMessage(msg); };

  /* ------------------------------------------------------------------ preferences */
  const DEFAULT_PREFS = { speed: 10, color: 'feature', travel: false, layerOnly: false, follow: false,
                          motion: 'auto', lines: 'fat', timing: 'aligned', head: true, gantry: true, shade: 'tube', flags: {}, pauseOnLeave: true };
  let prefs = Object.assign({}, DEFAULT_PREFS);
  try { Object.assign(prefs, JSON.parse(localStorage.getItem('orca-playback-prefs') || '{}')); } catch (e) { /* storage may be off */ }
  let prefTimer = 0;
  function savePrefs() {
    clearTimeout(prefTimer);
    prefTimer = setTimeout(() => {
      try { localStorage.setItem('orca-playback-prefs', JSON.stringify(prefs)); } catch (e) { /* ignore */ }
      send({ cmd: 'save_prefs', prefs });
    }, 300);
  }

  /* ------------------------------------------------------------------ small UI helpers */
  function fmtTime(s, withSec) {
    if (!isFinite(s) || s < 0) s = 0;
    s = Math.floor(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    if (h) return h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    return m + ':' + String(sec).padStart(2, '0');
  }
  function fmtLong(s) {
    s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return (h ? h + 'h ' : '') + (h || m ? m + 'm ' : '') + sec + 's';
  }
  let toastTimer = 0;
  function toast(text, isErr) {
    const t = $('toast'); t.textContent = text; t.className = 'overlay show' + (isErr ? ' err' : '');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = 'overlay'; }, isErr ? 6000 : 2800);
  }
  function busy(text, frac) {
    const b = $('busy');
    if (text == null) { b.style.display = 'none'; return; }
    b.style.display = 'grid'; $('busyText').textContent = text;
    $('busyBar').style.width = Math.round((frac || 0) * 100) + '%';
  }
  const nextFrame = () => new Promise((r) => setTimeout(r, 0));

  /* ------------------------------------------------------------------ colours */
  const RANGE = ['#0b2c7a', '#135985', '#1c8891', '#04d60f', '#aaf200', '#fcf903', '#f5ce0a', '#d16830', '#c2523c', '#942616'];
  const hexRGB = (h) => { h = String(h || '#888').replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join('');
                          const v = parseInt(h.substring(0, 6), 16); return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255]; };
  const RANGE_RGB = RANGE.map(hexRGB);
  const FEAT_RGB = C.FEATURES.map(f => hexRGB(f[1]));
  function rampRGB(t, out) {
    t = Math.max(0, Math.min(1, t)) * (RANGE_RGB.length - 1);
    const i = Math.min(RANGE_RGB.length - 2, Math.floor(t)), f = t - i, a = RANGE_RGB[i], b = RANGE_RGB[i + 1];
    out[0] = a[0] + (b[0] - a[0]) * f; out[1] = a[1] + (b[1] - a[1]) * f; out[2] = a[2] + (b[2] - a[2]) * f;
  }
  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  /* ------------------------------------------------------------------ three.js scene */
  const canvas = $('gl');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: false });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.5, 5000);
  camera.up.set(0, 0, 1);
  /* Camera like OrcaSlicer's: a turntable with Z up. Left drag rotates, right drag (or Shift/Ctrl +
     left) pans, middle drag and the wheel zoom.
     - Rotation turns about the middle of the screen, at the depth of the first line straight ahead
       (or the current view centre when there is none), so the picture doesn't jump.
     - The wheel zooms toward the point under the cursor, so what you point at stays put.
     - A drag ends on pointerup, pointercancel, lost capture or window blur, and the wheel never waits
       for a drag to end, so zooming can't get stuck after a release the page didn't see. */
  const controls = (() => {
    const target = new THREE.Vector3();
    const Z = new THREE.Vector3(0, 0, 1);
    let mode = null, pointerId = null, lastX = 0, lastY = 0, changed = true;
    const pivot = new THREE.Vector3(), panPerPx = { v: 0 };
    let zoomPick = null;                 // {x, y, p}: cached point under a resting cursor
    const tmp = new THREE.Vector3(), tmp2 = new THREE.Vector3(), q = new THREE.Quaternion();
    const api = { target, enabled: true, pick: null };

    function ray(clientX, clientY) {
      const r = canvas.getBoundingClientRect();
      const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
      camera.updateMatrixWorld();          // the camera may have moved since the last frame was drawn
      const rc = new THREE.Raycaster(); rc.setFromCamera(ndc, camera); return rc.ray;
    }
    // point on the view ray at the depth of the current target (the plane through it facing the camera)
    function onTargetPlane(rr) {
      const n = camera.getWorldDirection(tmp2);
      const denom = rr.direction.dot(n);
      const d = Math.abs(denom) > 1e-6 ? target.clone().sub(rr.origin).dot(n) / denom : target.distanceTo(camera.position);
      return rr.origin.clone().addScaledVector(rr.direction, Math.max(d, 1));
    }
    function pickAt(clientX, clientY) {
      const rr = ray(clientX, clientY);
      const hit = api.pick ? api.pick(rr) : null;
      return { hit, point: hit || null, rr };
    }
    /* The view direction is kept as two angles about the target: azimuth theta (around Z) and polar
       angle phi (0 = straight down from above). The camera's axes are built from them directly,
       never with lookAt, so straight overhead is an ordinary view: theta still says which way is up
       on screen, and the picture can't flip or flicker at the pole. */
    let theta = -2.1, phi = 0.9;
    const basis = new THREE.Matrix4(), bx = new THREE.Vector3(), by = new THREE.Vector3(), bz = new THREE.Vector3();
    function orient() {
      const st = Math.sin(theta), ct = Math.cos(theta), sp = Math.sin(phi), cp = Math.cos(phi);
      const d = Math.max(1e-6, camera.position.distanceTo(target));
      bz.set(sp * ct, sp * st, cp);                       // from the target toward the camera
      bx.set(-st, ct, 0);                                  // screen right
      by.set(-cp * ct, -cp * st, sp);                      // screen up
      camera.position.copy(target).addScaledVector(bz, d);
      basis.makeBasis(bx, by, bz); camera.quaternion.setFromRotationMatrix(basis);
      camera.updateMatrix(); changed = true;
    }
    // read the angles back after the camera was placed from outside (view buttons, tests)
    function fromCamera() {
      const v = tmp.copy(camera.position).sub(target), d = v.length();
      if (d < 1e-9) return;
      phi = Math.acos(Math.max(-1, Math.min(1, v.z / d)));
      if (Math.sin(phi) > 1e-6) theta = Math.atan2(v.y, v.x);   // at the pole keep the last azimuth
      orient();
    }
    function rotate(dx, dy) {
      const h = canvas.clientHeight || 1;
      // like OrcaSlicer: drag right swings the camera left around the print, drag down raises it (looks down more)
      theta -= 2 * Math.PI * dx / h;
      phi = Math.max(0, Math.min(Math.PI, phi - 2 * Math.PI * dy / h));
      orient();
    }
    function pan(dx, dy) {
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
      const move = right.multiplyScalar(-dx * panPerPx.v).add(up.multiplyScalar(dy * panPerPx.v));
      camera.position.add(move); target.add(move); changed = true;
    }
    function zoomAbout(p, f) {
      const dist = camera.position.distanceTo(p);
      if (f < 1 && dist * f < 0.6) f = 0.6 / Math.max(dist, 1e-6);          // don't go through what you point at
      if (f > 1 && dist * f > 4000) f = 4000 / Math.max(dist, 1e-6);
      if (Math.abs(f - 1) < 1e-6) return;
      camera.position.sub(p).multiplyScalar(f).add(p);
      target.sub(p).multiplyScalar(f).add(p);
      changed = true;
    }
    function zoomPoint(clientX, clientY) {
      if (zoomPick && Math.abs(zoomPick.x - clientX) < 3 && Math.abs(zoomPick.y - clientY) < 3) return zoomPick.p;
      const { point, rr } = pickAt(clientX, clientY);
      const p = point || onTargetPlane(rr);
      zoomPick = { x: clientX, y: clientY, p: p.clone() };
      return zoomPick.p;
    }
    function depthPerPx(p) {
      const d = Math.max(0.5, camera.position.distanceTo(p));
      return 2 * d * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) / (canvas.clientHeight || 1);
    }
    function end() {
      if (pointerId != null) { try { canvas.releasePointerCapture(pointerId); } catch (e) { /* already released */ } }
      mode = null; pointerId = null; canvas.style.cursor = '';
    }
    // touch: one finger rotates, two fingers pinch-zoom and pan
    const touches = new Map(); let pinch = null;

    canvas.addEventListener('pointerdown', (e) => {
      if (!api.enabled) return;
      canvas.focus({ preventScroll: true });
      if (e.pointerType === 'touch') {
        touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (touches.size === 2) {
          const [a, b] = [...touches.values()];
          const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
          const p = zoomPoint(mx, my);
          pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), mx, my, p }; panPerPx.v = depthPerPx(p); mode = null;
          return;
        }
      }
      end();
      const panBtn = e.button === 2 || (e.button === 0 && (e.shiftKey || e.ctrlKey || e.metaKey));
      mode = panBtn ? 'pan' : e.button === 1 ? 'dolly' : e.button === 0 ? 'rotate' : null;
      if (!mode) return;
      pointerId = e.pointerId; lastX = e.clientX; lastY = e.clientY;
      try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* not capturable */ }
      if (mode === 'rotate') {
        // OrcaSlicer-style turntable about the middle of the screen: the first line straight ahead
        // of the camera, or the current view centre when nothing is there. It sits on the view
        // axis, so making it the target doesn't move the picture.
        const r = canvas.getBoundingClientRect();
        const { point } = pickAt(r.left + r.width / 2, r.top + r.height / 2);
        if (point) target.copy(point);
        pivot.copy(target);
        canvas.style.cursor = 'grabbing';
      } else {
        const { point, rr } = pickAt(e.clientX, e.clientY);
        const p = point || onTargetPlane(rr);
        pivot.copy(p); panPerPx.v = depthPerPx(p);
        canvas.style.cursor = mode === 'pan' ? 'move' : 'ns-resize';
      }
      e.preventDefault();
    });
    canvas.addEventListener('pointermove', (e) => {
      if (e.pointerType === 'touch' && touches.has(e.pointerId)) {
        touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (pinch && touches.size === 2) {
          const [a, b] = [...touches.values()];
          const d = Math.hypot(a.x - b.x, a.y - b.y), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
          pan(mx - pinch.mx, my - pinch.my);
          if (d > 1 && pinch.d > 1) zoomAbout(pinch.p, pinch.d / d);
          pinch.d = d; pinch.mx = mx; pinch.my = my; panPerPx.v = depthPerPx(pinch.p);
          return;
        }
      }
      if (!mode || e.pointerId !== pointerId) return;
      if (e.buttons === 0 && e.pointerType === 'mouse') { end(); return; }   // the button came up where we couldn't see it
      const dx = e.clientX - lastX, dy = e.clientY - lastY; lastX = e.clientX; lastY = e.clientY;
      if (mode === 'rotate') rotate(dx, dy);
      else if (mode === 'pan') pan(dx, dy);
      else if (mode === 'dolly') zoomAbout(pivot, Math.exp(dy * 0.006));
      zoomPick = null;
    });
    const up = (e) => {
      if (e.pointerType === 'touch') { touches.delete(e.pointerId); if (touches.size < 2) pinch = null; }
      if (e.pointerId === pointerId) end();
    };
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);
    canvas.addEventListener('lostpointercapture', (e) => { if (e.pointerId === pointerId) end(); });
    window.addEventListener('blur', () => { end(); touches.clear(); pinch = null; });
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('wheel', (e) => {
      if (!api.enabled) return;
      e.preventDefault();
      const unit = e.deltaMode === 1 ? 33 : e.deltaMode === 2 ? 400 : 1;
      const dy = Math.max(-400, Math.min(400, e.deltaY * unit));
      zoomAbout(zoomPoint(e.clientX, e.clientY), Math.exp(dy * 0.0012));
    }, { passive: false });
    canvas.addEventListener('pointerleave', () => { zoomPick = null; });

    api.update = () => {
      const c = changed; changed = false;
      if (c) {
        // keep the near plane in step with how close we are, so zooming in doesn't clip the print
        const near = Math.min(5, Math.max(0.02, camera.position.distanceTo(target) / 400));
        if (Math.abs(near - camera.near) / camera.near > 0.2) { camera.near = near; camera.updateProjectionMatrix(); }
      }
      return c;
    };
    api.sync = () => { fromCamera(); zoomPick = null; changed = true; };
    api.isDragging = () => mode != null;
    api._pivot = () => pivot.clone();
    return api;
  })();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 0.6); sun.position.set(-1, -2, 3); scene.add(sun);

  const bedGroup = new THREE.Group(); scene.add(bedGroup);    // bed + everything printed on it
  const headGroup = new THREE.Group(); scene.add(headGroup);  // nozzle
  const gantry = new THREE.Group(); scene.add(gantry);
  let bedMesh = null;

  function buildHead() {
    const metal = new THREE.MeshLambertMaterial({ color: 0xc8ccd2 });
    // translucent hot-end body so it never hides the line being printed
    const block = new THREE.MeshLambertMaterial({ color: 0x59616b, transparent: true, opacity: 0.38, depthWrite: false });
    const cone = new THREE.Mesh(new THREE.ConeGeometry(1.4, 3.5, 24), metal);
    cone.rotation.x = -Math.PI / 2; cone.position.z = 1.75;        // tip at z = 0
    const body = new THREE.Mesh(new THREE.BoxGeometry(9, 9, 7), block);
    body.position.z = 3.5 + 3.5;
    const tip = new THREE.Mesh(new THREE.SphereGeometry(0.45, 16, 12), new THREE.MeshBasicMaterial({ color: 0xff5a1f }));
    headGroup.add(cone, body, tip);
    headGroup.userData.body = body;
  }
  buildHead();
  const beamMat = new THREE.MeshLambertMaterial({ color: 0x5b626b, transparent: true, opacity: 0.28, depthWrite: false });
  const beam = new THREE.Mesh(new THREE.BoxGeometry(1, 4, 4), beamMat);
  gantry.add(beam);

  function bedTexture(w, h) {
    const px = 4, cw = Math.min(2048, Math.ceil(w * px)), ch = Math.min(2048, Math.ceil(h * px));
    const c = document.createElement('canvas'); c.width = cw; c.height = ch;
    const g = c.getContext('2d');
    g.fillStyle = '#2b2f35'; g.fillRect(0, 0, cw, ch);
    const sx = cw / w, sy = ch / h;
    for (let mm = 0; mm <= Math.max(w, h); mm += 10) {
      const major = mm % 50 === 0;
      g.strokeStyle = major ? 'rgba(255,255,255,.22)' : 'rgba(255,255,255,.09)';
      g.lineWidth = major ? 2 : 1;
      if (mm <= w) { g.beginPath(); g.moveTo(mm * sx, 0); g.lineTo(mm * sx, ch); g.stroke(); }
      if (mm <= h) { g.beginPath(); g.moveTo(0, ch - mm * sy); g.lineTo(cw, ch - mm * sy); g.stroke(); }
    }
    const tex = new THREE.CanvasTexture(c);
    tex.anisotropy = 4;
    return tex;
  }
  function buildBed(bed) {
    if (bedMesh) { bedGroup.remove(bedMesh); bedMesh.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); }); }
    const w = bed.x1 - bed.x0, h = bed.y1 - bed.y0;
    const shape = new THREE.Shape(bed.poly.map(p => new THREE.Vector2(p[0], p[1])));
    const geo = new THREE.ShapeGeometry(shape);
    // UVs across the bounding box so the grid texture lines up with bed millimetres
    const pos = geo.attributes.position, uv = new Float32Array(pos.count * 2);
    for (let i = 0; i < pos.count; i++) { uv[i * 2] = (pos.getX(i) - bed.x0) / w; uv[i * 2 + 1] = (pos.getY(i) - bed.y0) / h; }
    geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    const mat = new THREE.MeshBasicMaterial({ map: bedTexture(w, h) });
    const plate = new THREE.Mesh(geo, mat);
    plate.position.z = -0.05;
    const slab = new THREE.Mesh(new THREE.BoxGeometry(w + 6, h + 6, 4), new THREE.MeshLambertMaterial({ color: 0x1a1d21 }));
    slab.position.set(bed.x0 + w / 2, bed.y0 + h / 2, -2.1);
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.ShapeGeometry(shape)),
                                        new THREE.LineBasicMaterial({ color: 0x8a939c }));
    edge.position.z = 0.01;
    bedMesh = new THREE.Group(); bedMesh.add(slab, plate, edge);
    bedGroup.add(bedMesh);
    beam.scale.set(w + 40, 1, 1);
  }

  /* ------------------------------------------------------------------ path buffers */
  const R = {                    // render state built per job
    segMove: null,              // Uint32Array: extrusion segment -> move index
    extPrefix: null,            // Uint32Array(moves+1): extrusion segments completed before move k
    travelPrefix: null,         // Uint32Array(moves+1): travel segments before move k
    pos: null, col: null,       // Float32Array 6 per segment
    main: null,                 // object rendering every segment, progressively revealed
    layerObj: null, layerObjLayer: -1,
    partial: null,              // the segment being printed right now
    travel: null,
  };
  let lineMat = null, lineMatPartial = null, thinMat = null;
  function lineWidth() { return Math.max(0.2, (job && job.machine.nozzle) ? job.machine.nozzle * 1.05 : 0.42); }

  function makeLines(pos, col, count, bead) {
    if (prefs.lines === 'thin') {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      g.setAttribute('color', new THREE.BufferAttribute(col, 3));
      g.setDrawRange(0, count * 2);
      const o = new THREE.LineSegments(g, thinMat); o.frustumCulled = false;
      o.userData.thin = true; return o;
    }
    const g = new THREE.LineSegmentsGeometry();
    g.setPositions(pos); g.setColors(col);
    g.setAttribute('instanceBead', new THREE.InstancedBufferAttribute(bead, 2));
    g.instanceCount = count;
    const o = new THREE.LineSegments2(g, lineMat); o.frustumCulled = false;
    return o;
  }
  function setCount(o, count) {
    if (!o) return;
    if (o.userData.thin) o.geometry.setDrawRange(0, count * 2);
    else o.geometry.instanceCount = count;
  }
  function disposeObj(o) { if (!o) return; bedGroup.remove(o); o.geometry.dispose(); }

  /* LineMaterial already finds, per pixel, how far the view ray passes from the line's axis
     (WORLD_UNITS mode). That is exactly a cylinder: turn the distance into a surface normal and
     light it, so extrusions read as round beads instead of flat ribbons. */
  const shadeUniform = { value: 1 };
  /* Each segment carries its own cross-section (instanceBead = width, height in mm): the bead is an
     ellipse-ish tube, wide across and as tall as the line really is. The quad is sized by the
     ellipse's extent across the view, and the fragment test and the lighting normal use the same
     ellipse, so scarf ramps and Z-contoured lines show their real thickness from the side. */
  const BEAD_VS_PARS = `
    attribute vec2 instanceBead;
    varying vec2 vBead;
    varying vec3 vUp;
    varying vec3 vSide;
    float beadRadius( vec3 dir ) {
      float a = 0.5 * vBead.x * dot( dir, vSide ), b = 0.5 * vBead.y * dot( dir, vUp );
      return max( sqrt( a * a + b * b ), 1e-4 );
    }`;
  const BEAD_FS_PARS = `
    varying vec2 vBead;
    varying vec3 vUp;
    varying vec3 vSide;
    float beadRadius( vec3 dir ) {
      float a = 0.5 * vBead.x * dot( dir, vSide ), b = 0.5 * vBead.y * dot( dir, vUp );
      return max( sqrt( a * a + b * b ), 1e-4 );
    }`;
  function shadedLineMaterial() {
    const m = new THREE.LineMaterial({ vertexColors: true, worldUnits: true, linewidth: 0.42 });
    m.onBeforeCompile = (shader) => {
      shader.uniforms.shadeMode = shadeUniform;
      const vs = shader.vertexShader;
      shader.vertexShader = vs
        .replace('attribute vec3 instanceEnd;', 'attribute vec3 instanceEnd;' + BEAD_VS_PARS)
        .replace('if ( position.x < 0.0 ) offset *= - 1.0;\n\n\t\t\t\tfloat forwardOffset', `if ( position.x < 0.0 ) offset *= - 1.0;
          vBead = instanceBead;
          vUp = normalize( ( modelViewMatrix * vec4( 0.0, 0.0, 1.0, 0.0 ) ).xyz );
          vSide = cross( vUp, worldDir );
          vSide = length( vSide ) > 1e-4 ? normalize( vSide ) : normalize( cross( worldDir, vec3( 1.0, 0.0, 0.0 ) ) );
          float beadR = beadRadius( offset );
          float beadCap = 0.5 * vBead.x;

\t\t\t\tfloat forwardOffset`)
        .replace('start.xyz += - worldDir * linewidth * 0.5;', 'start.xyz += - worldDir * beadCap;')
        .replace('end.xyz += worldDir * linewidth * 0.5;', 'end.xyz += worldDir * beadCap;')
        .replace('offset *= linewidth * 0.5;', 'offset *= beadR;');
      if (shader.vertexShader.indexOf('offset *= beadR;') < 0 || shader.vertexShader.indexOf('float beadR') < 0)
        console.warn('Playback: line shader layout changed; per-line widths are off');
      shader.fragmentShader = shader.fragmentShader
        .replace('uniform float opacity;', 'uniform float opacity;\nuniform float shadeMode;' + BEAD_FS_PARS)
        .replace('float norm = len / linewidth;', `vec3 beadDir = len > 1e-6 ? delta / len : vSide;
				float beadRs = beadRadius( beadDir );
				float norm = len / ( 2.0 * beadRs );`)
        .replace('#include <color_fragment>', `#include <color_fragment>
        #ifdef WORLD_UNITS
          if ( shadeMode > 0.5 ) {
            float r = beadRs;
            float s = clamp( len / r, 0.0, 1.0 );
            vec3 ld = normalize( lineDir );
            vec3 toCam = -normalize( p2 );
            vec3 c = toCam - dot( toCam, ld ) * ld;
            c = length( c ) > 1e-5 ? normalize( c ) : toCam;
            vec3 side = len > 1e-6 ? -delta / len : vec3( 0.0 );
            vec3 N = normalize( side * s + c * sqrt( max( 0.0, 1.0 - s * s ) ) );
            // round tube -> elliptical bead: normals scale by the inverse of the half-axes
            float ns = dot( N, vSide ), nu = dot( N, vUp );
            float ra = max( 0.5 * vBead.x, 1e-3 ), rb = max( 0.5 * vBead.y, 1e-3 ), rm = max( ra, rb );
            N = normalize( ( N - ns * vSide - nu * vUp ) + vSide * ( ns * rm / ra ) + vUp * ( nu * rm / rb ) );
            vec3 L = normalize( vec3( -0.35, 0.6, 0.72 ) );
            float diff = max( dot( N, L ), 0.0 );
            float spec = pow( max( dot( N, normalize( L + toCam ) ), 0.0 ), 36.0 ) * 0.22;
            diffuseColor.rgb = diffuseColor.rgb * ( 0.34 + 0.76 * diff ) + spec;
          }
        #endif`);
    };
    return m;
  }

  function ensureMaterials() {
    if (!lineMat) {
      lineMat = shadedLineMaterial(); lineMatPartial = shadedLineMaterial();
      thinMat = new THREE.LineBasicMaterial({ vertexColors: true });
    }
    lineMat.linewidth = lineWidth(); lineMatPartial.linewidth = lineWidth();
    resize();
  }

  function buildPaths() {
    const n = job.moves, F = job.flags, P = job.pts;
    let segs = 0, travels = 0;
    for (let k = 0; k < n; k++) { if (F[k] & C.FL_SKIP) continue; if (F[k] & C.FL_EXTRUDE) segs++; else if (F[k] & C.FL_TRAVEL) travels++; }
    const segMove = new Uint32Array(segs), extPrefix = new Uint32Array(n + 1), travelPrefix = new Uint32Array(n + 1);
    const pos = new Float32Array(segs * 6), tpos = new Float32Array(Math.max(1, travels) * 6);
    const bead = new Float32Array(Math.max(1, segs) * 2);
    // "Actual cross-section": each line as wide and tall as the G-code makes it, its centre half its
    // height below the nozzle (where the plastic is). "Uniform": one width, centred on the path.
    const real = prefs.lines !== 'uniform', lw = lineWidth();
    let s = 0, tr = 0;
    for (let k = 0; k < n; k++) {
      extPrefix[k] = s; travelPrefix[k] = tr;
      if (F[k] & C.FL_SKIP) continue;               // blocks the printer won't run are not drawn
      if (F[k] & C.FL_EXTRUDE) {
        segMove[s] = k;
        pos.set(P.subarray(k * 3, k * 3 + 6), s * 6);
        if (real && job.beadW[k] > 0) {
          bead[s * 2] = job.beadW[k]; bead[s * 2 + 1] = job.beadH[k];
          pos[s * 6 + 2] -= job.beadH[k] / 2; pos[s * 6 + 5] -= job.beadH[k] / 2;
        } else { bead[s * 2] = lw; bead[s * 2 + 1] = lw; }
        s++;
      } else if (F[k] & C.FL_TRAVEL) {
        tpos.set(P.subarray(k * 3, k * 3 + 6), tr * 6);
        tr++;
      }
    }
    extPrefix[n] = s; travelPrefix[n] = tr;
    R.segMove = segMove; R.extPrefix = extPrefix; R.travelPrefix = travelPrefix; R.pos = pos; R.bead = bead;
    R.col = new Float32Array(segs * 6);
    computeColors();
    rebuildObjects();
    // travel lines
    if (R.travel) disposeObj(R.travel);
    const tg = new THREE.BufferGeometry(); tg.setAttribute('position', new THREE.BufferAttribute(tpos, 3)); tg.setDrawRange(0, 0);
    R.travel = new THREE.LineSegments(tg, new THREE.LineBasicMaterial({ color: 0x4fa3ff, transparent: true, opacity: 0.55 }));
    R.travel.frustumCulled = false;
    bedGroup.add(R.travel);
  }

  function rebuildObjects() {
    ensureMaterials();
    disposeObj(R.main); disposeObj(R.layerObj); disposeObj(R.partial);
    R.main = makeLines(R.pos, R.col, 0, R.bead); bedGroup.add(R.main);
    R.layerObj = null; R.layerObjLayer = -1;
    const pg = new THREE.LineSegmentsGeometry();
    pg.setPositions(new Float32Array(6)); pg.setColors(new Float32Array(6));
    pg.setAttribute('instanceBead', new THREE.InstancedBufferAttribute(new Float32Array(2), 2));
    R.partial = prefs.lines === 'thin'
      ? (() => { const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
                 g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(6), 3)); const o = new THREE.LineSegments(g, thinMat); o.userData.thin = true; o.frustumCulled = false; return o; })()
      : (() => { const o = new THREE.LineSegments2(pg, lineMatPartial); o.frustumCulled = false; return o; })();
    bedGroup.add(R.partial);
    lastShown = -1;
  }

  /* What's under the cursor, for the camera: the nearest visible line the view ray passes through
     (within its own width, plus a few pixels so thin lines are easy to hit). Returns the world point
     under the cursor at that line's depth, or null. A plain loop over the drawn segments: ~10 ms per million. */
  controls.pick = (rr) => {
    if (!job || !R.pos || !R.segMove.length) return null;
    const off = bedGroup.position;
    const ox = rr.origin.x - off.x, oy = rr.origin.y - off.y, oz = rr.origin.z - off.z;
    const dx = rr.direction.x, dy = rr.direction.y, dz = rr.direction.z;
    const pxAng = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) / (canvas.clientHeight || 1);
    const done = R.extPrefix[Math.min(curMove, job.moves)] || 0;
    let a = 0, b = done;
    if (prefs.layerOnly && R.layerObj) a = R.layerObj.userData.base;
    const pos = R.pos, bead = R.bead, thin = prefs.lines === 'thin', lw = lineWidth();
    let bestT = Infinity, bx = 0, by = 0, bz = 0;
    for (let s = a; s < b; s++) {
      const i = s * 6;
      const ax = pos[i], ay = pos[i + 1], az = pos[i + 2];
      const ux = pos[i + 3] - ax, uy = pos[i + 4] - ay, uz = pos[i + 5] - az;
      // closest points between the ray o + t d and the segment a + u v, v in [0, 1]
      const wx = ox - ax, wy = oy - ay, wz = oz - az;
      const uu = ux * ux + uy * uy + uz * uz, ud = ux * dx + uy * dy + uz * dz;
      const uw = ux * wx + uy * wy + uz * wz, dw = dx * wx + dy * wy + dz * wz;
      const den = uu - ud * ud;
      let v = den > 1e-12 ? (uw - ud * dw) / den : 0;
      v = v < 0 ? 0 : v > 1 ? 1 : v;
      const px = ax + ux * v, py = ay + uy * v, pz = az + uz * v;
      let t = (px - ox) * dx + (py - oy) * dy + (pz - oz) * dz;
      if (t <= 0 || t >= bestT) continue;
      const ex = ox + dx * t - px, ey = oy + dy * t - py, ez = oz + dz * t - pz;
      const rb = thin ? 0.05 : (bead ? Math.max(bead[s * 2], bead[s * 2 + 1]) : lw) * 0.5;
      const r = rb + t * pxAng * 4, e2 = ex * ex + ey * ey + ez * ez;
      if (e2 > r * r) continue;
      // the spot on the view ray closest to that line (under the cursor, at the line's depth), pulled
      // onto the line itself when the ray only passed near it, so zooming in ends on the plastic
      const k = e2 > rb * rb ? rb / Math.sqrt(e2) : 1;
      bestT = t; bx = px + ex * k; by = py + ey * k; bz = pz + ez * k;
    }
    return bestT < Infinity ? new THREE.Vector3(bx + off.x, by + off.y, bz + off.z) : null;
  };

  /* colour by the selected mode; also fills the legend */
  let colorRange = null;
  function percentile(vals, p) {
    if (!vals.length) return 0;
    const a = Float32Array.from(vals).sort(); return a[Math.min(a.length - 1, Math.max(0, Math.floor(p * (a.length - 1))))];
  }
  function computeColors() {
    const mode = prefs.color, segs = R.segMove.length, col = R.col, rgb = [0, 0, 0];
    const filArea = Math.PI * Math.pow(job.machine.filamentDiameter / 2, 2);
    const filColors = String(job.config.filament_colour || job.config.extruder_colour || '').split(/[;,]/).map(s => s.trim()).filter(Boolean);
    const filRGB = filColors.map(hexRGB);
    let value = null, unit = '';
    if (mode === 'speed') { value = (k) => job.vp[k]; unit = 'mm/s'; }
    else if (mode === 'fcmd') { value = (k) => job.fcmd[k]; unit = 'mm/s'; }
    else if (mode === 'flow') { value = (k) => job.plannerDur[k] > 0 ? job.de[k] * filArea / job.plannerDur[k] : 0; unit = 'mm³/s'; }
    else if (mode === 'layertime') { value = (k) => { const L = job.layers[job.layer[k]]; return L ? L.t1 - L.t0 : 0; }; unit = 's'; }
    else if (mode === 'beadh') { value = (k) => job.beadH[k]; unit = 'mm'; }
    else if (mode === 'beadw') { value = (k) => job.beadW[k]; unit = 'mm'; }
    colorRange = null;
    if (value) {
      const sample = []; const stride = Math.max(1, Math.floor(segs / 20000));
      for (let s = 0; s < segs; s += stride) sample.push(value(R.segMove[s]));
      let lo = percentile(sample, 0.01), hi = percentile(sample, 0.99);
      if (mode === 'beadh') {
        // thinned lines (scarf ramps, Z contouring) are a small share of a print: scale from 0 so they stand out
        lo = 0; hi = Math.max(percentile(sample, 0.995), 0.05);
      } else if (mode === 'beadw' && hi - lo < 0.02) {
        const mid = percentile(sample, 0.5); lo = mid * 0.75; hi = mid * 1.25;
      }
      if (hi - lo < 1e-6) { hi = lo + 1; }
      colorRange = { lo, hi, unit };
      for (let s = 0; s < segs; s++) {
        rampRGB((value(R.segMove[s]) - lo) / (hi - lo), rgb);
        col[s * 6] = col[s * 6 + 3] = rgb[0]; col[s * 6 + 1] = col[s * 6 + 4] = rgb[1]; col[s * 6 + 2] = col[s * 6 + 5] = rgb[2];
      }
    } else {
      for (let s = 0; s < segs; s++) {
        const k = R.segMove[s];
        const c = mode === 'filament' ? (filRGB[job.tool[k]] || FEAT_RGB[0]) : FEAT_RGB[featVisible[job.feat[k]] === false ? 0 : job.feat[k]];
        col[s * 6] = col[s * 6 + 3] = c[0]; col[s * 6 + 1] = col[s * 6 + 4] = c[1]; col[s * 6 + 2] = col[s * 6 + 5] = c[2];
      }
    }
    applyShade();
    renderLegend(filColors);
  }
  function applyShade() {
    shadeUniform.value = (prefs.shade === 'tube' || prefs.shade === 'layers') ? 1 : 0;
    const col = R.col, segs = R.segMove.length;
    if (prefs.shade === 'layers') {
      // alternate layers slightly brighter / darker so individual layers are easy to count
      for (let s = 0; s < segs; s++) {
        const f = (job.layer[R.segMove[s]] & 1) ? 0.84 : 1.06;
        for (let q = 0; q < 6; q++) col[s * 6 + q] = Math.min(1, col[s * 6 + q] * f);
      }
    } else if (prefs.shade === 'height') {
      const z0 = job.bed.model.minZ, z1 = Math.max(z0 + 1e-3, job.bed.model.maxZ), P = job.pts;
      for (let s = 0; s < segs; s++) {
        const z = P[R.segMove[s] * 3 + 5];
        const f = 0.45 + 0.6 * Math.max(0, Math.min(1, (z - z0) / (z1 - z0)));
        for (let q = 0; q < 6; q++) col[s * 6 + q] = Math.min(1, col[s * 6 + q] * f);
      }
    }
    dirty = true;
  }
  const featVisible = {};

  function renderLegend(filColors) {
    const el = $('legend'); const mode = prefs.color;
    let html = '';
    if (mode === 'feature') {
      const used = new Set(); for (let s = 0; s < R.segMove.length; s += 7) used.add(job.feat[R.segMove[s]]);
      html = '<h4>Line type</h4>' + C.FEATURES.map((f, i) => used.has(i)
        ? '<div class="row"><span class="sw" style="background:' + f[1] + '"></span>' + f[0] + '</div>' : '').join('');
    } else if (mode === 'filament') {
      const used = new Set(); for (let s = 0; s < R.segMove.length; s += 7) used.add(job.tool[R.segMove[s]]);
      html = '<h4>Filament</h4>' + [...used].sort((a, b) => a - b).map(t =>
        '<div class="row"><span class="sw" style="background:' + (filColors[t] || '#9aa3ab') + '"></span>Filament ' + (t + 1) + '</div>').join('');
    } else if (colorRange) {
      const title = { speed: 'Actual speed (peak)', fcmd: 'Set speed', flow: 'Volumetric flow', layertime: 'Layer time',
                      beadh: 'Line height', beadw: 'Line width' }[mode];
      const f = (v) => (colorRange.unit === 'mm' ? v.toFixed(2) : v >= 100 ? Math.round(v) : v.toFixed(1)) + ' ' + colorRange.unit;
      html = '<h4>' + title + '</h4><div class="grad" style="background:linear-gradient(90deg,' + RANGE.join(',') + ')"></div>' +
             '<div class="ends"><span>' + f(colorRange.lo) + '</span><span>' + f(colorRange.hi) + '</span></div>';
    }
    el.innerHTML = html; el.hidden = !html || !job;
  }

  /* ------------------------------------------------------------------ playback state */
  let job = null, gcodeText = null, lineStarts = null, currentMeta = {};
  let simT = 0, playing = false, lastFrame = 0, lastShown = -1, dirty = true;
  let curMove = 0;
  let hudTimer = 0;
  const bedCenter = new THREE.Vector3();

  function bedSlinger() {
    if (prefs.motion === 'bed') return true;
    if (prefs.motion === 'head') return false;
    return !!(job && job.bed.bedSlinger);
  }

  function nozzleAt(t) {
    const k = C.moveAt(job, t);
    const st = C.stateIn(job, k, t);
    const P = job.pts, a = k * 3;
    return { k, frac: st.frac, v: st.v,
             x: P[a] + (P[a + 3] - P[a]) * st.frac, y: P[a + 1] + (P[a + 4] - P[a + 1]) * st.frac, z: P[a + 2] + (P[a + 5] - P[a + 2]) * st.frac };
  }

  function setLayerOnlyObject(layerIdx) {
    if (R.layerObjLayer === layerIdx && R.layerObj) return;
    disposeObj(R.layerObj); R.layerObj = null; R.layerObjLayer = layerIdx;
    const L = job.layers[layerIdx]; if (!L) return;
    const a = R.extPrefix[L.first], b = R.extPrefix[layerIdx + 1 < job.layers.length ? job.layers[layerIdx + 1].first : job.moves];
    const pos = R.pos.slice(a * 6, b * 6), col = R.col.slice(a * 6, b * 6), bead = R.bead.slice(a * 2, Math.max(a + 1, b) * 2);
    R.layerObj = makeLines(pos, col, 0, bead); R.layerObj.userData.base = a;
    bedGroup.add(R.layerObj);
  }

  const tmpCol = [0, 0, 0];
  function updateScene(force) {
    if (!job) return;
    const nz = nozzleAt(simT);
    curMove = nz.k;
    const F = job.flags;
    const done = R.extPrefix[nz.k];           // segments fully printed before this move
    const layerIdx = job.layer[nz.k];

    if (prefs.layerOnly) {
      R.main.visible = false;
      setLayerOnlyObject(layerIdx);
      if (R.layerObj) { R.layerObj.visible = true; setCount(R.layerObj, Math.max(0, done - R.layerObj.userData.base)); }
    } else {
      R.main.visible = true; if (R.layerObj) R.layerObj.visible = false;
      if (done !== lastShown || force) { setCount(R.main, done); lastShown = done; }
    }

    // the segment being extruded right now, drawn up to the nozzle
    if ((F[nz.k] & C.FL_EXTRUDE) && nz.frac > 0) {
      const P = job.pts, a = nz.k * 3, s = done;
      const thin = R.partial.userData.thin;
      const dz = thin ? 0 : R.pos[s * 6 + 2] - P[a + 2];      // same bead offset as the finished line
      const p = new Float32Array([P[a], P[a + 1], P[a + 2] + dz, nz.x, nz.y, nz.z + dz]);
      const c = R.col.slice(s * 6, s * 6 + 6);
      if (thin) {
        R.partial.geometry.attributes.position.array.set(p); R.partial.geometry.attributes.position.needsUpdate = true;
        R.partial.geometry.attributes.color.array.set(c); R.partial.geometry.attributes.color.needsUpdate = true;
      } else {
        R.partial.geometry.setPositions(p); R.partial.geometry.setColors(c);
        const bd = R.partial.geometry.attributes.instanceBead;
        bd.array[0] = R.bead[s * 2]; bd.array[1] = R.bead[s * 2 + 1]; bd.needsUpdate = true;
      }
      R.partial.visible = true;
    } else R.partial.visible = false;

    // travel moves of the current layer up to now
    R.travel.visible = prefs.travel;
    if (prefs.travel) {
      const L = job.layers[layerIdx];
      const a = R.travelPrefix[L ? L.first : 0], b = R.travelPrefix[nz.k + ((F[nz.k] & C.FL_TRAVEL) && nz.frac >= 1 ? 1 : 0)];
      R.travel.geometry.setDrawRange(a * 2, Math.max(0, b - a) * 2);
    }

    // nozzle, bed and gantry
    const slinger = bedSlinger();
    const cy = (job.bed.y0 + job.bed.y1) / 2;
    if (slinger) {
      bedGroup.position.set(0, cy - nz.y, 0);
      headGroup.position.set(nz.x, cy, nz.z);
      gantry.position.set((job.bed.x0 + job.bed.x1) / 2, cy, nz.z + 12);
    } else {
      bedGroup.position.set(0, 0, 0);
      headGroup.position.set(nz.x, nz.y, nz.z);
      gantry.position.set((job.bed.x0 + job.bed.x1) / 2, nz.y, nz.z + 12);
    }
    if (prefs.follow) {
      const target = headGroup.position.clone();
      const delta = target.sub(controls.target).multiplyScalar(0.18);
      controls.target.add(delta); camera.position.add(delta);
    }
    hudState = nz;
    dirty = true;
  }

  let hudState = null;
  function updateHud() {
    if (!job || !hudState) return;
    const nz = hudState, k = nz.k, L = job.layer[k], layer = job.layers[L];
    const startOffset = job.layers[0] && job.layers[0].start ? 1 : 0;
    const layerCount = job.layers.length - startOffset;
    $('hTime').textContent = fmtTime(simT);
    $('hTotal').textContent = fmtTime(job.total);
    $('hRemain').textContent = fmtLong(Math.max(0, job.total - simT));
    if (layer && layer.start) $('hLayer').textContent = 'start G-code';
    else $('hLayer').textContent = (L + 1 - startOffset) + ' / ' + layerCount;
    const lp = layer ? (simT - layer.t0) / Math.max(1e-6, layer.t1 - layer.t0) : 0;
    $('hLayerBar').style.width = Math.round(Math.max(0, Math.min(1, lp)) * 100) + '%';
    $('hZ').textContent = nz.z.toFixed(2) + ' mm' + (layer && layer.h ? '  ·  h ' + layer.h.toFixed(2) : '');
    const F = job.flags[k];
    let kind;
    if (F & C.FL_DWELL) kind = '<span class="muted">Waiting</span>';
    else if (F & C.FL_EONLY) kind = '<span class="muted">' + (job.de[k] < 0 ? 'Retract' : (job.feat[k] === 18 ? 'Flush / purge' : 'Unretract / prime')) + '</span>';
    else if (F & C.FL_TRAVEL) kind = '<span class="muted">Travel</span>';
    else { const f = C.FEATURES[job.feat[k]]; kind = '<span class="dot" style="background:' + f[1] + '"></span>' + f[0]; }
    $('hFeat').innerHTML = kind;
    const slow = job.aligned && job.plannerDur[k] > 0 ? 1 : 1;
    $('hSpeed').textContent = Math.round(nz.v * slow) + ' mm/s';
    $('hSpeedSet').textContent = (F & C.FL_DWELL) ? '' : 'of ' + Math.round(job.fcmd[k]) + ' set';
    const filArea = Math.PI * Math.pow(job.machine.filamentDiameter / 2, 2);
    const flow = (F & C.FL_EXTRUDE) && job.len[k] > 0 ? nz.v * job.de[k] / job.len[k] * filArea : 0;
    $('hFlow').textContent = (F & C.FL_EXTRUDE) ? flow.toFixed(1) + ' mm³/s' : '–';
    $('hBead').textContent = (F & C.FL_EXTRUDE) && job.beadW[k] > 0 ? job.beadW[k].toFixed(2) + ' × ' + job.beadH[k].toFixed(2) + ' mm' : '–';
    $('hAcc').textContent = (F & C.FL_DWELL) ? '–' : Math.round(job.ac[k]) + ' mm/s²';
    const fc = String(job.config.filament_colour || '').split(/[;,]/)[job.tool[k]];
    $('hTool').innerHTML = (fc ? '<span class="dot" style="background:' + fc.trim() + '"></span>' : '') + (job.tool[k] + 1);
    $('hSrc').textContent = sourceLine(job.line[k]);
    if (codeOpen) {
      const cur = job.line[k];
      if (cur !== codeLastCur) { codeLastCur = cur; codeFollowTo(!playing); renderCode(); }
    }
    // bottom bar
    $('cTime').textContent = fmtTime(simT); $('cTotal').textContent = fmtTime(job.total);
    $('cPct').textContent = Math.floor(simT / Math.max(1e-9, job.total) * 100) + '%';
    if (document.activeElement !== $('layerIn')) $('layerIn').value = Math.max(1, L + 1 - startOffset);
    drawTimeline();
  }

  function ensureLineStarts() {
    if (!lineStarts && gcodeText) {
      // index line starts once, lazily
      const starts = [0]; let i = -1;
      while ((i = gcodeText.indexOf('\n', i + 1)) >= 0) starts.push(i + 1);
      if (starts[starts.length - 1] >= gcodeText.length) starts.pop();     // no empty last line
      lineStarts = Uint32Array.from(starts);
    }
    return lineStarts;
  }
  function lineText(no, max) {
    if (!gcodeText || !no || !ensureLineStarts() || no > lineStarts.length) return '';
    const a = lineStarts[no - 1], b = no < lineStarts.length ? lineStarts[no] - 1 : gcodeText.length;
    return gcodeText.substring(a, Math.min(b, a + (max || 200))).replace(/\r$/, '');
  }
  function sourceLine(no) { return no ? no + ':  ' + lineText(no, 160).trim() : ''; }

  /* ------------------------------------------------------------------ G-code panel
     A virtual list: only the rows in view exist, so a million-line file scrolls as easily as a
     short one. While following, it glides to keep the running line centred; scrolling by hand
     pauses following until "Follow" is pressed again. Clicking a line seeks to it. */
  const ROW = 18, MAX_SCROLL_H = 1.2e7;
  const codeScroll = $('codeScroll'), codeRows = $('codeRows'), codeSpacer = $('codeSpacer');
  let codeOpen = false, codeFollow = true, codeTarget = null, codeLastCur = -1, flashLine = 0, flashUntil = 0;
  function codeCount() { return ensureLineStarts() ? lineStarts.length : 0; }
  function codeGeom() {
    const n = codeCount(), view = codeScroll.clientHeight || 288;
    const realH = n * ROW, H = Math.min(realH, MAX_SCROLL_H), vis = Math.floor(view / ROW);
    return { n, view, H, scaled: realH > MAX_SCROLL_H, vis };
  }
  function firstLineAt(top, g) {      // 0-based index of the first row shown for a scrollTop
    if (!g.scaled) return Math.floor(top / ROW);
    return Math.round(top / Math.max(1, g.H - g.view) * Math.max(0, g.n - g.vis));
  }
  function scrollTopFor(first, g) {
    first = Math.max(0, Math.min(Math.max(0, g.n - g.vis), first));
    if (!g.scaled) return first * ROW;
    return first / Math.max(1, g.n - g.vis) * Math.max(1, g.H - g.view);
  }
  const escHtml = (t) => t.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  function highlight(t) {
    let code = t, comment = '';
    const c = t.indexOf(';'); if (c >= 0) { code = t.substring(0, c); comment = t.substring(c); }
    let html = escHtml(code).replace(/^(\s*)([GMT]\d+(?:\.\d+)?)/i, (m, sp, cmd) =>
      sp + '<span class="' + (/^[mt]/i.test(cmd) ? 'km' : 'k') + '">' + cmd + '</span>');
    html = html.replace(/(\s)([XYZEFIJRSP])(?=[-\d.])/g, '$1<span class="a">$2</span>');
    if (comment) html += '<span class="c">' + escHtml(comment) + '</span>';
    return html;
  }
  function renderCode() {
    if (!codeOpen || !job) return;
    const g = codeGeom();
    codeSpacer.style.height = g.H + 'px';
    const top = codeScroll.scrollTop, first = firstLineAt(top, g);
    const offset = g.scaled ? top : first * ROW;
    const cur = job.line[curMove] || 0;
    let html = '';
    for (let i = first; i < Math.min(g.n, first + g.vis + 3); i++) {
      const no = i + 1;
      html += '<div class="ln' + (no === cur ? ' cur' : no < cur ? ' past' : '') + (no === flashLine && performance.now() < flashUntil ? ' flash' : '') + '" data-line="' + no + '"><span class="no">' + no +
              '</span><span class="tx">' + highlight(lineText(no, 220)) + '</span></div>';
    }
    codeRows.style.transform = 'translateY(' + offset + 'px)';
    codeRows.innerHTML = html;
    $('codeInfo').textContent = 'Line ' + (cur || '–') + ' of ' + g.n.toLocaleString();
  }
  /* Following keeps the running line pinned to the middle row. While playing it moves straight
     there (an eased glide falls behind at high speeds and the highlight drifts out of view);
     the glide is only used for one-off jumps, such as pressing Follow. */
  function codeFollowTo(animate) {
    if (!codeOpen || !codeFollow || !job) return;
    const g = codeGeom(), cur = (job.line[curMove] || 1) - 1;
    const target = scrollTopFor(cur - Math.floor((g.vis - 1) / 2), g);
    if (!animate || playing || Math.abs(target - codeScroll.scrollTop) > g.view * 40) { setCodeScroll(target); codeTarget = null; }
    else codeTarget = target;
  }
  function setCodeScroll(v) { codeScroll.scrollTop = v; renderCode(); }
  function stepCodeScroll() {      // called every animation frame: ease towards the target
    if (codeTarget == null || !codeOpen) return;
    const cur = codeScroll.scrollTop, d = codeTarget - cur;
    if (Math.abs(d) < 0.6) { setCodeScroll(codeTarget); codeTarget = null; return; }
    setCodeScroll(cur + d * 0.22);
  }
  function setFollow(on) {
    codeFollow = on; $('codeFollow').classList.toggle('on', on);
    $('codeFollow').textContent = on ? 'Following' : 'Follow';
    if (on) codeFollowTo(true);
  }
  function setCodeOpen(open) {
    codeOpen = open && !!job;
    $('codePanel').classList.toggle('open', codeOpen);
    $('codePanel').setAttribute('aria-hidden', String(!codeOpen));
    $('codeToggle').setAttribute('aria-expanded', String(codeOpen));
    if (codeOpen) { renderCode(); setFollow(true); codeFollowTo(false); }
  }
  $('codeToggle').onclick = () => setCodeOpen(!codeOpen);
  $('codeFollow').onclick = () => setFollow(true);
  codeScroll.addEventListener('scroll', renderCode);
  // only real user input stops following (programmatic scrolls must not)
  const userScrolled = () => { if (codeFollow) setFollow(false); codeTarget = null; };
  codeScroll.addEventListener('wheel', userScrolled, { passive: true });
  codeScroll.addEventListener('touchstart', userScrolled, { passive: true });
  codeScroll.addEventListener('pointerdown', (e) => { if (e.target === codeScroll) userScrolled(); });   // scrollbar drag
  codeScroll.addEventListener('keydown', (e) => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(e.key)) { e.stopPropagation(); userScrolled(); }
  });
  codeRows.addEventListener('click', (e) => {
    const row = e.target.closest('.ln'); if (!row || !job) return;
    const no = parseInt(row.dataset.line, 10);
    // the first move at or after this line; comments and settings jump to the move that follows
    const L = job.line; let lo = 0, hi = job.moves - 1;
    if (!(hi >= 0)) return;
    if (no > L[hi]) { seek(job.total); }
    else {
      while (lo < hi) { const mid = (lo + hi) >> 1; if (L[mid] < no) lo = mid + 1; else hi = mid; }
      seek(job.t0[lo] + (job.dur[lo] > 0 ? Math.min(1e-4, job.dur[lo] / 2) : 0));
    }
    flashLine = no; flashUntil = performance.now() + 600;
    renderCode();
  });

  /* ------------------------------------------------------------------ timeline */
  const tlc = $('tlc'), tg = tlc.getContext('2d');
  let tlHover = -1;
  function drawTimeline() {
    const dpr = window.devicePixelRatio || 1, w = tlc.clientWidth, h = tlc.clientHeight;
    if (tlc.width !== Math.round(w * dpr) || tlc.height !== Math.round(h * dpr)) { tlc.width = Math.round(w * dpr); tlc.height = Math.round(h * dpr); }
    tg.setTransform(dpr, 0, 0, dpr, 0, 0);
    tg.clearRect(0, 0, w, h);
    const fg = cssVar('--fg', '#ddd'), accent = cssVar('--accent', '#009688');
    const trackY = 14, trackH = 12;
    tg.fillStyle = 'rgba(127,137,142,.18)';
    roundRect(tg, 0, trackY, w, trackH, 6); tg.fill();
    if (!job) return;
    const X = (t) => (t / Math.max(1e-9, job.total)) * w;
    // layer bands: alternating shades, so long layers read as long
    for (let i = 0; i < job.layers.length; i++) {
      const L = job.layers[i]; const x0 = X(L.t0), x1 = X(L.t1);
      if (i % 2) { tg.fillStyle = 'rgba(127,137,142,.12)'; tg.fillRect(x0, trackY, Math.max(0.5, x1 - x0), trackH); }
    }
    tg.save(); roundRect(tg, 0, trackY, w, trackH, 6); tg.clip();
    tg.fillStyle = accent; tg.globalAlpha = 0.85; tg.fillRect(0, trackY, X(simT), trackH); tg.globalAlpha = 1; tg.restore();
    // layer ticks
    const n = job.layers.length, every = n > 400 ? 50 : n > 150 ? 20 : n > 50 ? 10 : 5;
    tg.fillStyle = fg; tg.globalAlpha = 0.35;
    const startOffset = job.layers[0] && job.layers[0].start ? 1 : 0;
    for (let i = startOffset; i < n; i++) {
      const num = i + 1 - startOffset;
      if (num % every) continue;
      const x = X(job.layers[i].t0); tg.fillRect(x, trackY + trackH, 1, 4);
    }
    tg.globalAlpha = 1;
    // events
    const filColors = String(job.config.filament_colour || '').split(/[;,]/);
    for (const ev of job.events) {
      const t = ev.move < job.moves ? job.t0[ev.move] : job.total, x = X(t);
      tg.fillStyle = ev.kind === 'pause' ? '#d9534f' : ev.kind === 'heat' ? '#e0913a' : (filColors[ev.tool] || '#7fb2ff').trim();
      tg.beginPath(); tg.moveTo(x, trackY - 1); tg.lineTo(x - 5, trackY - 9); tg.lineTo(x + 5, trackY - 9); tg.closePath(); tg.fill();
      tg.strokeStyle = 'rgba(0,0,0,.4)'; tg.lineWidth = 1; tg.stroke();
    }
    // playhead
    const px = X(simT);
    tg.fillStyle = fg; tg.fillRect(Math.round(px) - 1, trackY - 3, 2, trackH + 6);
    if (tlHover >= 0) { tg.fillStyle = fg; tg.globalAlpha = .4; tg.fillRect(Math.round(tlHover), trackY, 1, trackH); tg.globalAlpha = 1; }
  }
  function roundRect(g, x, y, w, h, r) {
    g.beginPath(); g.moveTo(x + r, y); g.lineTo(x + w - r, y); g.quadraticCurveTo(x + w, y, x + w, y + r);
    g.lineTo(x + w, y + h - r); g.quadraticCurveTo(x + w, y + h, x + w - r, y + h); g.lineTo(x + r, y + h);
    g.quadraticCurveTo(x, y + h, x, y + h - r); g.lineTo(x, y + r); g.quadraticCurveTo(x, y, x + r, y); g.closePath();
  }
  function timeAtX(clientX) {
    const r = tlc.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * (job ? job.total : 0);
  }
  let dragging = false;
  $('tl').addEventListener('pointerdown', (e) => { if (!job) return; dragging = true; $('tl').setPointerCapture(e.pointerId); seek(timeAtX(e.clientX)); });
  $('tl').addEventListener('pointermove', (e) => {
    if (!job) return;
    const r = tlc.getBoundingClientRect(); tlHover = e.clientX - r.left;
    const t = timeAtX(e.clientX);
    if (dragging) seek(t);
    const k = C.moveAt(job, t), L = job.layer[k], so = job.layers[0] && job.layers[0].start ? 1 : 0;
    const ev = job.events.find(ev => Math.abs(((ev.move < job.moves ? job.t0[ev.move] : job.total) - t) / job.total * r.width) < 6);
    const tip = $('tip'); tip.style.display = 'block'; tip.style.left = Math.max(60, Math.min(r.width - 60, tlHover)) + 'px';
    tip.textContent = fmtTime(t) + '  ·  ' + (job.layers[L] && job.layers[L].start ? 'start' : 'layer ' + (L + 1 - so)) + (ev ? '  ·  ' + ev.label : '');
    drawTimeline();
  });
  $('tl').addEventListener('pointerup', () => { dragging = false; });
  $('tl').addEventListener('pointerleave', () => { tlHover = -1; $('tip').style.display = 'none'; drawTimeline(); });

  /* ------------------------------------------------------------------ transport */
  function seek(t) {
    if (!job) return;
    simT = Math.max(0, Math.min(job.total, t));
    updateScene(true); updateHud();
  }
  function setPlaying(p) {
    if (!job) p = false;
    if (p && simT >= job.total - 1e-6) simT = 0;
    playing = p; lastFrame = performance.now();
    $('playIco').innerHTML = p ? '<rect x="6.5" y="5" width="4" height="14" rx="1"/><rect x="13.5" y="5" width="4" height="14" rx="1"/>'
                               : '<path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/>';
  }
  function stepMove(dir) {
    if (!job) return; setPlaying(false);
    let k = C.moveAt(job, simT);
    if (dir > 0) { k++; while (k < job.moves - 1 && job.dur[k] <= 0) k++; seek(k < job.moves ? job.t0[k] + job.dur[k] : job.total); }
    else { const atStart = simT - job.t0[k] < 1e-6; k = atStart ? k - 1 : k; while (k > 0 && job.dur[k] <= 0) k--; seek(Math.max(0, job.t0[Math.max(0, k)])); }
  }
  function stepLayer(dir) {
    if (!job) return;
    // layer steps land on the end of a layer, so the layer is shown complete
    const L = job.layer[C.moveAt(job, simT)];
    const endOf = (i) => Math.max(job.layers[i].t0, job.layers[i].t1 - 1e-4);
    if (dir > 0) {
      if (simT < endOf(L) - 1e-3) seek(endOf(L));
      else seek(L + 1 < job.layers.length ? endOf(L + 1) : job.total);
    } else seek(L > 0 ? endOf(L - 1) : 0);
  }
  function gotoLayer(num) {
    if (!job) return;
    const so = job.layers[0] && job.layers[0].start ? 1 : 0;
    const i = Math.max(0, Math.min(job.layers.length - 1, num - 1 + so));
    seek(job.layers[i].t1 - 1e-6);
  }
  $('play').onclick = () => setPlaying(!playing);
  $('bStart').onclick = () => { setPlaying(false); seek(0); };
  $('bEnd').onclick = () => { setPlaying(false); seek(job ? job.total : 0); };
  $('bPrevM').onclick = () => stepMove(-1);
  $('bNextM').onclick = () => stepMove(1);
  $('bPrevL').onclick = () => stepLayer(-1);
  $('bNextL').onclick = () => stepLayer(1);
  $('layerIn').addEventListener('change', () => gotoLayer(parseInt($('layerIn').value, 10) || 1));
  /* Playback speed: presets, or any multiplier typed into the custom box (0.01× – 10000×). */
  const presetSpeeds = () => [...$('speedSel').options].map(o => parseFloat(o.value)).filter(v => isFinite(v));
  const fmtSpeed = (v) => (Math.round(v * 1000) / 1000) + '×';
  function showSpeed() {
    const isPreset = presetSpeeds().some(v => Math.abs(v - prefs.speed) < 1e-9);
    $('speedSel').value = isPreset ? String(presetSpeeds().find(v => Math.abs(v - prefs.speed) < 1e-9)) : 'custom';
    $('speedCustomWrap').hidden = isPreset;
    if (!isPreset && document.activeElement !== $('speedCustom')) $('speedCustom').value = prefs.speed;
  }
  function setSpeed(v, announce) {
    if (!isFinite(v) || v <= 0) return;
    prefs.speed = Math.min(10000, Math.max(0.01, v)); savePrefs(); showSpeed();
    if (announce) toast('Playback ' + fmtSpeed(prefs.speed));
  }
  $('speedSel').onchange = () => {
    if ($('speedSel').value === 'custom') {
      $('speedCustomWrap').hidden = false; $('speedCustom').value = prefs.speed; $('speedCustom').focus(); $('speedCustom').select();
    } else setSpeed(parseFloat($('speedSel').value));
  };
  $('speedCustom').addEventListener('change', () => setSpeed(parseFloat($('speedCustom').value)));
  $('speedCustom').addEventListener('keydown', (e) => { if (e.key === 'Enter') { setSpeed(parseFloat($('speedCustom').value)); $('speedCustom').blur(); } });
  function bumpSpeed(dir) {
    // the next preset above (or below) the current speed, custom values included
    const opts = presetSpeeds().sort((p, q) => p - q);
    const next = dir > 0 ? opts.find(v => v > prefs.speed + 1e-9) : [...opts].reverse().find(v => v < prefs.speed - 1e-9);
    if (next != null) setSpeed(next, true);
  }

  document.addEventListener('keydown', (e) => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT')) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (X.open) return;
    switch (e.key) {
      case 'e': case 'E': if (job) { e.preventDefault(); openExport(); } break;
      case ' ': e.preventDefault(); setPlaying(!playing); break;
      case 'ArrowRight': e.preventDefault(); stepMove(1); break;
      case 'ArrowLeft': e.preventDefault(); stepMove(-1); break;
      case 'ArrowUp': e.preventDefault(); stepLayer(1); break;
      case 'ArrowDown': e.preventDefault(); stepLayer(-1); break;
      case 'Home': setPlaying(false); seek(0); break;
      case 'End': setPlaying(false); seek(job ? job.total : 0); break;
      case '+': case '=': bumpSpeed(1); break;
      case '-': case '_': bumpSpeed(-1); break;
      case 't': case 'T': toggle('travel', $('tTravel')); break;
      case 'l': case 'L': toggle('layerOnly', $('tLayer')); break;
      case 'f': case 'F': toggle('follow', $('tFollow')); break;
      case 'g': case 'G': setCodeOpen(!codeOpen); break;
    }
  });

  /* ------------------------------------------------------------------ options */
  function toggle(key, btn) { prefs[key] = !prefs[key]; btn.classList.toggle('on', prefs[key]); savePrefs(); updateScene(true); }
  function syncOptionUI() {
    $('tTravel').classList.toggle('on', prefs.travel); $('tLayer').classList.toggle('on', prefs.layerOnly);
    $('tFollow').classList.toggle('on', prefs.follow);
    $('colorSel').value = prefs.color; $('motionSel').value = prefs.motion; $('lineSel').value = prefs.lines;
    $('timingSel').value = prefs.timing; showSpeed();
    $('pauseLeaveChk').checked = prefs.pauseOnLeave !== false;
    $('headChk').checked = prefs.head !== false; $('gantryChk').checked = prefs.gantry !== false;
    $('shadeSel').value = prefs.shade || 'tube';
    headGroup.visible = prefs.head !== false; gantry.visible = prefs.gantry !== false;
  }
  $('optBtn').onclick = (e) => { e.stopPropagation(); $('optPanel').hidden = !$('optPanel').hidden; $('optBtn').classList.toggle('on', !$('optPanel').hidden); };
  document.addEventListener('pointerdown', (e) => {
    if (!$('optPanel').hidden && !$('optPanel').contains(e.target) && e.target !== $('optBtn') && !$('optBtn').contains(e.target)) {
      $('optPanel').hidden = true; $('optBtn').classList.remove('on');
    }
  });
  (function about() {
    const info = window.PLAYBACK_ABOUT; if (!info) return;
    $('verText').textContent = 'Real G-code Playback v' + info.version;
    const esc = (t) => String(t).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    $('changelog').innerHTML = info.entries.map(e => '<h5>v' + esc(e.version) + ' <span>' + esc(e.date || '') + '</span></h5><ul>' +
      e.changes.map(c => '<li>' + esc(c) + '</li>').join('') + '</ul>').join('');
    $('logLink').onclick = (ev) => { ev.preventDefault(); $('changelog').hidden = !$('changelog').hidden; };
  })();
  /* Print options found in this G-code (Bambu conditional blocks). Changing one re-reads the file
     with the new choice and keeps the playback position. */
  function renderFlags() {
    const box = $('flagList');
    const found = job && job.flagsFound ? job.flagsFound : [];
    box.hidden = !found.length;
    if (!found.length) { box.innerHTML = ''; return; }
    const esc = (t) => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    box.innerHTML = '<div class="flagHead">Print options in this G-code</div>' + found.map(f =>
      '<label class="check" title="' + esc(f.name) + '"><input type="checkbox" data-flag="' + esc(f.name) + '"' + (f.value ? ' checked' : '') + '> ' +
      esc(f.label) + (f.count > 1 ? ' <span class="muted">×' + f.count + '</span>' : '') + '</label>').join('') +
      '<div class="flagNote">Choose them as you will when sending the print. Heating time is not counted.</div>';
    box.querySelectorAll('input[data-flag]').forEach(inp => inp.onchange = () => {
      prefs.flags = Object.assign({}, prefs.flags, { [inp.dataset.flag]: inp.checked }); savePrefs();
      reparse();
    });
  }
  async function reparse() {
    if (!job || !gcodeText) return;
    const frac = simT / Math.max(1e-9, job.total), wasPlaying = playing, before = job.total;
    await loadText(gcodeText, Object.assign({}, currentMeta, { keepFrac: frac, keepView: true }));
    if (job) toast('Print time ' + (job.total < before ? '−' : '+') + fmtLong(Math.abs(job.total - before)) + ' → ' + fmtLong(job.total));
    if (wasPlaying) setPlaying(true);
  }
  $('pauseLeaveChk').onchange = () => { prefs.pauseOnLeave = $('pauseLeaveChk').checked; savePrefs(); };
  $('headChk').onchange = () => { prefs.head = $('headChk').checked; headGroup.visible = prefs.head; savePrefs(); dirty = true; };
  $('gantryChk').onchange = () => { prefs.gantry = $('gantryChk').checked; gantry.visible = prefs.gantry; savePrefs(); dirty = true; };
  $('shadeSel').onchange = () => { prefs.shade = $('shadeSel').value; savePrefs(); recolor(); };
  $('tTravel').onclick = () => toggle('travel', $('tTravel'));
  $('tLayer').onclick = () => toggle('layerOnly', $('tLayer'));
  $('tFollow').onclick = () => toggle('follow', $('tFollow'));
  function recolor() {
    if (!job) return;
    computeColors();
    if (R.main.userData.thin) R.main.geometry.attributes.color.needsUpdate = true; else R.main.geometry.setColors(R.col);
    R.layerObjLayer = -1; updateScene(true);
  }
  $('colorSel').onchange = () => { prefs.color = $('colorSel').value; savePrefs(); recolor(); };
  $('motionSel').onchange = () => { prefs.motion = $('motionSel').value; savePrefs(); updateScene(true); };
  $('lineSel').onchange = () => { prefs.lines = $('lineSel').value; savePrefs(); if (job) { buildPaths(); updateScene(true); } };
  $('timingSel').onchange = () => {
    prefs.timing = $('timingSel').value; savePrefs();
    if (!job) return;
    const frac = simT / job.total;
    C.applyTiming(job, prefs.timing === 'aligned');
    simT = frac * job.total; describeTiming();
    if (prefs.color === 'layertime') { computeColors(); if (R.main.userData.thin) R.main.geometry.attributes.color.needsUpdate = true; else R.main.geometry.setColors(R.col); }
    updateScene(true); updateHud();
  };

  /* ------------------------------------------------------------------ camera */
  function frame(view) {
    if (!job) return;
    const m = job.bed.model, bed = job.bed;
    const cx = (m.minX + m.maxX) / 2, cy = (m.minY + m.maxY) / 2, cz = (m.minZ + m.maxZ) / 2;
    const size = Math.max(m.maxX - m.minX, m.maxY - m.minY, m.maxZ - m.minZ, 20);
    const yOff = bedSlinger() ? bedGroup.position.y : 0;
    const target = new THREE.Vector3(cx, cy + yOff, cz);
    const d = size * 1.7 + 18;
    let dir;
    if (view === 'top') dir = new THREE.Vector3(0, -1e-5, 1);          // straight down, front of the bed at the bottom
    else if (view === 'front') dir = new THREE.Vector3(0, -1, 0.12);
    else if (view === 'bed') { const s = Math.max(bed.x1 - bed.x0, bed.y1 - bed.y0); target.set((bed.x0 + bed.x1) / 2, (bed.y0 + bed.y1) / 2 + yOff, 0); dir = new THREE.Vector3(-0.55, -1, 0.8); return place(target, dir.normalize().multiplyScalar(s * 1.6)); }
    else dir = new THREE.Vector3(-0.6, -1, 0.75);
    place(target, dir.normalize().multiplyScalar(d));
  }
  function place(target, offset) {
    controls.target.copy(target); camera.position.copy(target).add(offset); camera.updateProjectionMatrix(); controls.sync(); controls.update(); dirty = true;
  }
  $('vIso').onclick = () => frame('iso'); $('vTop').onclick = () => frame('top');
  $('vFront').onclick = () => frame('front'); $('vFit').onclick = () => frame('iso');

  function resize() {
    const r = canvas.getBoundingClientRect();
    const w = Math.max(1, r.width), h = Math.max(1, r.height);
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    if (lineMat) { lineMat.resolution.set(w, h); lineMatPartial.resolution.set(w, h); }
    dirty = true; drawTimeline();
  }
  new ResizeObserver(resize).observe($('stage'));

  function applyTheme() {
    const bg = cssVar('--bg', '#1e2023');
    scene.background = new THREE.Color(bg);
    dirty = true;
  }

  /* ------------------------------------------------------------------ main loop */
  /* Leaving the Playback tab pauses. OrcaSlicer hides the tab's web view, which the page sees as
     visibilitychange; as a second signal, a long gap between animation frames means the view was
     not being drawn (hidden), which is treated the same way. */
  let lastLoop = 0;
  /* OrcaSlicer hides a tab's panel without telling the web view inside it (on Windows the page stays
     "visible" and keeps animating), so visibilitychange alone never fires there. Clicking another tab
     does take keyboard focus away from the page, though: a window blur is treated as leaving, and the
     next focus or pointer movement inside the page as coming back. */
  let away = false;
  function onLeave() {
    away = true;
    if (playing && prefs.pauseOnLeave !== false) setPlaying(false);
  }
  function onReturn() { away = false; send({ cmd: 'check_latest' }); }
  document.addEventListener('visibilitychange', () => { if (document.hidden) onLeave(); else onReturn(); });
  window.addEventListener('pagehide', onLeave);
  window.addEventListener('blur', () => { if (!document.hasFocus()) onLeave(); });
  window.addEventListener('focus', () => { if (away) onReturn(); });
  document.addEventListener('pointermove', () => { if (away && !document.hidden) onReturn(); }, { passive: true });
  document.addEventListener('pointerdown', () => { if (away && !document.hidden) onReturn(); }, true);

  function loop(now) {
    requestAnimationFrame(loop);
    if (lastLoop && now - lastLoop > 1500) {
      // the view was hidden (no frames were drawn). If playback keeps going while away, catch the
      // clock up by the time spent away so the print has progressed when you come back.
      if (playing && prefs.pauseOnLeave === false && job) {
        simT = Math.min(job.total, simT + (now - lastLoop) / 1000 * prefs.speed);
        lastFrame = now; updateScene(true); updateHud();
      }
      onLeave(); onReturn();
    }
    lastLoop = now;
    if (codeOpen && job && playing) {
      const cur = job.line[curMove];
      if (cur !== codeLastCur) { codeLastCur = cur; codeFollowTo(false); renderCode(); }
    }
    stepCodeScroll();
    if (playing && job) {
      const dt = Math.min(0.25, (now - lastFrame) / 1000); lastFrame = now;
      simT += dt * prefs.speed;
      if (simT >= job.total) { simT = job.total; setPlaying(false); }
      updateScene(false);
      if (now - hudTimer > 90) { hudTimer = now; updateHud(); }
    }
    if (controls.update()) dirty = true;
    if (prefs.follow && job) dirty = true;
    if (dirty) { renderer.render(scene, camera); dirty = false; }
  }

  /* ------------------------------------------------------------------ loading */
  async function loadText(text, meta) {
    meta = meta || {};
    setPlaying(false);
    busy('Reading G-code…', 0); await nextFrame();
    let parsed;
    try {
      parsed = C.parseGcode(text, { flags: prefs.flags || {}, progress: (f) => { $('busyBar').style.width = Math.round(f * 85) + '%'; } });
      busy('Planning motion…', 0.88); await nextFrame();
      C.planJob(parsed, { align: prefs.timing === 'aligned' });
    } catch (err) {
      busy(null); toast('Could not read this G-code: ' + err.message, true); console.error(err); return false;
    }
    if (parsed.moves < 2) { busy(null); toast('No moves found in this file.', true); return false; }
    // a new G-code replacing one on screen (a re-slice) keeps the view and the time, unless the
    // new print is somewhere else on the bed or shorter than the moment being shown
    const prev = job ? { t: simT, model: job.bed.model } : null;
    job = parsed; gcodeText = text; lineStarts = null; codeLastCur = -1; currentMeta = meta;
    if (codeOpen) { codeScroll.scrollTop = 0; }
    busy('Building paths…', 0.95); await nextFrame();
    for (const k in featVisible) delete featVisible[k];
    buildBed(job.bed);
    buildPaths();
    $('empty').style.display = 'none';
    $('hud').hidden = false; $('viewbtns').hidden = false; $('legend').hidden = false; $('expBtn').disabled = false;
    $('fileName').textContent = meta.name || 'G-code';
    const so = job.layers[0] && job.layers[0].start ? 1 : 0;
    $('fileInfo').textContent = (job.layers.length - so) + ' layers · ' + (job.moves / 1000).toFixed(job.moves > 1e5 ? 0 : 1) + 'k moves' +
      (meta.when ? ' · ' + meta.when : '');
    $('layerIn').max = job.layers.length - so;
    describeTiming();
    if (R.segMove.length > 1200000 && prefs.lines !== 'thin')
      setTimeout(() => toast('Large print (' + Math.round(R.segMove.length / 1e5) / 10 + 'M lines). If playback stutters, use Options → Line style → Thin lines.'), 400);
    let keepView = !!meta.keepView;
    if (meta.keepFrac != null) simT = meta.keepFrac * job.total;
    else if (meta.keepTime != null) simT = Math.min(meta.keepTime, job.total);
    else if (prev) {
      simT = prev.t <= job.total ? prev.t : 0;
      const a = prev.model, b = job.bed.model;
      keepView = keepView || (a.minX <= b.maxX && b.minX <= a.maxX && a.minY <= b.maxY && b.minY <= a.maxY);
    } else simT = 0;
    if (!keepView) frame('iso');
    renderFlags();
    updateScene(true); updateHud();
    busy(null);
    return true;
  }
  function describeTiming() {
    const b = $('timingBadge'); b.hidden = false;
    if (job.aligned) {
      const adjusted = Math.abs(job.total - job.estimate) > 1;
      b.className = 'badge ok'; b.textContent = (adjusted ? 'Synced to slicer, adjusted for print options · ' : 'Synced to slicer · ') + fmtLong(job.total);
      b.title = 'Total time matches the slicer estimate (' + fmtLong(job.estimate) + '); the motion planner fills in the timing between its progress markers. Planner alone: ' + fmtLong(job.plannerTotal) + '.';
    } else {
      b.className = 'badge'; b.textContent = 'Planner estimate · ' + fmtLong(job.total);
      b.title = job.estimate ? 'Slicer estimate: ' + fmtLong(job.estimate) + '. Choose "match slicer estimate" to sync to it.'
                             : 'No slicer estimate in this file; times come from the built-in motion planner.';
    }
  }

  /* --- files: .gcode and .gcode.3mf (zip) */
  async function readZipGcodes(buf) {
    const dv = new DataView(buf), u8 = new Uint8Array(buf);
    let eocd = -1;
    for (let i = u8.length - 22; i >= Math.max(0, u8.length - 65557); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error('not a zip / 3MF file');
    const count = dv.getUint16(eocd + 10, true); let p = dv.getUint32(eocd + 16, true);
    const td = new TextDecoder(); const out = [];
    for (let i = 0; i < count; i++) {
      if (dv.getUint32(p, true) !== 0x02014b50) break;
      const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true);
      const nlen = dv.getUint16(p + 28, true), xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
      const lho = dv.getUint32(p + 42, true);
      const name = td.decode(u8.subarray(p + 46, p + 46 + nlen));
      p += 46 + nlen + xlen + clen;
      if (!/\.gcode$/i.test(name)) continue;
      const lnl = dv.getUint16(lho + 26, true), lxl = dv.getUint16(lho + 28, true);
      const data = u8.subarray(lho + 30 + lnl + lxl, lho + 30 + lnl + lxl + csize);
      out.push({ name, method, data });
    }
    return out;
  }
  async function inflate(entry) {
    if (entry.method === 0) return new TextDecoder().decode(entry.data);
    if (entry.method !== 8) throw new Error('unsupported compression in 3MF');
    if (typeof DecompressionStream === 'undefined') throw new Error('this viewer cannot unzip 3MF files; export plain G-code instead');
    const stream = new Blob([entry.data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return await new Response(stream).text();
  }
  let pendingPlates = null;
  async function openFile(file) {
    try {
      busy('Opening ' + file.name + '…', 0.02); await nextFrame();
      if (/\.3mf$/i.test(file.name)) {
        const entries = await readZipGcodes(await file.arrayBuffer());
        if (!entries.length) { busy(null); toast('This 3MF has no sliced G-code. Use a .gcode.3mf exported after slicing.', true); return; }
        pendingPlates = { file: file.name, entries };
        const sel = $('plateSel');
        sel.innerHTML = entries.map((e, i) => '<option value="' + i + '">' + (/plate_(\d+)/i.exec(e.name) ? 'Plate ' + /plate_(\d+)/i.exec(e.name)[1] : e.name) + '</option>').join('');
        sel.hidden = entries.length < 2;
        await loadPlate(0);
      } else {
        $('plateSel').hidden = true; pendingPlates = null;
        if (await loadText(await file.text(), { name: file.name, when: 'opened file' })) loadedStamp = null;
      }
    } catch (err) { busy(null); toast(err.message, true); }
  }
  async function loadPlate(i) {
    const e = pendingPlates.entries[i];
    busy('Unpacking ' + e.name + '…', 0.05); await nextFrame();
    await loadText(await inflate(e), { name: pendingPlates.file + (pendingPlates.entries.length > 1 ? ' · plate ' + (i + 1) : ''), when: 'opened file' });
  }
  $('plateSel').onchange = () => { if (pendingPlates) loadPlate(parseInt($('plateSel').value, 10)); };
  $('btnOpen').onclick = $('eOpen').onclick = () => $('file-in').click();
  $('file-in').onchange = () => { const f = $('file-in').files[0]; if (f) openFile(f); $('file-in').value = ''; };
  let dragDepth = 0;
  window.addEventListener('dragenter', (e) => { e.preventDefault(); dragDepth++; $('drop').style.display = 'grid'; });
  window.addEventListener('dragleave', (e) => { e.preventDefault(); if (--dragDepth <= 0) { dragDepth = 0; $('drop').style.display = 'none'; } });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault(); dragDepth = 0; $('drop').style.display = 'none';
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (f) openFile(f);
  });

  /* --- from the plugin: the latest slice, sent in chunks */
  let incoming = null;
  function requestLatest(quiet) {
    if (!host) { toast('Latest slice is only available inside OrcaSlicer.', true); return; }
    hideNewSlice();
    busy('Fetching the latest slice…', 0.02);
    send({ cmd: 'load_latest', quiet: !!quiet });
  }
  /* A newer slice than the one shown: load it if nothing is shown yet, otherwise ask. */
  let loadedStamp = null, dismissedStamp = null, offeredStamp = null;
  function considerLatest(latest) {
    if (!latest || !latest.stamp) return;
    if (latest.stamp === loadedStamp || latest.stamp === dismissedStamp) return;
    if (incoming || $('busy').style.display === 'grid') return;
    if (!job) { requestLatest(true); return; }
    offeredStamp = latest.stamp;
    $('newSliceWhen').textContent = latest.when ? '· ' + latest.when : '';
    $('newSlice').hidden = false;
  }
  function hideNewSlice() { $('newSlice').hidden = true; }
  $('nsLoad').onclick = () => requestLatest(false);
  $('nsKeep').onclick = () => { dismissedStamp = offeredStamp; hideNewSlice(); };
  $('btnLatest').onclick = $('eLatest').onclick = () => requestLatest(false);
  $('btnLatest').disabled = !host; $('eLatest').disabled = !host;

    function onHostMessage(msg) {
    if (!msg || typeof msg !== 'object') return;
    switch (msg.cmd) {
      case 'saved': onSaved(msg); break;
      case 'status': {
        if (msg.prefs && typeof msg.prefs === 'object') { Object.assign(prefs, msg.prefs); syncOptionUI(); }
        renderSetup(msg);
        considerLatest(msg.latest);
        break;
      }
      case 'latest_info':
        renderSetup(msg);
        if (!document.hidden) considerLatest(msg.latest);
        break;
      case 'slice_ready':
        // sliced while this tab is hidden: nothing to do now, the check runs when the tab is shown
        renderSetup(msg);
        if (!document.hidden) considerLatest(msg.latest);
        break;
      case 'gcode_begin':
        incoming = { id: msg.id, name: msg.name, size: msg.size, when: msg.when, stamp: msg.stamp, parts: new Array(msg.chunks), got: 0 };
        busy('Receiving ' + (msg.name || 'G-code') + '…', 0.02);
        break;
      case 'gcode_chunk':
        if (!incoming || msg.id !== incoming.id) break;
        incoming.parts[msg.i] = msg.data; incoming.got++;
        $('busyBar').style.width = Math.round(incoming.got / incoming.parts.length * 40) + '%';
        break;
      case 'gcode_end': {
        if (!incoming || msg.id !== incoming.id) break;
        const inc = incoming; incoming = null;
        if (inc.got !== inc.parts.length) { busy(null); toast('The G-code transfer was incomplete; try again.', true); break; }
        $('plateSel').hidden = true; pendingPlates = null;
        loadText(inc.parts.join(''), { name: inc.name, when: inc.when }).then((ok) => { if (ok) { loadedStamp = inc.stamp || null; hideNewSlice(); } });
        break;
      }
      case 'error':
        busy(null); if (!msg.quiet) toast(msg.message || 'Something went wrong', true);
        if (msg.stamp) dismissedStamp = msg.stamp;     // don't retry the same failing slice on every visit
        if (msg.setup) renderSetup(msg);
        break;
      case 'toast': toast(msg.message); break;
    }
  }
  function renderSetup(msg) {
    const steps = $('setupSteps');
    if (msg.capture_enabled === false && msg.hint) {
      steps.hidden = false;
      // numbered rows built by hand: a native <ol> picks up the host page's list styles in OrcaSlicer
      steps.innerHTML = '<div class="title">' + msg.hint.title + '</div>' +
        msg.hint.steps.map((t, i) => '<div class="step"><span class="num">' + (i + 1) + '</span><span class="txt">' + t + '</span></div>').join('');
    } else steps.hidden = true;
  }
  if (host) host.onMessage(onHostMessage);

  /* ------------------------------------------------------------------ boot */
  syncOptionUI();
  applyTheme();
  if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
  resize();
  requestAnimationFrame(loop);
  send({ cmd: 'hello' });
  // test hook: standalone page can be driven from the console / a harness
  /* ------------------------------------------------------------------ export: video and images
     Frames are rendered one by one at the chosen size and time step (not recorded off the screen),
     so a video has exact timing whatever the computer's speed. MP4 and WebM go through WebCodecs and
     a muxer; GIF through gifenc. "Whole window" images draw the page itself into an SVG
     foreignObject, with the 3D view and the timeline pasted in as pictures. */
  const X = { open: false, tab: 'video', running: false, cancel: false };
  const xs = (id) => $(id);
  function parseClock(str) {
    const t = String(str || '').trim(); if (!t) return NaN;
    if (/^\d+(\.\d+)?$/.test(t)) return parseFloat(t);
    const p = t.split(':').map(Number); if (p.some((v) => !isFinite(v) || v < 0)) return NaN;
    return p.reduce((a, v) => a * 60 + v, 0);
  }
  const moveTime = (k) => (k < job.moves ? job.t0[k] : job.total);
  const layerOffset = () => (job.layers[0] && job.layers[0].start ? 1 : 0);
  function exportEvents() {
    const list = [{ t: 0, label: 'Start of print' }];
    for (const ev of job.events) list.push({ t: moveTime(ev.move), label: ev.label });
    list.push({ t: job.total, label: 'End of print' });
    return list;
  }
  function fillEventSelects() {
    const ev = exportEvents();
    const html = ev.map((e, i) => '<option value="' + i + '">' + fmtTime(e.t) + ' · ' + e.label.replace(/</g, '&lt;') + '</option>').join('');
    xs('xEv0').innerHTML = html; xs('xEv1').innerHTML = html;
    xs('xEv0').value = '0'; xs('xEv1').value = String(ev.length - 1);
    X.events = ev;
  }
  // the time range [t0, t1] the dialog describes, or null with a reason
  function exportRange() {
    const mode = xs('xRange').value, so = layerOffset();
    let t0 = 0, t1 = job.total;
    if (mode === 'layer') {
      const L = job.layers[job.layer[Math.min(curMove, job.moves - 1)]]; t0 = L.t0; t1 = L.t1;
    } else if (mode === 'layers') {
      const n = job.layers.length - so;
      let a = Math.round(+xs('xL0').value), b = Math.round(+xs('xL1').value);
      if (!(a >= 1 && a <= n) || !(b >= 1 && b <= n)) return { err: 'Layers go from 1 to ' + n + '.' };
      if (b < a) [a, b] = [b, a];
      t0 = job.layers[a - 1 + so].t0; t1 = job.layers[b - 1 + so].t1;
    } else if (mode === 'events') {
      const ev = X.events || exportEvents();
      let a = ev[+xs('xEv0').value], b = ev[+xs('xEv1').value];
      if (!a || !b) return { err: 'Pick two events.' };
      t0 = Math.min(a.t, b.t); t1 = Math.max(a.t, b.t);
    } else if (mode === 'time') {
      const a = parseClock(xs('xT0').value), b = parseClock(xs('xT1').value);
      xs('xT0').classList.toggle('bad', !(a >= 0)); xs('xT1').classList.toggle('bad', !(b >= 0));
      if (!(a >= 0) || !(b >= 0)) return { err: 'Times look like 1:23 or 1:02:03.' };
      t0 = Math.min(a, b); t1 = Math.min(job.total, Math.max(a, b));
    }
    t0 = Math.max(0, Math.min(job.total, t0)); t1 = Math.max(0, Math.min(job.total, t1));
    if (t1 - t0 < 0.05) return { err: 'That range is empty.' };
    return { t0, t1 };
  }
  function viewSize() { const r = canvas.getBoundingClientRect(); return { w: Math.max(2, Math.round(r.width)), h: Math.max(2, Math.round(r.height)) }; }
  function exportSize(sel, fmt) {
    const v = viewSize(), aspect = v.w / v.h;
    let h = sel === 'window' ? Math.round(v.h * Math.min(2, window.devicePixelRatio || 1)) : +sel;
    if (fmt === 'gif' && sel === 'window') h = Math.min(h, 480);
    let w = Math.round(h * aspect);
    w -= w % 2; h -= h % 2;                       // encoders want even sizes
    return { w: Math.max(2, w), h: Math.max(2, h) };
  }
  function exportPlan() {
    const r = exportRange(); if (r.err) return r;
    const fmt = xs('xFmt').value, fps = +xs('xFps').value, sp = xs('xSpeed').value;
    const span = r.t1 - r.t0;
    const speed = sp.startsWith('fit') ? Math.max(span / +sp.slice(3), 1e-3) : +sp;
    const length = span / speed, frames = Math.max(1, Math.round(length * fps));
    const size = exportSize(xs('xSize').value, fmt);
    return Object.assign(r, { fmt, fps, speed, length, frames, size });
  }
  function updateExportSummary() {
    if (!job) return;
    const sum = xs('xSum');
    if (X.tab === 'image') {
      const what = document.querySelector('input[name=xWhat]:checked').value;
      const sc = xs('xImgSize').value, v = viewSize();
      const s = what === 'window' ? null : sc === '2160' ? { w: Math.round(2160 * v.w / v.h), h: 2160 } : { w: v.w * +sc * Math.min(2, window.devicePixelRatio || 1), h: v.h * +sc * Math.min(2, window.devicePixelRatio || 1) };
      sum.innerHTML = 'The picture on screen now, at <b>' + fmtTime(simT) + '</b> (layer ' + (job.layer[Math.min(curMove, job.moves - 1)] - layerOffset() + 1) + ')' +
        (s ? ' \u00b7 <b>' + Math.round(s.w) + '\u00d7' + Math.round(s.h) + '</b>' : ' \u00b7 the whole window, as you see it') +
        '<br>File size: <b id="xEst">estimating\u2026</b>';
      xs('xImgSize').disabled = what === 'window';
      xs('xGo').disabled = false; scheduleEstimate(null); return;
    }
    const p = exportPlan();
    if (p.err) { sum.innerHTML = '<span class="warn">' + p.err + '</span>'; xs('xGo').disabled = true; return; }
    const warn = [];
    if (p.fmt === 'gif' && p.frames > 900) warn.push('A GIF this long is very large; MP4 is much smaller.');
    if (p.frames > 36000) warn.push('That is a lot of frames; consider a higher speed.');
    if (p.fmt !== 'gif' && !X.codecs[p.fmt]) warn.push(p.fmt.toUpperCase() + ' video is not supported here.');
    const cd = p.fmt === 'gif' ? null : X.codecs[p.fmt];
    const notes = [];
    if (cd && p.fmt === 'mp4' && cd.kind !== 'avc') notes.push('H.264 isn\u2019t available here: the MP4 uses ' + (cd.kind ? cd.kind.toUpperCase() : 'the system\u2019s codec') + ' instead.');
    if (cd && cd.via === 'rec') notes.push('Recorded in real time: this takes at least ' + fmtLong(p.length) + '.');
    sum.innerHTML = '<b>' + fmtTime(p.t0) + ' \u2192 ' + fmtTime(p.t1) + '</b> of the print at ' + (p.speed >= 10 ? Math.round(p.speed) : +p.speed.toFixed(2)) + '\u00d7 \u2192 a <b>' +
      fmtLong(p.length) + '</b> video \u00b7 ' + p.frames + ' frames \u00b7 ' + p.size.w + '\u00d7' + p.size.h +
      '<br>File size: <b id="xEst">' + (p.fmt === 'gif' ? 'estimating\u2026' : 'up to about ' + fmtBytes(videoBitrate(p) * p.length / 8)) + '</b>' +
      (notes.length ? '<br>' + notes.join(' ') : '') +
      (warn.length ? '<br><span class="warn">' + warn.join(' ') + '</span>' : '');
    xs('xGo').disabled = p.fmt !== 'gif' && !X.codecs[p.fmt];
    if (p.fmt === 'gif') scheduleEstimate(p);
  }
  // which encoders this browser has (checked once, at a common size)
  /* What can encode video here. OrcaSlicer puts its page in WebView2 with NavigateToString, which is
     not a secure context, so WebCodecs isn't there: then the canvas is recorded with MediaRecorder,
     one frame at a time (see recordVideo). In a browser from file:// or https, WebCodecs is used. */
  async function probeCodecs() {
    if (X.codecs) return X.codecs;
    const c = { mp4: null, webm: null };
    if (typeof VideoEncoder === 'function') {
      const ok = async (codec) => { try { return (await VideoEncoder.isConfigSupported({ codec, width: 1280, height: 720, bitrate: 4e6, framerate: 30 })).supported; } catch (e) { return false; } };
      if (await ok('avc1.640028') || await ok('avc1.42001f')) c.mp4 = { via: 'wc', kind: 'avc' }; else if (await ok('vp09.00.10.08')) c.mp4 = { via: 'wc', kind: 'vp9' };
      if (await ok('vp09.00.10.08')) c.webm = { via: 'wc', kind: 'vp9' }; else if (await ok('vp8')) c.webm = { via: 'wc', kind: 'vp8' };
    }
    if (typeof MediaRecorder === 'function' && typeof canvas.captureStream === 'function') {
      const ok = (t) => { try { return MediaRecorder.isTypeSupported(t); } catch (e) { return false; } };
      if (!c.mp4) {
        const t = ['video/mp4;codecs=avc1.640028', 'video/mp4;codecs=avc1', 'video/mp4;codecs=avc3', 'video/mp4'].find(ok);
        if (t) c.mp4 = { via: 'rec', mime: t, kind: /avc/.test(t) ? 'avc' : '' };
      }
      if (!c.webm) {
        const t = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(ok);
        if (t) c.webm = { via: 'rec', mime: t, kind: /vp8/.test(t) ? 'vp8' : 'vp9' };
      }
    }
    X.codecs = c;
    for (const o of xs('xFmt').options) if (o.value !== 'gif') o.disabled = !c[o.value];
    if (xs('xFmt').selectedOptions[0].disabled) xs('xFmt').value = c.mp4 ? 'mp4' : c.webm ? 'webm' : 'gif';
    return c;
  }
  function fmtBytes(n) {
    if (!(n > 0)) return '\u2013';
    return n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e8 ? 0 : 1) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' kB';
  }
  const videoBitrate = (p) => Math.max(2e6, Math.min(60e6, p.size.w * p.size.h * p.fps * 0.12));
  /* GIF and picture sizes depend on the content, so encode one real frame to measure */
  let estTimer = 0, estSeq = 0;
  function scheduleEstimate(p) {
    clearTimeout(estTimer);
    const seq = ++estSeq;
    estTimer = setTimeout(async () => {
      if (X.running || !X.open) return;
      let n = 0;
      try {
        if (p) {                                   // GIF: one frame (at most 480 px tall, scaled up) x the frame count
          const { w, h } = p.size, sc = Math.min(1, 480 / h), sw = Math.max(2, Math.round(w * sc)), sh = Math.max(2, Math.round(h * sc));
          const c2 = document.createElement('canvas'); c2.width = sw; c2.height = sh;
          const g2 = c2.getContext('2d', { willReadFrequently: true });
          renderAt(simT); g2.drawImage(canvas, 0, 0, sw, sh);
          const data = g2.getImageData(0, 0, sw, sh).data, { GIFEncoder, quantize, applyPalette } = window.gifenc;
          const enc = GIFEncoder(), pal = quantize(data, 256, { format: 'rgb565' });
          enc.writeFrame(applyPalette(data, pal, 'rgb565'), sw, sh, { palette: pal }); enc.finish();
          n = enc.bytes().length / (sc * sc) * p.frames;
        } else {
          const what = document.querySelector('input[name=xWhat]:checked').value;
          n = (await captureImage(what, xs('xImgFmt').value, xs('xImgSize').value)).size;
        }
      } catch (e) { n = 0; }
      if (seq !== estSeq || !xs('xEst')) return;
      xs('xEst').textContent = n ? (p ? 'about ' : '') + fmtBytes(n) : '\u2013';
    }, 250);
  }
  function setExportTab(tab) {
    X.tab = tab;
    xs('xTabVideo').classList.toggle('on', tab === 'video'); xs('xTabImage').classList.toggle('on', tab === 'image');
    xs('xTabVideo').setAttribute('aria-selected', tab === 'video'); xs('xTabImage').setAttribute('aria-selected', tab === 'image');
    xs('xVideo').hidden = tab !== 'video'; xs('xImage').hidden = tab !== 'image';
    updateExportSummary();
  }
  function showRangeRows() {
    const m = xs('xRange').value;
    xs('xLayersRow').hidden = m !== 'layers'; xs('xEventsRow').hidden = m !== 'events'; xs('xTimeRow').hidden = m !== 'time';
    updateExportSummary();
  }
  async function openExport() {
    if (!job || X.running) return;
    setPlaying(false);
    X.open = true; xs('expDlg').hidden = false; xs('xProg').hidden = true; showExportResult(null);
    const so = layerOffset(), n = job.layers.length - so, cur = job.layer[Math.min(curMove, job.moves - 1)] - so + 1;
    xs('xL0').max = xs('xL1').max = n;
    if (!xs('xL0').value) { xs('xL0').value = 1; xs('xL1').value = n; }
    if (!xs('xT0').value) { xs('xT0').value = fmtTime(simT); xs('xT1').value = fmtTime(Math.min(job.total, simT + 60)); }
    if (+xs('xL0').value > n) xs('xL0').value = 1;
    if (+xs('xL1').value > n) xs('xL1').value = n;
    fillEventSelects();
    if (!X.inited) {
      X.inited = true;
      xs('xFps').value = '30'; xs('xSize').value = '1080'; xs('xSpeed').value = 'fit30';
    }
    void cur;
    await probeCodecs();
    setExportTab(X.tab); showRangeRows();
    (X.tab === 'video' ? xs('xRange') : xs('xImgFmt')).focus();
  }
  function closeExport() {
    if (X.running) { X.cancel = true; return; }
    X.open = false; xs('expDlg').hidden = true; canvas.focus({ preventScroll: true });
  }
  xs('expBtn').onclick = openExport;
  xs('xClose').onclick = closeExport; xs('xCancel').onclick = closeExport;
  xs('expDlg').addEventListener('pointerdown', (e) => { if (e.target === xs('expDlg') && !X.running) closeExport(); });
  xs('expDlg').addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeExport(); } e.stopPropagation(); });
  xs('xTabVideo').onclick = () => setExportTab('video'); xs('xTabImage').onclick = () => setExportTab('image');
  xs('xRange').onchange = showRangeRows;
  for (const id of ['xL0', 'xL1', 'xEv0', 'xEv1', 'xT0', 'xT1', 'xFmt', 'xSpeed', 'xSize', 'xFps', 'xImgFmt', 'xImgSize'])
    xs(id).addEventListener(id.startsWith('xT') || id.startsWith('xL') ? 'input' : 'change', updateExportSummary);
  for (const r of document.querySelectorAll('input[name=xWhat]')) r.onchange = updateExportSummary;
  xs('xFmt').addEventListener('change', () => {
    // GIFs: modest size and frame rate by default
    if (xs('xFmt').value === 'gif') { if (+xs('xFps').value > 24) xs('xFps').value = '15'; if (['1080', '1440', '2160'].includes(xs('xSize').value)) xs('xSize').value = '480'; }
    updateExportSummary();
  });
  xs('xNow').onclick = () => { xs('xT0').value = fmtTime(simT); updateExportSummary(); };

  /* --- rendering at a given size; everything is put back afterwards */
  function withRenderSize(w, h, fn) {
    const pr = renderer.getPixelRatio();
    renderer.setPixelRatio(1); renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    if (lineMat) { lineMat.resolution.set(w, h); lineMatPartial.resolution.set(w, h); }
    try { return fn(); } finally { renderer.setPixelRatio(pr); resize(); }
  }
  async function withRenderSizeAsync(w, h, fn) {
    const pr = renderer.getPixelRatio();
    const apply = () => {
      renderer.setPixelRatio(1); renderer.setSize(w, h, false);
      camera.aspect = w / h; camera.updateProjectionMatrix();
      if (lineMat) { lineMat.resolution.set(w, h); lineMatPartial.resolution.set(w, h); }
    };
    apply(); X.applySize = apply;
    try { return await fn(); } finally { X.applySize = null; renderer.setPixelRatio(pr); resize(); }
  }
  function renderAt(t) {
    simT = Math.max(0, Math.min(job.total, t));
    updateScene(true); controls.update();
    renderer.render(scene, camera); dirty = false;
  }
  function progress(frac, text) {
    xs('xBar').style.width = Math.round(Math.max(0, Math.min(1, frac)) * 100) + '%';
    if (text != null) xs('xProgText').textContent = text;
  }
  const sleep0 = () => new Promise((r) => setTimeout(r, 0));

  async function encodeVideo(p) {
    const { w, h } = p.size, fps = p.fps, dtSim = p.speed / fps;
    const frameUs = 1e6 / fps;
    const bitrate = videoBitrate(p);
    if (p.fmt === 'gif') {
      const { GIFEncoder, quantize, applyPalette } = window.gifenc;
      const gif = GIFEncoder(), c2 = document.createElement('canvas'); c2.width = w; c2.height = h;
      const g2 = c2.getContext('2d', { willReadFrequently: true });
      const delay = Math.round(100 / fps) * 10;
      await withRenderSizeAsync(w, h, async () => {
        for (let i = 0; i < p.frames; i++) {
          if (X.cancel) throw new Error('cancelled');
          if (X.applySize) X.applySize();
          renderAt(p.t0 + i * dtSim);
          g2.drawImage(canvas, 0, 0, w, h);
          const data = g2.getImageData(0, 0, w, h).data;
          const palette = quantize(data, 256, { format: 'rgb565' });
          gif.writeFrame(applyPalette(data, palette, 'rgb565'), w, h, { palette, delay });
          if (i % 2 === 0) { progress((i + 1) / p.frames, 'Frame ' + (i + 1) + ' of ' + p.frames); await sleep0(); }
        }
      });
      gif.finish();
      return new Blob([gif.bytes()], { type: 'image/gif' });
    }
    const cd = X.codecs[p.fmt];
    if (!cd) throw new Error(p.fmt.toUpperCase() + ' video is not supported here.');
    if (cd.via === 'rec') return recordVideo(p, cd, bitrate);
    const kind = cd.kind;
    let codec, muxer, target;
    if (kind === 'avc') {
      const big = w * h > 1920 * 1088;
      const cands = big ? ['avc1.640033', 'avc1.640034', 'avc1.4d0033'] : ['avc1.640028', 'avc1.4d0028', 'avc1.42001f', 'avc1.640033'];
      for (const c of cands) {
        try { if ((await VideoEncoder.isConfigSupported({ codec: c, width: w, height: h, bitrate, framerate: fps, avc: { format: 'avc' } })).supported) { codec = c; break; } } catch (e) { /* next */ }
      }
    } else {
      for (const c of kind === 'vp8' ? ['vp8'] : ['vp09.00.40.08', 'vp09.00.31.08', 'vp09.00.10.08']) {
        try { if ((await VideoEncoder.isConfigSupported({ codec: c, width: w, height: h, bitrate, framerate: fps })).supported) { codec = c; break; } } catch (e) { /* next */ }
      }
    }
    if (!codec) throw new Error(w + '×' + h + ' is too large for this video encoder; pick a smaller size.');
    if (p.fmt === 'mp4') {
      target = new Mp4Muxer.ArrayBufferTarget();
      muxer = new Mp4Muxer.Muxer({ target, video: { codec: kind === 'avc' ? 'avc' : 'vp9', width: w, height: h, frameRate: fps }, fastStart: 'in-memory' });
    } else {
      target = new WebMMuxer.ArrayBufferTarget();
      muxer = new WebMMuxer.Muxer({ target, video: { codec: kind === 'vp8' ? 'V_VP8' : 'V_VP9', width: w, height: h, frameRate: fps } });
    }
    let encErr = null;
    const enc = new VideoEncoder({ output: (chunk, meta) => muxer.addVideoChunk(chunk, meta), error: (e) => { encErr = e; } });
    enc.configure(Object.assign({ codec, width: w, height: h, bitrate, framerate: fps, latencyMode: 'quality' }, kind === 'avc' ? { avc: { format: 'avc' } } : {}));
    try {
      await withRenderSizeAsync(w, h, async () => {
        for (let i = 0; i < p.frames; i++) {
          if (X.cancel) throw new Error('cancelled');
          if (encErr) throw encErr;
          if (X.applySize) X.applySize();
          renderAt(p.t0 + i * dtSim);
          const vf = new VideoFrame(canvas, { timestamp: Math.round(i * frameUs), duration: Math.round(frameUs) });
          enc.encode(vf, { keyFrame: i % (fps * 2) === 0 }); vf.close();
          while (enc.encodeQueueSize > 6) await new Promise((r) => setTimeout(r, 2));
          if (i % 3 === 0) { progress((i + 1) / p.frames, 'Frame ' + (i + 1) + ' of ' + p.frames); await sleep0(); }
        }
      });
      progress(1, 'Finishing…');
      await enc.flush();
      if (encErr) throw encErr;
      muxer.finalize();
    } finally { if (enc.state !== 'closed') enc.close(); }
    return new Blob([target.buffer], { type: p.fmt === 'mp4' ? 'video/mp4' : 'video/webm' });
  }

  /* MediaRecorder can't take frames with timestamps, so it is paced: each frame is rendered and copied
     onto a plain 2D canvas while the recorder is paused, then the recorder runs for exactly one
     frame's time on that still picture and pauses again. Paused time doesn't count, so the video's
     timing is right however long a frame takes to render. */
  async function recordVideo(p, cd, bitrate) {
    const { w, h } = p.size, fps = p.fps, dtSim = p.speed / fps, frameMs = 1000 / fps;
    const waitMs = (ms) => new Promise((r) => setTimeout(r, ms));
    let rec = null, track = null, recErr = null;
    const parts = [];
    try {
      await withRenderSizeAsync(w, h, async () => {
        const still = document.createElement('canvas'); still.width = w; still.height = h;
        const sg = still.getContext('2d');
        renderAt(p.t0); sg.drawImage(canvas, 0, 0, w, h);
        const stream = still.captureStream(0); track = stream.getVideoTracks()[0];
        rec = new MediaRecorder(stream, { mimeType: cd.mime, videoBitsPerSecond: Math.round(bitrate) });
        rec.ondataavailable = (e) => { if (e.data && e.data.size) parts.push(e.data); };
        rec.onerror = (e) => { recErr = e.error || new Error('The recorder failed.'); };
        rec.start(1000); rec.pause();
        const t0 = performance.now();
        for (let i = 0; i < p.frames; i++) {
          if (X.cancel) throw new Error('cancelled');
          if (recErr) throw recErr;
          if (X.applySize) X.applySize();
          renderAt(p.t0 + i * dtSim); sg.drawImage(canvas, 0, 0, w, h);
          rec.resume();
          track.requestFrame();
          await waitMs(frameMs);
          rec.pause();
          if (i % 2 === 0) {
            const left = (performance.now() - t0) / (i + 1) * (p.frames - i - 1) / 1000;
            progress((i + 1) / p.frames, 'Frame ' + (i + 1) + ' of ' + p.frames + ' \u00b7 about ' + fmtLong(left) + ' left');
          }
        }
        progress(1, 'Finishing\u2026');
        await new Promise((r) => { rec.onstop = r; rec.stop(); });
      });
    } finally {
      if (rec && rec.state !== 'inactive') { try { rec.stop(); } catch (e) { /* stopping anyway */ } }
      if (track) track.stop();
    }
    if (recErr) throw recErr;
    return new Blob(parts, { type: cd.mime.split(';')[0] });
  }
  function canvasToBlob(c, type, q) { return new Promise((res, rej) => c.toBlob((b) => (b ? res(b) : rej(new Error('Could not encode the image.'))), type, q)); }
  async function captureImage(what, fmt, scale) {
    const type = 'image/' + fmt, q = fmt === 'png' ? undefined : 0.92;
    const v = viewSize(), dpr = Math.min(2, window.devicePixelRatio || 1);
    if (what === 'render') {
      const h = scale === '2160' ? 2160 : Math.round(v.h * +scale * dpr), w = Math.round(h * v.w / v.h);
      const c2 = document.createElement('canvas'); c2.width = w; c2.height = h;
      withRenderSize(w, h, () => { renderAt(simT); c2.getContext('2d').drawImage(canvas, 0, 0); });
      renderAt(simT);
      return canvasToBlob(c2, type, q);
    }
    // whole window: the page drawn by the browser inside an SVG, canvases pasted in as pictures
    renderAt(simT);
    const shots = new Map();
    for (const c of document.querySelectorAll('canvas')) { try { shots.set(c, c.toDataURL('image/png')); } catch (e) { /* skip */ } }
    const W = document.documentElement.clientWidth, H = document.documentElement.clientHeight;
    const clone = document.documentElement.cloneNode(true);
    const origAll = document.documentElement.querySelectorAll('*'), cloneAll = clone.querySelectorAll('*');
    for (let i = 0; i < origAll.length; i++) {
      const o = origAll[i], c = cloneAll[i];
      if (o.tagName === 'SCRIPT') { c.remove(); continue; }
      if (o.id === 'expDlg' || o.id === 'toast') { c.remove(); continue; }
      if (o.tagName === 'CANVAS' && shots.has(o)) {
        const img = document.createElement('img'); img.src = shots.get(o);
        img.setAttribute('style', (o.getAttribute('style') || '') + ';width:' + o.clientWidth + 'px;height:' + o.clientHeight + 'px;display:block');
        if (o.id) img.id = o.id;
        img.className = o.className; c.replaceWith(img); continue;
      }
      if (o.tagName === 'SELECT') { for (const opt of c.querySelectorAll('option')) opt.toggleAttribute('selected', opt.value === o.value); }
      else if (o.tagName === 'INPUT') { if (o.type === 'checkbox' || o.type === 'radio') c.toggleAttribute('checked', o.checked); else c.setAttribute('value', o.value); }
      if (o.scrollTop) c.setAttribute('data-scroll', o.scrollTop);
    }
    // inline the CSS variables and colours the host set on <html> (theme), and pin the page size
    clone.setAttribute('style', (document.documentElement.getAttribute('style') || '') + ';width:' + W + 'px;height:' + H + 'px');
    const xml = new XMLSerializer().serializeToString(clone);
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W * dpr + '" height="' + H * dpr + '" viewBox="0 0 ' + W + ' ' + H + '">' +
                '<foreignObject x="0" y="0" width="' + W + '" height="' + H + '">' + xml + '</foreignObject></svg>';
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error('Could not draw the window.')); img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); });
    const c2 = document.createElement('canvas'); c2.width = Math.round(W * dpr); c2.height = Math.round(H * dpr);
    const g = c2.getContext('2d'); g.fillStyle = getComputedStyle(document.body).backgroundColor || '#1e2023'; g.fillRect(0, 0, c2.width, c2.height);
    g.drawImage(img, 0, 0, c2.width, c2.height);
    return canvasToBlob(c2, type, q);
  }

  /* --- saving: the system's Save dialog when there is one (Windows/Chromium), else the plugin
     writes it into its own exports folder (OrcaSlicer on macOS/Linux), else a browser download */
  const MIME = { mp4: 'video/mp4', webm: 'video/webm', gif: 'image/gif', png: 'image/png', jpeg: 'image/jpeg', webp: 'image/webp' };
  function exportName(ext) {
    const base = String((currentMeta && currentMeta.name) || 'print').replace(/\.gcode(\.3mf)?$/i, '').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 80) || 'print';
    return base + (X.tab === 'image' ? '_' + fmtTime(simT).replace(/:/g, '-') : '') + '.' + (ext === 'jpeg' ? 'jpg' : ext);
  }
  async function pickSaveTarget(name, ext) {
    if (typeof window.showSaveFilePicker !== 'function') return null;
    const accept = {}; accept[MIME[ext]] = ['.' + (ext === 'jpeg' ? 'jpg' : ext)];
    try { return await window.showSaveFilePicker({ suggestedName: name, types: [{ description: ext.toUpperCase(), accept }] }); }
    catch (e) { if (e && e.name === 'AbortError') return 'cancelled'; return null; }
  }
  const pendingSaves = new Map();
  function saveViaPlugin(name, blob) {
    return new Promise(async (resolve, reject) => {
      const id = 'x' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      pendingSaves.set(id, { resolve, reject });
      const buf = new Uint8Array(await blob.arrayBuffer()), CH = 384 * 1024, n = Math.max(1, Math.ceil(buf.length / CH));
      send({ cmd: 'save_begin', id, name, size: buf.length, chunks: n });
      for (let i = 0; i < n; i++) {
        let bin = ''; const part = buf.subarray(i * CH, (i + 1) * CH);
        for (let j = 0; j < part.length; j += 0x8000) bin += String.fromCharCode.apply(null, part.subarray(j, j + 0x8000));
        send({ cmd: 'save_chunk', id, i, data: btoa(bin) });
        if (i % 4 === 3) { progress((i + 1) / n, 'Saving…'); await sleep0(); }
      }
      send({ cmd: 'save_end', id });
      setTimeout(() => { if (pendingSaves.has(id)) { pendingSaves.delete(id); reject(new Error('The plugin did not answer.')); } }, 30000);
    });
  }
  function onSaved(msg) {
    const p = pendingSaves.get(msg.id); if (!p) return;
    pendingSaves.delete(msg.id);
    if (msg.ok) p.resolve(msg.path); else p.reject(new Error(msg.error || 'Could not save the file.'));
  }
  async function deliver(blob, name, handle) {
    if (handle && handle !== 'cancelled') {
      const w = await handle.createWritable(); await w.write(blob); await w.close();
      return 'Saved ' + handle.name;
    }
    if (host) { const path = await saveViaPlugin(name, blob); X.savedPath = path; return 'Saved to ' + path; }
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    return 'Downloaded ' + name;
  }

  async function runExport() {
    if (!job || X.running) return;
    const isImg = X.tab === 'image';
    const plan = isImg ? null : exportPlan();
    if (plan && plan.err) return;
    const ext = isImg ? xs('xImgFmt').value : plan.fmt;
    const name = exportName(ext);
    // ask where to save first: the Save dialog has to open straight from the click
    const handle = await pickSaveTarget(name, ext);
    if (handle === 'cancelled') return;
    X.running = true; X.cancel = false; X.savedPath = null; showExportResult(null);
    const keep = { t: simT };
    xs('xProg').hidden = false; progress(0, isImg ? 'Capturing…' : 'Rendering…');
    xs('xGo').disabled = true; xs('xCancel').textContent = 'Stop';
    for (const el of xs('expDlg').querySelectorAll('select,input,.tabs button')) el.disabled = true;
    let msg = null, isErr = false;
    try {
      const blob = isImg
        ? await captureImage(document.querySelector('input[name=xWhat]:checked').value, ext, xs('xImgSize').value)
        : await encodeVideo(plan);
      progress(1, 'Saving…');
      msg = await deliver(blob, name, handle) + ' (' + (blob.size >= 1e6 ? (blob.size / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(blob.size / 1e3)) + ' kB') + ')';
    } catch (e) {
      if (e && e.message === 'cancelled') msg = 'Export stopped.';
      else { msg = 'Export failed: ' + (e && e.message ? e.message : e); isErr = true; console.error(e); }
    } finally {
      X.running = false; X.cancel = false;
      simT = keep.t; updateScene(true); updateHud(); dirty = true;
      for (const el of xs('expDlg').querySelectorAll('select,input,.tabs button')) el.disabled = false;
      xs('xCancel').textContent = 'Cancel'; xs('xProg').hidden = true;
      updateExportSummary();
    }
    X.last = { msg, isErr };
    if (!isErr && msg !== 'Export stopped.' && !X.savedPath) { toast(msg); closeExport(); }
    else showExportResult(msg, isErr, X.savedPath);
  }
  xs('xGo').onclick = runExport;
  function showExportResult(msg, isErr, path) {
    const r = xs('xResult');
    if (!msg) { r.hidden = true; return; }
    r.hidden = false; r.className = 'result' + (isErr ? ' err' : '');
    xs('xResultText').textContent = path ? 'Saved into the plugin\u2019s exports folder (OrcaSlicer can\u2019t show a Save dialog here):' : msg;
    xs('xResultPath').hidden = !path; xs('xCopy').hidden = !path;
    if (path) xs('xResultPath').textContent = path;
  }
  xs('xCopy').onclick = async () => {
    const t = xs('xResultPath').textContent;
    let ok = false;
    try { await navigator.clipboard.writeText(t); ok = true; } catch (e) {
      const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select();
      try { ok = document.execCommand('copy'); } catch (e2) { ok = false; } ta.remove();
    }
    xs('xCopy').textContent = ok ? 'Copied' : 'Select and copy';
    if (!ok) { const rg = document.createRange(); rg.selectNodeContents(xs('xResultPath')); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(rg); }
    setTimeout(() => { xs('xCopy').textContent = 'Copy path'; }, 1600);
  };

  window.PlaybackApp = { loadText, seek, setPlaying, get job() { return job; }, get time() { return simT; },
                         setPrefs(p) { Object.assign(prefs, p); syncOptionUI(); if (job) { if ("lines" in p) buildPaths(); else rebuildObjects(); computeColors(); if (R.main.userData.thin) R.main.geometry.attributes.color.needsUpdate = true; else R.main.geometry.setColors(R.col); updateScene(true); updateHud(); } },
                         frame, onHostMessage,
                         // tests: camera state and the screen position of a bed point
                         _pick(x, y) { const r = canvas.getBoundingClientRect(); const rc = new THREE.Raycaster();
                                       camera.updateMatrixWorld(); rc.setFromCamera(new THREE.Vector2((x - r.left) / r.width * 2 - 1, -(y - r.top) / r.height * 2 + 1), camera);
                                       const h = controls.pick(rc.ray); return h ? h.sub(bedGroup.position).toArray() : null; },
                         _export: X, _runExport: runExport, _openExport: openExport,
                         _exportPlan() { return exportPlan(); },
                         _capture(what, fmt, scale) { return captureImage(what, fmt, scale); },
                         _cam() { const d = controls.target.clone().sub(camera.position); return { pos: camera.position.toArray(), posBed: camera.position.clone().sub(bedGroup.position).toArray(), dist: d.length(), dir: d.normalize().toArray(), up: new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1).toArray(), pivot: controls._pivot().sub(bedGroup.position).toArray() }; },
                         _project(pt) { camera.updateMatrixWorld(); const v = new THREE.Vector3(pt[0], pt[1], pt[2]).add(bedGroup.position).project(camera); const r = canvas.getBoundingClientRect();
                                        return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height]; },
                         // tests: put the camera at (px,py,pz) looking at (tx,ty,tz), in bed millimetres
                         look(tx, ty, tz, px, py, pz) { controls.target.set(tx, ty, tz); camera.position.set(px, py, pz); camera.updateProjectionMatrix(); controls.sync(); controls.update(); dirty = true; } };
})();
</script>
</body></html>
'''

VENDOR_B64 = """
eNrcvWlj2ziSAPp9f4XjN5sVKUoWddmWw/ilk3R3ZnJNjp7uZDxeSoIkdihSTVK25UTvt7+qwk1StpPumZ3dHCJQAApAoVAoXIUD
d69YZIy1f833Mr9/uNd48ezd3vNowpKceXuP09Umi+aLYq/b8Tutbqfb3Xsn4z9aF4s0y5099+A/Dlz3P/bcvf835inRfZe0GO/t
6yc/t0SOrWdTlhTRLGLZaA9K8h+I+95snUyKKE0ahcecz/vp+Fc2KfaDoNisWDrbY1erNCvy+/f318mUzaKETffvycBlOl3H7JQ1
RCxntC/RaQw81f37/NsOl9NT7mx83Bfp9s8g7xFrNIqgLpt5nI7D+N0iyk+1c1R8+ZKzeOa03/345unT4PPW2TYKCPAaukpQoXXO
9vIii6BSJ5M0yYs9FuxDY+x7UeB3Ol4S9OA3g1/fy+G364Xw2/NS+O17MfwOvUngs563wPi+t8ZP15vip+et8NP3lvgZeDP8DL05
fg69C/wceVf4OfbO4eN3vQ1++t4L/Ay8MX6G3lv4dDveJX563jv8DL1H+Dn0nga93uHh0HtM30PvOX2PvDf0PfZeB73BUb/jPaOv
7z2hb9d7Sd+e9yroHfaPu941fYfee/geQbG+o++x9z1+/Y73ib6+9wN9u95P9O15P9K37/2NvgPvV/oOvd/oe+j9TN8j7xf6Hnsf
8AuV+TN9fe8vQW+I+f8p6CKl/4of3ysK/HY9Bt8+gCP6+l5C366XwXcA8Jy+vhcWQQ/aIC2wuXwvBk7Js/l435sIVysGpgmzfW9R
BIfDo463hqiDTr/vTSEGJNpj+b63KoCovcHJJA7zfG9ZfA6n06cX0C2eR3nBEpbxbnCRRtO9TgA8DAzVPo9FIHSDRgmCfCf4KirH
PlFooo/FGaTFT/DxzPFavgC2I2D3q1ezBnPu3yfAap0vwLddhHlNwaJZY1fZnIwV6yy55+8sDo+wxxHck6Vq+fcqZdlmbJlesG8q
wK7sIYcTlRqzdD7zmEUQGVmfUHkKoEY7X6HEg3x9Z7udRvkqLCYLKhP27DuXhFVL0kbJYhcH6gbgMJsDR2J8VQ3WzqkYHedklmaN
mCFGlBtRO2bJvFicsAfJCWs2negjO2tPwjjmcqhwThTGZB3H2+2W45wVwcf9Tmff2+/4+NPFnx7+9PFngD9D/DnEnyP8OcafEH/G
+DPBnyn+MPyZwY+P+HzE5yM+H/H5iM9HfD7i8xGfj/h8xOcjPh/x+YjPR3w+4vMRXxfxdRFfF/F1EV8X8XURXxfxdRFfF/F1EV8X
8XURXxfxdRFfF/F1EV8P8fUQXw/x9RBfD/H1EF8P8fUQXw/x9RBfD/H1EF8P8fUQXw/x9RBfH/H1EV8f8fURXx/x9RFfH/GhkN/v
I74+4usjvj7i6yO+PuLrI74+4hsgvgHiGyC+AeIbIL4B4hsgvgHiGyC+AeIbIL4B4hsgvgHiGyC+AeIbIr4h4hsiviHiGyK+IeIb
Ir4h4hsiviHiGyK+IeIbIr4h4hsiviHiO0R8h4jvEPEdIr5DxHeI+A4R3yHiO0R8h4jvEPEdIr5DxHeI+A4R3yHiO0J8R4jvCPEd
Ib4jxHeE+I4Q3xHiO0J8R4jvCPEdIb4jxHeE+I4Q3xHiO0Z8x4jvGPEdI75jxHeM+I4R3zHiO0Z8x4jvGPEdI75jxHeM+I4R3zHi
CxFfiPhCxBcivhDxhYgvRHwh4gsRX4j4QsQXIr4Q8YWIL0R8IeIbI74x4hsjvjHiGyO+MeIbI74x4hsjvjHiGyO+MeIbI74x4hsj
vjHimyC+CeKbIL4J4psgvgnimyC+CeKbIL4J4psgvgnimyC+CeKbIL4J4psivinimyK+KeKbIr4p4psivinimyK+KeKbIr4p4psi
vinimyK+KeJjiI8hPob4GOJjiI8hPob4GOJjiI8hPob4GOJjiI8hPob4GOKbIb4Z4pshvhnimyG+GeKbIb4Z4pshvhnimyG+GeKb
Ib4Z4pshvtls/+wE5egcRuNurz8YHgppe1EEL8Ji0X797MCHIfwKwo86BwJ0IvW6vfOioQePfvcY1JrD7vHApYhZmEzTZcP50vHY
TYHRTYHJDYFiHG3Mio/dweB+cdYEV/Hw4dF98EqPPzR93T737bf2myIZozCmkokgRkn9wZdhX0YoJR727kdf/O4RBUfl9JGVdaRT
i2wTciVmaRMrSaKSOO0ifZ5esuxxmLOGs1Xk3xSoC3gwgAuNggi0DK8azOPOKGlEMP4ZaV4UXH8QtCv+kzWZ859MRxiXkDb8VuS4
RTNyjUhvaeQXucLA3yjuFy0fVCccwQsd79KMR0VapZeNLi/dhEVxg1xxOod4nL+ev+ya5X13E4ZZnIImcBuKR6LK+WUEekuDtYlj
s/WkSDNgXyDq3vdxGha97qMsCzcjkVlxQkHvo6Twh3bIwXAwQOVVhh+VgqHVeOCzSlrVRMVBr3s4PAQV1FFxj3ZF9bs8IkzJwnVc
jGA6m17uJexy72mWAQn2nyUXYQwa1CRdrtIENLM91Kza+6CwKTo8/aPpwPtjCjPFBhHELZxdNDGiAnFUxGc34ST6mFF3ogTyYLxv
oc5FmO09LoJXNN1uz2Dmfs0an8/PV1lapOfnI1QYvSdPf+i+efRkdFF48OmCd3RVeHNUYsOCvX//7MnovPBgLrNcjTZA4/UEcmNh
8gLn5enoReEtw9VzmheNzHm+F3mJlyn2TpqNosUct5G1EuegEYF760XJBajK7DnLVqW0Kl2BavMpxIcO0GDwO+psvRgTjAtvioUq
Z6qSit7ut4ia7GrVaEVuAr3HW0XJHIg1t9IGvkrJeJJwnDdIpnRd5lCB82WaFgtQ8XeX9wEUtzMqHgbRqT9qFAFVm1cYRI3b6LW6
0J4SFVT/dyADdPBv6IJ8GjhNvwNocQgBdhrZSy4SX7MsWuSI4yJtm74jMFBfuRGHldBM9XaVsXA6MtdHZEq30R60rNRIB8ambPqG
AFYqNWuCeVoDRnHoBHxeNC+aMGT3/MFwcOT35IyT8VE9Wq7jBvsHDGkP/YHnf2GOx/4RsGY58NAbUmBDRu478NtxDtSYPNx6UzZ/
l77ZVZuLAqs9fZc+YfP6GFcQI8pf4/j2avbuMh29hZ4EI4MBuSw8ag4D9K4AohR/XUP3yxJA+X2WLl9n6YplT9fA+bW9jCsqOafB
JM29kDvzKPHSIG9EB13Hi4OQOyYAabAmdETwLACqPGsKaXHPlEKEZ4UhCbIfeJYYIjwnQuYKObv/8y8/74+KNlShkboLL3bX8H/q
pe7EORkDb3wimbf/y4dfZDQezKOWo334+YOOJjEtKtF+/lDKdAn/V9VMfzYyXXkyaiXTX4xMJSYrUymOke5pzNqXIWgT+7RK2EbC
vy+iOB/ttW9qyIazx5IJCHkIZtO9MNlbJ5+S9DLZS7Mprp/uNzOQ4l6SZksQ8dds9BREHtPeRwWuC9Eq0/PiszHigaRAxbTjfH5e
tEna05gQ5T8xDO4G9zoerVdcBQV3bAK2nUPvuoymxaKhWZgibXMVAtwtE1L8BcMF4lKCDSUQQTLFBlIgQS1ZUi4DOTDa20kYh5nZ
mUpRCxX1512xMPCXcqCZ8rEcMi3doRD6Ashdjo0ZrLHnj2RZS5xQGZhpuWkvyvfSdbGXzvZA5s0ZNmqBS1+qREhGoyA1xbDqJkth
1enbCrGdxJCpbjtMRvgsTqJcBdWd7SRdbWrorWKAc8PpG06nlYhNI2bTirqjvZuqwaULI3MuzmtZCdIwqzTgtbNhIn1Nciqfy8wS
upIn1+NK6VpGdVq6OhB1R3VaqjotxYbr8c3VadnVaanqwFhWRKu42hyuUSxXF0vG31E2V5VNurbT6AJUvUrMAwP/gcbPY9djL+Xt
HwD7hSsAgKzMoqsecbu5kHrlibXdDUyTizaL2RK6h1peFuRJPnbOXBi6PvbO3Ag+wzNJqeSjz0P6POTwTBAhSqrsq+aTktnbV45E
ZIdBVaEXCFQ4e6lHhSG7UMkwExVp13Xtr5MALlUUxRFXTg1ywGzE3Miua2YlG+mmDA0kN2RWiWVn9JwWr3lG1pI9X9VuOFaDWhwU
ffniO2XGqc84cnBKTEptbX14kKiEVQcjRLUFztxr0VBIHRYdIJHwqVstFh5Uh8YIsfC8Sz+wLK1g458HndNK4Ua7a80/1USbaiJZ
hoTNQYGpZN+yRgbhlaIgLaryBUWzEDDAo9tJluZ5XaxNS8W62nI+eftboxKPC2wZlasdkqusNZX8t6xo3JDKgZ6cLMKiCJPndelx
Fiio2LQBkFQpY6UC2sLQ5Hhk6y2MwjEr5wMF6DYkHVtWlq+f4d4URJiwd2l50UhXUMd5+9s6BKWygetjddCStG0VhsQFz0bNqkCI
Rm6kSfRkZzE0nRBbhVaI1UGtS8oEm2AGIduVkWqLE/7a8RoFoySVMXA3NBtJMOEwhlpzmq11B5StVHw3MnUIFKRUAQHeMqBkbLEv
IBB7hFf370NU6dtsZ6D20+oOrTJ0Ktl+ZGrYAnfTF0NVkYpEwcczOx0kkKMkTyCHyoLy+m49m7HsUQEj63hdsHq9Yo6KM9NyAQG/
SADInQL6/CMhkUzpLSeYGDVRc0z0ZSYv5TW8JPLO3KiVu0nTUBoz8OYwTitdQq4P1ApQEWbLThO4dT++3SzHadyOClzFSrMzQLWJ
WDwVmDzDs0FFGOdQb+w5lPP5jT15ErqKmjxJpST46Hsd+qu+Z3Kqw+fnHszHvdSLJRkngYVAEmgC6gzoXhPQXYIEPt2zIIRP7wwm
RhPQZIIMPoOzIIXP8CyI4HN4FuTwOToLYl71iM7fFJsS7bA4lVLKEU/o9JZIkGVDqVApKMOCRvDjMSxrBD/g6qKri64eunro6qOr
j64BugbowqKjqsaw9BGqZgwrEMGP6FxXRRZOiu/CPKp0VawJzqNFYzxO4/WSK2dex/HYDcFQ3eiG4K6j5oU6Rt+iS70aiqRlnBZ9
XhWiClUZfo45aajeGNA5c27W3yWcSjBhudzo364ydvc0lIezrQkwVTHdzEnAtCcr8UDOGzvkrZry5ot5u094Ay94S645C0x5W694
oy5JUfdmASrq3jwgRf2CdHQPlXhIfh6Qjo6KOyR/AR9IPobP0ZkkdoZMl7vLZuheNFN342XIZ7k7A8AVAF4AYIiAOQDOATAGAHBn
DEkmkGRBSfoImAHgCgCY5BABcwCcAwCTABuvIckUkqwoyQABMwBcAQCTHCFgDoBzAIx3za5qu5PZg3CehX2Ff4fi64tvX3wPxbcr
vgPxPTrT8zQGYg5U4TAx9yztJoRyYBtAmyPVYU6FdIZ2xhYBYY1tEMJngM1b8OYtsEVAVBltwNzcnbSYG7pxK3IzdwLKQeimzQTc
cSuB0HRLi/r/rIIAn03cvAX5A6tBzq2JmwG3xW4GY0oKDMfcBZRpDSWa4tEbPLizcsrdteOV/srjVcvAP1ip3o0Mt3CXHpY0aCRQ
w4kbOQQAJmmEMJBBlTmgR1zjYfmDxsRlEJLykAGlzaDMjAOASafkANZrRFCHWIYAYzVySAukJQCpATC05asUd0c/4/p3cXIjYxWB
ED5QZMZlcA8HFYR3hZQWomgo4QMhnxmXxYdnkrFAJ3hJehmXhmWpUxGVbdn2baPUugbPEqXT3NI9iPQkVAtVkUIVnahN1SRyk9wt
VAWIwFRZojBVj0jL1AADBX9/8Q6LNYPq2eO0LFmqVZ0Ml86VqpM5FfEPjehFwJLQcI3UzZuxGzrNvFl4wAWxB5yAjga0cw5iCYLC
JrNG4ByXpap6minwXxcw7/1EMwoe09LUyi1Tk/INRsRdg1Yh01LDxGFxt6zfidhyQ0gtg1SDalWPglQPu+JWwQymUKQvYNDWpC+q
pGdAdEAYCcQ26rf1dOW6GY9eTqYV+zuoQ/KsXhF0TooHxycFHtCbgTZQnInzjvrApHB0qtMBiSUCLBFgiQCLlenHCHrkx6jJzszq
10wQrCWWap9iQmkTk4aI9yDWlIobuqXqhm6pvKFbqm/olgocuqUKh26lxJVWlht1K8tO2yCEWV5HHmF8XQSY8E2hD+U8o3UFfUSy
ENPqln/CHgL5Wi2GDYBVfRjQvr1sAHmi5p4vsD8pgs963125PGN/Xzs59DEuabGpEWhCPGPDXzs982yB4cbY8jCCdlJsCTbcnnV4
wfTwkGHfCBGerSbbS3vbBan6pADuxFO4KtIrc81mmk7W2BrtScZAQDzlbfPybWN/URSr0cHB5eVl+7LXTrP5gX98fHxwtSiW8T6q
qQrhtbUI9KDd6Xf6g9N25/Cwd3zcO+ocucVInXppH/cPj3Db9WjoFs12Z9D1e91DPMXebfcNpO/LSDs9v9c5OvW77eMuIPQhqThN
hWgLr933h8Oh00K4aPrvoOk/xsXZ6PPHCfxeF1uPHBz4vthuve8hSszm4WTzIp2yEUz5aHcszT5FyRymDWn2dhVOjCWcSYFb2XVR
hCgp7xJSjBdhEs6JtKO9diUp7tvgZnqaxBs80OEBHhxfK8cFkOX5GpMs8ZcvDE9/f/lyD5z3IqUBoU70HXaP+/fV/jr5QcZI+ZEo
iBId7SyAzNowEBbtOTnn6ByTcwzObWXn6X2Sr1d484Lh2RSo0l5OdeJ1yKH0VCUUAn8rV3zHyQMhQUjFEJsVFZp5eEyjSL8NJduB
FHdhPwFHhHhIexyv2cgfHB53e0c9D3Tu6Lc1u1xEBUCH/X6/dzjwQhhFRiR/yLkMsyhho6Pe0dFg2PfC63XGUfR9iDxm0RzT+v5x
d9jxxlH+G+YwPDzsdPt9bxyHk0+jDn6TyYJNw3iZJlMK70KH8qg83QF3XETAZ8XoGJi92+l6Y2iUZOR3jrr9bg9QrbN4c5mmkLo/
OB52e743CWH2QCiG3eFw0D3yJoswKzK2znmBe4MugFJowhBr2Ds8gp7aAVbMwhgL0e93D7voTWYxnmHguAbH/vGRT+A8ij9RaQeA
zZtk0TJPoUyQrod3YyabMBGkmobZJ07d3jF5KKw3OOz2yDtP4ylLMix+t3PcPRax5ij5fPhz3PEPBYSxBGgyBPzCX4rxaRF+igBN
v9frDjiaJfTEpAhHx37neNjnOaZxdME4tsHg+BAEHQfzbVSs/SHQWcAmiwhK1gExh3dwEJaxKaEbdPrkz6ntoOVBYvV9ni5nIc8A
mOEYqMaBSGwiRf+w1+/1DzWUaouU6x8PTCizocDev63TCBpx0D3uc5hkjuHx8QBpx9hqFSXUOP7wGDMBSP5pwzM+9ge+N42WlOHw
GHhoOOB+ZvjT6Vy0eRdFMRBoFmVsnEXAsz4SyO8P8YQLcIvsI8AJx0A0GMVZXoim6g57eJ9otp4s8iikEvnHwBLzMErycZqlyDDA
a9A/5os0LySuHgj3Q99DzsBE4AHMBp/0e91jH0FYCcjBx6bgeeIRvCPu3rAYeBfK2+/0oOd4VEUZewGqzGbKLkWHhRIs0kLSrXd0
2AftM5lGYYKt7ff6g6NBt0+geUpU7PUgxkWabajuUMCOJ9hvcHgERe54cXjBEjzyASTvdZEzJAQomy8oXa8H5I7Dy4SX/gh4+fhw
6MHAnIJYiGYzZCykLcgYL8ajF7wrQV8CFu9zkOi1g8MhFGsoYNjJfCAucPgxBykCSsKAXDvqYrEolPobdOZuDzqmAHEOPj6CTqdA
5ViSaIOj/lCUUfYIAEJzdAVQdomu3+8eHYtsJWMCoNPri1x0lzg86oHk7VlgVgYXjMWCLFAI6FocrqoJzeMfIXCJMqx71CGn4Bdg
JWxKvAOWEEkGQxCEUmwolgVhn0KVUHYOO0fekk2j9dIYBYBpDnvdrggQXWcgvFKKdLs+craArtbZKmbQcUFGw5jDgYpKvWO8Yyfj
atEBGtbhIVBPwFeQ+5ynGPZ94AgO14KiD7yJt+c4nAsLztOd/qF/CPlG00QzFhAAuhYAkwKVxCWOYF3/aAAIorzYZDDhF4MYJk0n
kxCmcALSPfaS8CL8NVUyYXg0BL4FIDANDELAgDGO2kCEfm8wQABIYuqTPeB68k2zcDw67PSPQJ/0tEgG0QYdnvup+KhV9mAglbTt
96ADQNOvYHJoiIrBcHAIVeVgIhPewYTuxEGaTsA73WNoCwIbZOr3jkDU9AC8Cjch1GzFOy4ovN6KhZPFaj2bUV3hL0Rj2RrlxfAI
xL4n+8YQrw56q3i9xDG62x/2IHF6ORVCFvKGMQJ6omAJ5LJD6MkgchlQWECHQ2AJGH5F9YGVoBLQIBuhD3RhTB3AUJOlm5D3B+hn
Qxwm8nA6jRmPBq0LveHQU30UhB90Z/AnU4lp2OlByr6nmbEzANAhAvIFdCsiAdTiyMsjliTQTyDC8BDYFfSCCxR5IPq7KDWs/g2a
iWZkqE2nMxQQ3tl70KbQpEY/l5BEdOTBMbSlxfSDfgdyVSKgPwQlAuhSoPjD6cghehjIR6jS8ZBUwQKICTIIeAxUlyJdhkVKUv8Q
xnTP6DndATD+0BMDLLASDMVHQ+9yAZMn0ux6WCM9AB7C0MK9+TL9JJU/6ACGJBoew8jA/ZIdgSM6h/2t9wPoohmohHNUC/FA9E8A
WIAnh/8xAn4sAfRc8G/lixXRgw5eG20GuEHy0Ed3i9wP/IPhadEc8iO+bjSKHrQHpww+3YOeEdAAbytyRsbdiF/tCSeD+QPMHjwG
kweYOsB3DN+xx8TO22+l04vV3dkoJ21c7b1lgc8dc+kYg0Pd1WRyeoOToFO96OOMpPvND9+JfPhWnc4Od29FdqdifkD7Y6P9BMQ1
y/St80Jh/pFdUQy8BJ7MjRiATER5W2xwLcq55YhjJo9hzaVjbJxYpHw8Ju4l65TWaRZHkqih7gg5eG1D4m3Ie0QGdBw06J4RB31f
tGumUHwjiukaKBp6SQBJqtOmXTVjMtPoxqwSndWPb5/fkhXOgQM6rQ+8y4INLg3Ssl6E7oi7iTccWRxBZlGUExbnTE2BowcBMHvk
Nvwmc0ZRExflmZcFXVz0PxEYoC9lXuIVTf+g58jKSaAjKykBLYwlj37esd6Ca4wmV30sajDjkDxw/CrMckYrQBDyADryzmWH0d6j
eLUIjTsjwKv7zaK5v3cZxfHemO1F8wT08ynO0XGpLcGFgyQ4+EejcTqCgnxZ5LETnjp/bzQ+/uPvzpnr/N05aLMrNsEjJ9ZGRcY3
+nLa2isfFsc6jaQr3B9RKx784++52/j7tOnA19vhhnIIr/v39qkAOqd/EqXIHcdmPnVeDBmcSPUMz9ti0fyOY3WQXVG75ajjnVF7
RtRbelPUwF0M3uQn5fr/p1Xrqu+bqYBT7xoqILhMhVLUbjnqeGfUnhH1a6hgHMUHPhMMAq4ygxh1LlPhP3fAbieYEgFGf0ICOQe9
IRrxsMDdM1673Ab3OFiun5mVawtpxrebcGlpi4JnT/Svv/8/jY+PWt+Hrdnfp2dN509Gp5L7qdSdIrX2jTzTw3Gu1NS6Hdq4pPOo
aHScpuH2/KHF9dX4vhHfL8Uf18TvGvG7Ov4dRhOsw/Cr6+DfoQ5mmXp3qEPfiD/4qjpsTQWCN83DjtIQKNHLcMm3o0b6CoIBVjJe
7uN8KtCMhHlB9qxqYMNSQiJEfoPcfy9umPAVWbwGIE/r3vEqQCZILShYfyOAa3tyfFWRSedTR47egvrwLuU3B6sIcPOA1ps5EvLO
1ZBK3rFxfomjeZe+JZ2kjOy9jey9jey9jYwWg63ClZeLy2XHkzZWaqs01dR2YXXquVDwyurd90W7dpm88Ss/9wnzAQf1DdBz8ALq
D0j8jocK3oMH/vAfGjxX4CMDOlbQjijCW1JjKwVp7Hfozz4/QCuLi3e4RQroLo4wZdIaOoSNK247lLY71Yxp4zdUtSSgqmQBlT3X
p9H5XTh59Y1fEEcI3RtMvfhEnr5rhM0c+jVKnRCkTu6kAUyTgo6pAhZB3gqluhIHE9IHi4NG3gyh+x40ui0Id7xcXNOJRmnQSFqZ
c1A0G8mD7HQ46ph3yvYSjJDBPAkidM2ADAMivGVXNPvb9CAYKknSXgSpV7RzPNzXhjJ4dOlKqN03q9x3pKyHWztEVdzYIbritg5R
ljITCui3siRe342L0/8medP40+diu/enz5if+M7Fd7x1/nv035AFxJE8/AXmsco3t3xj8Dn/vU1nM3NuYPc0wXw/QSl+AkriBSL4
5k2YfcA3bgaRNR5jHIpAoc7OS0xZ0xBuTUO6NbV4g2REkpo7PSQam8wSj+A1RSR4x7dcjMrUxai5co2bxp2iqgxUvUTOoFumSCyH
zlumhCyHjltaYO46kpi5Bp1cg06uptPNV5IydSVprlxjdeit/kh4Rme/M372O1NHwucEnnPwXIHHBB63xFhmnhTX7VfmK96CDSYo
KA+K85YEMCedBPMWBTCnmTw/jlkIvhX3Iw12LaTnx0KLvnHBWfRH/KHD1xySI4SUkExAYoTEKDZLh14QpZCRuw6xZ/LYeoZazFz6
5ugbS9/45iPtmXGkfW4eaUdi0HGTOx9wz6wD7nN5WoUju+tx96x83H1eOu5OjQSAD+r8e5H++e2rl42qQIHxzrn1eHlmHi+fm57x
lmbTPxcnvxXtl49ePH0LOp64wvtL8TnHk1CTPcjoSViE7988FzbIDv4xBf/oIGoXLEdtJc8memaHPhzKDLOGagHqx3cvnj8Ok4sw
F0c47FR0ioYmnXtRwi921CZiQcHHRrWq9jPeyv+5CF4Vjf0Jxd13HO9nGJLwnnAgvgjg94AD6VAM/TPR/HGaFOwKkHSn+86JVYxn
uLWChDiN2qt1obz87JYzitrTLLwksDjOJXOVeeFC0M/FVq1CUuhDXM798oWJOOQ9bdTpzISabnK3dZOMeLnEOQY83VCke7+u5nsz
UKhXLMMThVgBPLmRA1I8E+MxUJFkk+5HmP7g1xWb73ttUJhGNaGrZL7vbAU/5CVN2W7re2ZbU9lEq0GfLbeqGfzlyy4kVtvXYLHC
69FQRt9FxTJclRAYIfqMnclFJ6zEQ2wnC7EqB92BKU7UGh8m12xVz0FZkLSx95UO+2Vy9o1n/jK0uYiqCcxL0I1TRiV9S8ybEPN6
bIu9jjCbNwzQX7UFyLNkZpbMpKk+qAZ8XQkwD6md4tlEc7VYlJrJUgM3YgwBkpX4TPKHeUSckSQSJ9FI0morO9otfcliZwfnpPqk
EHE/t2Cz9zLdcXBoD68OR7Q4CWOA2EP4ULaAgNZtxNga5W/TdTZhavtgvY6mAVr44l6sndQwRB5Bh4wYJIxN8/erqThje48MQYpF
fRGz2ZTDhXFoVFuNhP5R2RVAiXuPGUewijZVPP+oSnemBXUlSPH/Z/SOVIC3zuLR/v4WT9XLatG6LVACMknkuiyAiBmALnwEThwg
FIzClvHJCBhfGZ+MyPhkgsYnoxz5+B10uXXGTgtuTPTPRYMHYlmBiWyw4/A1riJAAHZSKGmgBfOXL42aagaR40WGjac/G9s0/yfk
3+kvRdsa60dcAJzy7sbbCFUcKShu7n8e5i1QmAs37SRcsu2odogTzYidMBzHDMeynGUR3cTcE4HYzdDyMTLGX1AU8Q73J2CTq4Il
U7Jxa/e9PxXtJ0+/f/T++bvzZy8e/fAUxmED9OLR69fPXv7AjSP7wK30ybhd45wbNA65meKU2zWOzeSPXj57++rdm1evf/EmaLDX
+QzyA82peKKzi3Jjbxe2r3j7cNsrBT9v7O1H033v80WIe8F/AZG6dWplAxIv2N8Xc0UuRnB57EOhdtqW0QpaM0c1lvtDPFeltrku
s3D1Vs420fMuSGTE+fdRDEpkkElMiQDkHBAmUZ4WUO6NuODXJv2iCEJRWTQek4Tx9xxKFr0oAHkBFw/QzafJVOrndPlF7hCyFQsV
3Jdn4NsThlhr4ouT+kFHFh8vfjxaFymXkEq88gBxelvo3MKg2AtBKxnVuGhAe1LBPbGfO4uj1S9aYCcwBnx6FEfzBDtd0BdXMJNJ
OkVST0Q0YF7sTsHnbUmaC0okoqSaUFH+hk5avSMjuop1RClI/r9+8ebpC1lFn+zekLAq37Ek5qDuR2MHjyPt3xihIPnWhE1cqxEx
ONXa5cspugXlhVnh25itKMOEb2O3mNmuMqbwoVGXu5zW5+u8dKmwbsmXuklBH6urFMJh95RCupSuY/ecQrrMHlTwr9mPOOhduTcV
2l3uV4V2V3pYYXiszlYIR22fK0oAo/9xG9BWo3HaCZ/VD2UQ91ldUQZxX7k3FqVmrnTLogIyI0rk3OfUd9eiDNnRe4sKyOzNBf/W
d+miDCl18UI5S30dda827eQ0yMnVrWiGlZKRpO0SQ5+TsuWP0N4KLjbq9beaQK3BLVkR0mj/WYiqUb894CP5vhBG+9IaY5opWJsX
GnS9kgqIHXCkeqRHMmhkCiBVWx5f9LOR2f08zoKjjzfIlzOPs7CIVC+gzjzOsSJSvfw58yT7jmyZhV1bpCx3/DOPd8iR0UuF+iM7
nye5ZWSxkae6/8iWDJ4SGSNbmnhaKIxKEsMjdh5pDvfK3D+q7SZeidNHdR1iK+Ze+5+3oFcGZdY2u4CDh7Z0h7DDPK5e13AhV7DR
6D2/XiptiBg28D9zThRx9rfiNidS/P2FWIswWYemGeZlE5Cplp0nLXdwnfPqQefLF/g89B1p9kw1t9hYmYwKYQjLPOPUvrI2VxYy
0oPOaWfkm0HrEb6DoO152kj+s+ucFraBH4CiCYtd2fJ5+4YXfFNT8HdGwbnJLgvDplJwivR1Bd+IglsGiACK5jZ2ZWsanePcii9N
QFy/xS1R3TThbdgzXnOIL8lUZ7sta/9c26pOAEANrlXrA19MMf5aa9UQ5g1oPNt3Pv+1zrphv9a6IXdcKzU8SHbaO7yusXd4fZO9
w8s6e4eX2t6hZZX2DiX7WiuIWDqZ+I+wi/ihHHhtBP6tHHj5R1tUJGh3JHK2oL2RyPLfyvqiKLBFMVlei1L/KjuNgisET3yF1UZs
aZUuMBScSxA2lyP/a007tq+bBkJ0X369yUdColH8TjOQvIrgVdWEQoH38vcbiRS1lT5e3683INm+bhlEa2mifY1hSUKiUfxOY5Oc
aC2baC1FtK80RQkkMiro6gp+tYlKwqTxiCbUCkf/FsOSvJuIo8CXaH9kl6nJnJuazLlByRzNryTw8btnbiYplnOjkznaaME4xyJO
T8W5hjhdHmfI4/gdEamvIl1CpB6PdCgi+SLSQEb6amubIJwfXUX5IzQ8h0Y7tFViY8Tq8ovTIVleAMFxYtljIDtzqCxcuhQoV28f
+KzVPxUSSB7H38gll+ug44wamsUOmMFgB8xgrwPjaLlVVmkhQlshoTVqbrPjRJq+buMLXkHbR7sx2l5DHKRo8mACH7JSlKKBgjV8
fLRSlHIrRSlaaVrCp4tWilK0bTDHKB16vkmpYJPW2nmQ37+vAIvW0gasWjMAkFasUzUhVWimai5twKo5swFxc9qct3oAdHYY8RLH
Jpl8yuREHlqCtL5z0AUiNKbcdRE05tx1FVBhDvreeUClANcmoOwP+orfH6b37xcPL06LB/lpg6ta7cPOod8ZHuKVIsMD7RoZrFHg
oYSrgwjinB9EzigFJClHYiDAtbgSksRAkuKB/asDaNhgc5A4o4saBFZxkLsyA8EFIjg/wGNim4NMn7nlJx/UYU3koAsjWWPWWjku
/TapXV36bTbWrQm48VdxvGqnCwcNEOCVmYtALp4CkRHJwYVkc8IjvdcBoZLey0B3ONHqPhlY/4ON1UK+dhgI3/a1YxVChV3iLugf
buRWFUGG1RVBhplF+NcZx7WKCOUzYorB6tqpKTCU1oh5KbWuf7HBXavwlVi1Ba/EuvxfbrxX0sAIKXGYEXL5Bxr8lRnrgFK+OuDy
jzURLHM2QkpZGyGX/z5mhXHIp0810XU1ka4S/1QTXVYTXX6zAWMoXMuaQgnv5Z3NGzeFdopTDaGegpz4OnPGCgefWkg0fMXhm0wd
34Tx95hBLgGuy4DLbzaU/D9nLxgnczgKCEZwjFkdinzBEP8U68JiiorDTgvHSDcyp6o4xqAS/i22iNF3LX3X6LuUvstvtFOMhdWH
OrGMZEXs220YG0c8r6VJMtn7/iD7xkRg88AnkXaOi1vqMs/vskCspLIFvPz9topNz7XpuZTnoAq2+1iGj69cgXr8eVs5M/E3Nv7h
ubkTrlZRxWE87hEn8URfmLIVBIkZXz6J8jzlxwb+ym1sFlLdloHvWF6ovfWLiF3isa9yCnU+77M47iIPujCPMhz5W34BV2xpUPo/
FY3Ei9QOViS2jCKxQRwZ+zmRsekTyc2jiG8aRebuTqR2jUQtRIa7zgx07FjiBINvQ8s7q/oiVzkInyeu3XVVxbA3og1MdshpGTAy
zokIXHqH3ECjgKeGezQzGp/3Rb1hGpngL18sr+AE4M1JFFsJKTMrgJ5mNgFGnpLeRloTfmp7jbrmoNTGzCK5AJ0q14jO/b3FgYXE
OG4zGN1An/4TPYFuXhudgYyuNe7WcaJSc+JerZ3KDrJx2GEWRrWl59g9TRm/rXRMK+SbD4SY1ZYHaY3K64NqmgYF/5bKKY4kSL/d
/fR+e1sU9G69U61miUNhIC2jedLAo0I2Me2JjQyyz35J+pm9oLiN24sST4uDmYXFsHKzzeJ1O4qst2PzdSFdconwqzZ2xfjB9Pjx
p7ojtWII8fkOHB9F6KitHElw05lG/bJcJNoG/GxjIY4yMinbIyHbk235MM+0fIRnqg8CvAkWO46X2afI/PojJ76sdPRHVLr35H9R
jRN289aqqJdeJlaVOlf7j+dq9/JcbV+e486qvLeASvH3cViULSzTfcwg+pg0O9yOfNIUluQTVCQX5OjJUzLrIPuYY8wpOXxcsUVH
F9ds0dE7k6a+9Xop6I0dfClBKJex1CsnZCSmIfTKhYMp/ZqUa5lyKlOurJRLSrmA3rv88iWFz/rLF+zL0y9fJvfQ5jg/ax34rVDJ
ndRdN2N32py4qybaFY8CNFp76o9axFgt5tJdnOThSzI00376+u2z569eytUXc5UzceTFV/5sTOYxN3JOCsNWsps7B5nxDmQjJMhW
IgvdCHNLoVhFc+1m0BAxuKbgmgQTcK3AtQgW4FrirgMQCSqjzRD4B8aqrZtCzWKo2QRqBlRNcTcmxp8J/izgZ7slpb+uSWRrSMaR
EzrNfXmZjWQ58E2ChL9JQEwUSyaaCCaCKgCP4Jq/YJ6pZJ6VZB5zThJC20zcRTN1py18cFIUNiUwNt+iFbqKJ2ICT5uhu27hC5Gi
ItDAEGsBoHULX6zkZweuSrOJc/6w4pUaOY2elSaPF7gF/DiM4zH04AZdpt4rP+txzp9a1IPv+eY2FNdlFPy4w7VGcX0bissyCn4A
4lKjuLwJxc5TEbdLlp1Iv9KKwfmVzEfmIvOo3yw/N3bLz43t8nNjv/z8Um1k7i6hMJnP3/8svcUBhcLDnFAm1BSgSDiin9NboLIb
48uuqX7Z1XjQNWwk8jHXjD/kmvKgKTgS/oBrSkHyTnuu3mvFx05FLdcuMj/wrLtStUXfooUhK1XrGH0gNabuQtUeYRgP0tpvrn4r
/lYN/mYF/wd609XE36rB3/zm8n+g92y/Bf/dyv/Lh5/vQJ+74q+W/+cPd6HPXdvXKv9Nr+Bq2c2fwdVsf/uzt7k8o3PPv6cnWLd1
KrVnbHcsdtA1X6qKbO2e92w3Mfu28lHvVr5L/SxB5Nytn1d3rquPCaEagFvUCX/IIuPvVOT8gYuQv1+RBvSQUMzftZjwZzAWAT0n
hG/uNMMm2QFaP+zoAbo9MEboddN3TmQ92t3BQaG0ucaklTqulryNrBVr/3XQyFsJ+JWZouhhCNPzhwudkzg3wA8INKNW2FrozAi9
kR1kbmaWoCkOI7OsGYNfZRbuzidsRVY+WGyzWhbmjZUv5JM2JzKfHfgXgD808Odko0Pj5yXVNeEYVQ6Un3Xo8jZueZ9EhXU+h78K
AXO/FCecTV9dKX1ga4h8n16vubevnIeG79o5lcNe0NJj18YY067lcQ2oaCTPa0D0jorb0gPdtTEAYnQjPh2G4svWLrNyQj8tfrvM
QoR+Wv121c4tIfXKy/z80UTr3UHzvIqq70Y+hki7NF4L7zU5jngo5V0KMmqa12xqauxyMmEZo1KLktrWmccOSsIkF/sO0oDfDY+x
yVdH9HNJJZP0v675rtXWcJd0Ejdo+ZLChvvacO/iuJotrHPcwzoXO0bnuIt1LjaMznEf61zsF53jTtb5zq2sc7HzZCLiX42LfzU6
oUPesqX17Zjt3Sc+L6vdyKbDzqc1zN+p6SZ4cgVnQVoiqGJqtpcF1Qwvi6qVRlnY28aU2x5/M2ZLX/NmnJWs9GycHXYHbfUSRywM
S/GzwRELwyb4uSwPvBHMFnM3bOLLWpmbKqolBE+bmQsi3o0V7TKCx018MytxQ0VBfJMsgrgJwDMVf6ew1ZuDoqMzq6OLBQELKG3A
nlgig5NAzCMy2bTy7UuoL7JaCMVDwkCpqXslvGNl1KXIAtWDjmQ53GdGGhrCWs9UyKfnHS0iehi0QmHUVhTRCx8Ca9rTM3mbFGmu
qazp6hkSLsVZvkv3xtMHQf1KBC5rsJNSHoWbN5nscrpPuJGCGhMoN1FQYyrlZgp6XZH/t839qGSxfZRsYq6RxF6IEySlCTagEo4L
Yza+JadfMiVIuXI5aL6yo641MRX0SkGRfRdKQq0N5l0oObW+C4uW+l55R1k0txhzyJCx2rOUrWRvN5aOceqXtdThPTGevn7m2imz
XSHV57hcpSPDIBi5xqtp0ideVGM6LEH7ANVN7HO1i31O29jnah/7nDayz9VO9jltZZ+rvezzWzazz83d7HN7O/vc3s8+tza0dzfZ
HXa6z+2t7nN7r/vc3uw+v/Nu93llu/u8st99XtnwPq/seKuqVRSDcp3lQesaYny+dT/73NrQPrd2tM+tLe1ztaed7VysxpLW3AHq
3XwHSC9BqZrqHUy8SxdYp45239b5lks6/8S7Of/E6zf/vhdt/rV3ar7tMs03Xpn5xmsyf9jlmD/wNsw33n/5xjsvf9hNl99zteX3
XGdRaW+uhWvXwrVr4ep2xCsxYtHZRkMhxmWQkNmLdQWMzRSntLp2Nxx2Imdr3wW+29WcXTdyMn4jB1+BBh0T336WK3WbIOM3cTJ+
WwcfeZZhoIjxGzgZv6WT0U0eg0o3PXhbKr69OvENt47MF7b9g0bGr/1k/NpPJq79ZHjtxylVvqFq39e1wKjdM8fN1dUDRQdR12MR
q6dj4ZKbpMhQ5NsR0foq2rbcxnet4RXNCzf4pjNAUtoiiYMUbze5CUw0IryaA7mGLoO5W4I3dDBvN2rlIDnWAQAZOCOImpRoEMMU
ce22subExRVHt6XqPeEheROAWSuGYFnXBQ8JmwDMW5BQXKcCFQLPhNzQ4H1lIuNvaRZPn5ExMuaUowhEas3X2a6TuyEvp9yVg1EI
4zb+kyhjk+JrWua2btUvdQ+zWxnsVOlWJhNVF/H4ed+KLDwwpOmBIU0PtDT92htv/5rbM/+iGzL/lrdg/s3utvzfu7Xyz72b8s+/
gvK/9qLJ778z8pWXRH7PzZA/4i7IH3r74//MZY9/xa2O7SRL87xcYwKqnMVivg20l+P5ajxfjMclaBwAcCl+Qyvx16VBnq+Uh2pc
d/NWJBfgrwO+lp5bmtGrRE4BzT1szbUndWvpeqfLWDnnG3O4zXBgryHLFc1SC0eOLsPrOExM5SFnxjHkdrWo4nwsTD1BkdpmbBbX
6GE8eFf2XdfYTXSsXcjq7XiDp5EorkmhKonEkupB195W4Flp4ug9TnrIjG9o4uleMilqbYiWSqLjvP1tHWZsStO5OmhJZUR2Vmoj
bRlL1RFZV938B30vAmUvcRMtPp7sLJeWIdRbynKE+kpZllBPkfvjb1cLlkXQLJUWLIU/BnmOm7ztLJxGa2Dk9moR4SnvBSvCKjoZ
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
ByuV+bXT9YmtPsnbf4p/PAoAqfHTVAZI5ZerFJDSX5Z+QKo+LTWBVH36tAVS87dPdyA1f/vUCFLzd6ZGQepJtDUMUsIzWLoGKeEZ
bKWDlPIMfvWD1D31HW2E1Dj1bb2ElJ76XhWF1Dn1HYWF1Dj1Xd2F1Dz1XT2G1Dz1XZ0Gs6Pafs1ScmhzYylgheEJWlr9a+NlbUqO
it7SB6yyFUo61XYClK29vJyU4q/Jt07E/pGq8aaPFFO/Is5QrkidJFfZIqW/HL2LlPxw9C9Syjxamhip/vYpZKTm72ztjNSXmqmx
kXoSbSWOVH9b5zrLUt9+RY/UTsnU+0g9ibkGIORgSMmPh9lm8Dg4sQzcqKSA2uuO8FIqyry4Q42LQqLtX4BMS5cDpnII2CeB8tiZ
Vh67tYwbXO2xaHIF8et7VI2MKn/Z+S/IasP98kdarK2srq7Way39nEAUfpRw3U3Scp0akZiTgpb8u+ZI/2hZ+Sygk4TIiuoocTmU
8iZJBEPKG6Up6qmsr1k8l1Id8jBbvhxgmwR/FPgZHjMbGY2qcoKttG1szW+cSVO5nis5SE1v+EGmBIyjRtacpOoza2ZSN43OVcr/
eqcrtRLc2UvpL2saU/VpTGYqPswJTeWXZ2JT46d/llM7xZ7zVH9nTn7qScxYD6mTlLU0UjdNL5MU/uVERahBzZSd0z7/2kuFSum5
RQq4pYZreVwqpVfj4XeM2wHvL13q5M0yY9gohFCpMLkaTgd99FeHdfr8FAU1LUFnrIpqgRv6pghMmlexs+sab5DqfAOnBfoC+UY6
FnkZbVTp4xSrA7p7oGUmiTQcEdM0IH5U+KvwzyEeR6w+Qt8o12wNv7th8mE0GIZ96g99cYoMZx207viSQpRSGXzOtehweHA+NsjI
828zngpPK1lDl6pPOoap8Ppgj1lKftCRS/lfjSzxVrnUMVoM4iXGT8lflIWSav0qL3k1bifKkSJg/zVdBt5K/IjZD8tpH2vZ56Cf
Dwf3ui580mlHbw2hp1iX9zmJQMlyU6PGRzmq2Y/9pjugTs1uYSzbakfR7M9firABIZIf2GUprw2N+yMxy0dilofErwyLGWAxg3CC
MzAEM0bUdnz8tMg0H4DMAXGN/ZQYWXDvgRbeRRka14bftifAywv4HogJczsaLcLaDNJEDXSS0dsux5huuCVjNRr7jRAD8CnU2YQg
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
a/y7xdb6Gn6bYi9231F1a5WVtVo1Wq6uwBG8ut5q8O86W+ZrTfg2696Emu1uVhr11TVWZj0orFca1eYK/16prNTqNfg268LDaAcx
ly8npKMAGI4hdnLhCy6cSDgcy2qsluDRDl7s+LTx7JKsK1pijVRugR9er6w2V9mw1Zq+5pqVVn2tznGUrbI+N9bXsc9W4/LOqjAg
1ZcsdAgihZd4pK+staLyKh2J8SVIPkw6tQTjY25sVsyzrgxZNl84w2kKZry7h8dy1UdpWJffrHOnIKmoyYT0Cg1rr0+vGCfGqTlC
P2c92LGJ0K4hoSRkmbUm5ae0fd7y5Ho4TK8maTQqKnfQbEk6LTuiXMaBILL1kz8U36TBs61oYVAib7G8tOquA1vmcNi8DmlPlEVV
GFpUSip+SvNtU2ZBH1nvvM0pCk6hmqgdA5m3qJrZ04AOg1W5Vjd56+OqYKjJWJg16iBOYfWM1NMaJvOBsTNHVzE2UxWCXzFQ1nS8
MrBUlY52bVjYEtuKZV6G7g5YhnxxWWeleKDmy9R6m4YOSgDHNXcwBdDAWT+05eN6wxrImjWQdYuUso40PHIIMTiiUU4+XrlLF6tL
CYwaI7NqLbdqLa9qPbdq3ayqTih1AFkVlzy7d0kPjDUsWhsH5xr4EmzXGO4aDp6YVljFSzAFKIttOWoHnHLyKnw7YX1zAieKaOBi
LnGIHk7IrbtV5VuCYXo8ERm7LGmrapSCV3PWTBkbkGPHeADgWhgDCvunzf68YqPYLiwvs09COVjtpQ52oi2TuHbItRp1P+tQRDhL
nIMwUmCsSwraLhx90AoDadIk+r6wG9AVa78hvQjOp9ejfLWutx/2jzIVu6C6X7ULcjBqln6t6b/v387OLr73i/TcYeknp318jtjp
M4xRY7JtZc949szM5i29HwCDpNqD1auVAwWCUhHT1IXpv71dsOayQJJBYOuBtWjBmd0LzsyBo48ZULB4exsgTJvXHEVjVuxcuCcY
nwv+fTIdX5wxRiogP+HCh7/FsEuGAEIyEUcpxvl/cxJfXoef1UxIuNrzjVnyi5qUnJIHsIclRiZJIE8LHF4AxS0yTQodBApFcwVc
bEepes7iJQKAD5vG6LCB2btxCJqE6DGRg+AcBo5XBd6KGIhl8XOG5MW+jxERAL6XKSiqx3AnwoacnScjBJxxmzlz8xUOPuyfbe3t
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
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
                elif key == "speed" and isinstance(value, (int, float)) and not isinstance(value, bool):
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
            elif cmd in ("save_begin", "save_chunk", "save_end"):
                self.on_save(cmd, msg)
            elif cmd == "save_prefs":
                prefs = msg.get("prefs")
                if isinstance(prefs, dict):
                    clean = {k: prefs[k] for k in DEFAULT_PREFS if k in prefs}
                    self.save_config(json.dumps({"prefs": clean}))
        except Exception as exc:
            self.post({"cmd": "error", "message": str(exc)[:300]})

    # ---- export: the page sends a finished file in base64 chunks -------------
    def on_save(self, cmd, msg):
        saves = self.__dict__.setdefault("saves", {})
        sid = str(msg.get("id", ""))[:40]
        if cmd == "save_begin":
            name = os.path.basename(str(msg.get("name") or "export"))
            name = "".join(ch if ch.isalnum() or ch in "-_. ()" else "_" for ch in name).strip(" .") or "export"
            stem, ext = os.path.splitext(name)
            if ext.lower() not in EXPORT_EXTS:
                self.post({"cmd": "saved", "id": sid, "ok": False, "error": "Unsupported file type"})
                return
            if int(msg.get("size") or 0) > EXPORT_MAX:
                self.post({"cmd": "saved", "id": sid, "ok": False, "error": "File too large"})
                return
            os.makedirs(EXPORT_DIR, exist_ok=True)
            path, n = os.path.join(EXPORT_DIR, stem + ext), 2
            while os.path.exists(path):
                path = os.path.join(EXPORT_DIR, f"{stem} ({n}){ext}"); n += 1
            saves[sid] = {"path": path, "f": open(path, "wb"), "next": 0}
        elif cmd == "save_chunk":
            sv = saves.get(sid)
            if not sv:
                return
            if int(msg.get("i", -1)) != sv["next"]:
                sv["f"].close(); saves.pop(sid, None)
                self.post({"cmd": "saved", "id": sid, "ok": False, "error": "Parts arrived out of order"})
                return
            sv["f"].write(base64.b64decode(msg.get("data") or ""))
            sv["next"] += 1
        else:
            sv = saves.pop(sid, None)
            if not sv:
                self.post({"cmd": "saved", "id": sid, "ok": False, "error": "Unknown export"})
                return
            sv["f"].close()
            self.post({"cmd": "saved", "id": sid, "ok": True, "path": sv["path"]})

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
