# Real G-code Playback

**Real G-code Playback** is an [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) plugin that adds a **Playback** tab: it plays your sliced G-code the way a printer would print it, in real time.

Each move is timed by a motion planner that models acceleration and cornering. The playback clock is synced to OrcaSlicer's own time estimate, so what you watch lines up with the print time OrcaSlicer reports.

## Features

- Play, pause, step move by move or layer by layer, and scrub a timeline at any speed from 0.01× to 10000×
- Timeline shows layer bands plus markers for filament changes, pauses and heating waits
- Live readout of the current layer, line type, actual vs. set speed, volumetric flow, acceleration and the G-code line being run
- G-code panel: scroll through the whole file; it follows playback, and clicking a line jumps to that moment
- Colour by line type, actual speed, set speed, volumetric flow, layer time or filament
- Shading options: lit round lines, layer contrast, height shading or flat colours
- Print options: choose bed leveling, flow calibration, timelapse and the other printer flags in Bambu Lab G-code; blocks the printer would skip are not drawn or timed
- Moving-bed view for bed slingers such as the Bambu Lab A1 and A1 mini
- Picks up each new slice when you open the tab, and asks before replacing one you're already viewing
- Pauses when you leave the tab (optional)
- Also opens `.gcode` and `.gcode.3mf` files directly

## Install

Requires an OrcaSlicer build with the Python plugin system (releases after 2.4.2, or a nightly).

1. Download [`dist/orca_playback.py`](dist/orca_playback.py).
2. In OrcaSlicer open **Plugins → Install local plugin** and pick the file, then activate it.
3. A **Playback** tab appears in the top bar.

### Recommended setup

In the **Process** settings (Advanced mode), go to **Others → Slicing Pipeline Plugin** and add **Playback capture**. New slices then load with no permission prompts. Bambu Lab printers are captured on every slice; other printers when you export or send.

Without it, **Latest slice** reads OrcaSlicer's temporary G-code instead, and OrcaSlicer asks once for read permission.

## Notes

- Read-only: never changes your G-code or model.
- No network access, and no files written outside the plugin's own folder.
- No extra Python packages to install.
- Heating time is not counted. Bed leveling counts as 260 s, as in OrcaSlicer's estimate.
- On Linux, OrcaSlicer's plugin sandbox blocks paths containing `conf` (its data folder is `~/.config/OrcaSlicer`), so Playback capture cannot work there; use Latest slice or open a file.

## Development

```
src/
  core.js        G-code parser and motion planner (no DOM; runs in node)
  app.js         the player: Three.js scene, timeline, HUD, G-code panel, options
  page.html      page layout and styles
  plugin.py      the OrcaSlicer plugin: Pages tab + slicing-pipeline capture step
  changelog.json single source for the version number and the changelog
build.py         assembles dist/orca_playback.py and dist/playback.html
test/            G-code generators, node tests, Playwright tests with a mock `orca` module
```

Build:

```
npm install          # three.js r147, used only at build time
python3 build.py     # writes dist/orca_playback.py and dist/playback.html
```

`dist/playback.html` is the same player as a standalone page: open it in a browser and drop a G-code file on it.

Test (needs node, Python 3 and `pip install playwright && playwright install chromium`):

```
test/run_all.sh
```

## Releasing

The version in the plugin header, the in-app changelog and the plugin's docstring all come from `src/changelog.json`.

1. Add the new version at the top of `src/changelog.json`, run `python3 build.py`, and commit (including `dist/orca_playback.py`).
2. Create a GitHub release with the tag `v<version>` (for example `v1.4.2`) and publish it.

Publishing the release runs [`.github/workflows/publish-orcacloud.yml`](.github/workflows/publish-orcacloud.yml), which builds the plugin and uploads it to Orca Cloud as `real_gcode_playback_any.py`. Orca Cloud uses the tag as the version (it must be higher than the published one) and the release notes as that version's changelog; leave the notes empty to use the entry from `src/changelog.json`. The workflow stops if the tag and `src/changelog.json` disagree.

To upload earlier versions too, open the **Actions** tab, pick **Publish to Orca Cloud** and click **Run workflow**. It uploads every version committed to `dist/orca_playback.py`, oldest first, each with its own changelog entry (or only the versions you list), and skips versions Orca Cloud already has.

One-time setup: in Orca Cloud open **Edit plugin → GitHub publishing**, enter `Chungchiyu/real-gcode-playback` and click **Connect**. No secrets are needed; the workflow signs in with a GitHub OIDC token.

## License

MIT, see [LICENSE](LICENSE). Bundles [three.js](https://threejs.org) r147 (MIT License, Copyright 2010-2022 Three.js Authors).
