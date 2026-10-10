# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Real G-code Playback"
# description = "Real-time playback of the sliced G-code in its own tab: a motion-planned, accelerations-and-corners timeline of the print, synced to the slicer's own time estimate."
# author = "NickChung"
# version = "1.4.3"
# ///
"""Real G-code Playback — watch the sliced G-code print in real time, in an OrcaSlicer tab.

Changelog
---------
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
 "version": "1.4.3",
 "entries": [
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
<script>window.PLAYBACK_ABOUT = {"version": "1.4.3", "entries": [{"version": "1.4.3", "date": "2026-10-09", "changes": ["Fixed playback running far too fast in the first part of Bambu Lab prints with bed leveling (since 1.3.0)"]}, {"version": "1.4.2", "date": "2026-10-09", "changes": ["Pausing when you click another tab now works in OrcaSlicer"]}, {"version": "1.4.1", "date": "2026-10-09", "changes": ["Clearer setup instructions on the start screen"]}, {"version": "1.4.0", "date": "2026-10-09", "changes": ["Custom playback speed, including slow motion (0.1×, 0.25×, 0.5× or any value)", "Option to keep playing when you leave the Playback tab"]}, {"version": "1.3.0", "date": "2026-10-09", "changes": ["Print options: choose bed leveling, flow calibration, timelapse and the other printer flags in the G-code; blocks the printer would skip are not drawn or timed", "Bed leveling counts as 260 s, as in OrcaSlicer's estimate"]}, {"version": "1.2.1", "date": "2026-10-09", "changes": ["G-code panel keeps the running line centred while playing", "G-code panel button moved to the front of the current line"]}, {"version": "1.2.0", "date": "2026-10-09", "changes": ["G-code panel: expand the current-line readout to scroll through the whole file; it follows playback, and clicking a line jumps to that moment"]}, {"version": "1.1.1", "date": "2026-10-09", "changes": ["Packaging aligned with the OrcaSlicer plugin rules for Orca Cloud upload"]}, {"version": "1.1.0", "date": "2026-10-08", "changes": ["Opening the tab loads a new slice automatically when nothing is loaded, and asks before replacing one that is", "Playback pauses when you leave the tab", "Shading options: round lit lines, layer contrast, height shading, flat colours", "Hot end and gantry can be shown or hidden separately", "Playback controls centred in the bottom bar"]}, {"version": "1.0.0", "date": "2026-10-08", "changes": ["Playback tab: real-time playback of the sliced G-code", "Motion planner with acceleration and cornering, synced to the slicer's time estimate", "Timeline with layer bands and filament change, pause and heating markers", "Colour by line type, actual speed, set speed, volumetric flow, layer time or filament", "Moving-bed view for bed slingers such as the A1 mini", "Loads the latest slice, or a .gcode / .gcode.3mf file", "Playback capture step for loading slices without permission prompts"]}]};
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
    switch (e.key) {
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
    $('hud').hidden = false; $('viewbtns').hidden = false; $('legend').hidden = false;
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
  window.PlaybackApp = { loadText, seek, setPlaying, get job() { return job; }, get time() { return simT; },
                         setPrefs(p) { Object.assign(prefs, p); syncOptionUI(); if (job) { if ("lines" in p) buildPaths(); else rebuildObjects(); computeColors(); if (R.main.userData.thin) R.main.geometry.attributes.color.needsUpdate = true; else R.main.geometry.setColors(R.col); updateScene(true); updateHud(); } },
                         frame, onHostMessage,
                         // tests: camera state and the screen position of a bed point
                         _pick(x, y) { const r = canvas.getBoundingClientRect(); const rc = new THREE.Raycaster();
                                       camera.updateMatrixWorld(); rc.setFromCamera(new THREE.Vector2((x - r.left) / r.width * 2 - 1, -(y - r.top) / r.height * 2 + 1), camera);
                                       const h = controls.pick(rc.ray); return h ? h.sub(bedGroup.position).toArray() : null; },
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
KZyJ1G9yZfxzmJz/xqIvgVvVamKVxwXpeYtIrKw8qZ9+ffnMjQ29pmbcCGsq7CVpS8TXUcJtFk/ApOWZVjHTuzKhNwcG/f/AZHCS
UDVovcnKyGgEyhqPO2gFc4KqGOfzJGHkXOk0I7PdUil3nqHYMkHHRABWXxXkcUo5ctEjQ8Kvim0Vj1/N/TYfPw7U0k02UsRhzvLC
u46V2f3YiAI3gl53tnqysvdwlLtZUo59aTUUXKvHL0mNIfpmHRdXtYoEaRg6usbEbzl7LDTc8IRXWyHneMC/KYlG1deGCuGrxGZ8
fhj+zqtW5kYWNr5mh4q3iX2SmPaoVXNUmqUu67c5LUKrh5I0DuWCqOi2vNgz06KUC7lMBrmrnuUhCQbnbfqqerabJ7YFuwTqlAM/
i478dZQp9V6j/+KI7ZLGL2H0rUaYFcbFS6AWptgyAjGsX9t2IRhzYydoJUFhxyrQaOVntSDYxaykP7k9xm/GL1JU2BS6SWSo7Fqb
pIz0u4wkiiN7MYpXixDRkINInUAOmkatWCTNP1gQ8w8D/hZqULblu3tLHJJiEl0R1T0h74mmvVE7AIOmg2Js7idJaVU3kyC5JKRx
JwWqWNc0Y/vyPbq+2wjb2YpU7XY5jqiZztlF+Tl3WUGh5CdCf+I7G6qziZHE7zFfyOJavorhygzFOuq3gMcqW2iqFSaZUL7FZ2a0
GWZLL5HAS/F7oaFXklFEWJqmFwzR+jiLJzO4RRM09UBl342PG+IC7ZFZBeOgs0Oq++r5FpNBlyzugLAkU1VNknqiN1qHnv2hST2F
EywpoeFiCFr9sZXkvJmMebYvpYZiDXe3gq7dXHhvGa1SvWC9PqUSp2FIqb5iUzSwK7mpgNzUQT5JPweaVhe8szWikC9J9Hrow+Yx
8utnvvMWW/8SYx7GfRM13V/I0SwvYV9dog61NAQG8d1gqSVL2ctAMzZmW5bASFuoP4EMJWMgYQIJl0hc/lSgoQ2Q/cmNMG0ytpd5
ZT2lTI6/9IY3vGzfp9ZjPgM2N5nXUynmZVVDYPrf4FDTtmkM2WzWGqy993NrxaBhbaqyWsMqrj5I/QI1cqxOdGTjxwZoSc/VJpBA
eFdjEX5fBEwS5VdtRgX8g7rPDP1ee4yWNk5AdnQLHI1TQI1NIwjRMEZkNs1ti+Refe5DyLkIXaBVW6T6OarqdR9nch+Z1Tohxf4y
1r996ql6Gg89BdF45on6l2Cg/IbyctTJa2xrMDU1q0zKWp6dLGoxaWFphCb9ymiyWpQhwUuV5Bbw32sLKEv9q8V0FimA6wYJ6gnF
UpI965pykaOM/ryTcivjsB/6QqhnUvGlkHH5FfGKnq/JLEI+my0ZFDmH1zU3E3hpobFjr1tu6Sc21VBSnxlrBFh7oPvJl5vHF12r
kul7qGBOCzVglI9J9x9POvp8JM/zGmVvXH4mKV3p7UoCXzcAqqxT/Cs5sIYLbBUH5rzFrNpW8WFGDStBv4RnW5Np+5Zc23K+atRq
YK9Grf8v8lp1r8iDijoPut9zKPEYHIotS6066Gl7vslS2cBSjC3GWCimkEwlD9NpdtlGbdLe9Tn9Hzlz8apKQyqAuK6m0RfzYC0n
zIOftLIxHE1IcKIUEK3Qig5Z/ZXxWZzEJdSJBtoTaQwTtqAlswwlgktGBA1ktJM3U124aDd6D7Sibo/rzja/iP/7WgZQlEvMJjt9
gw4MdwcGSS713asU/L/WJ+QReCsg78ryUPya8/ALj0Krx8fQBHQG9C96weq1dluoxVgDwYvjpKH4FuYJ5r6Cd0vcV/Y9Ytipu1yt
Shxf4cxXVc++uYVJ/hSmY9pnzUW5Lhrcn1ouL77YB6rdcvZVrtygTntf0oCvccHqqL6vq+83eswUoqm2lFFh2boQSsyS1lKTG1kJ
i3SWsb8EkxNo5CLepSYWJIj0ygjkwg9mPRaXYTq0s865UWvjoFLFBj1HFIaXMSC5spwiI2SyQa3wIsQRrFwcH2dxEpmtAKKNbGwz
fhplp3DVNVzOgFieZSQZ0x0W+vZYwaDiyXG3AayrMX3+THuypyS6Fm7yhPydWzZnRC1XMrn1T2PjorPmWdPCTPoZ4kJtnbylh4Lh
v+5sP/3CY71KgH806G9myPkRk03f1QpUeFc6Ib1Y4THRXBLixVRwNE11eMuJTNGjOEVmq4jqnZBvgLBUabsV0tjFYBpbyp6WovpS
8df0dKp3oWvDmZD205ZhfW6rIghJgHaKKV+N9eOSIWv15bOycUMQf9E2qUztxbPSoHWfXGUzfJdku+WcNOHvEq5n93BR8/QpKeZf
vZJ7tHbopNDDyYdvVXTRuFbxQX7VQnW7s21apTWXtuTxt2F9IuqvWJy61U0r01qMAL7OSlRgX7kM2Ytz0xrEUVhvAZrtWH/1Qe3r
LD1sBqsvPFUSIV2h17j4cFqF8+X1ll3jMDseblnZ3qQHXOPtet7ikq5nLQfzVmcxBhUvqQOtH/R/AYEpGK4=
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
