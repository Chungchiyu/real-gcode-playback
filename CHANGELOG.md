# Changelog

## v1.4.3 (2026-10-09)
- Fixed playback running far too fast in the first part of Bambu Lab prints with bed leveling (since 1.3.0)

## v1.4.2 (2026-10-09)
- Pausing when you click another tab now works in OrcaSlicer

## v1.4.1 (2026-10-09)
- Clearer setup instructions on the start screen

## v1.4.0 (2026-10-09)
- Custom playback speed, including slow motion (0.1×, 0.25×, 0.5× or any value)
- Option to keep playing when you leave the Playback tab

## v1.3.0 (2026-10-09)
- Print options: choose bed leveling, flow calibration, timelapse and the other printer flags in the G-code; blocks the printer would skip are not drawn or timed
- Bed leveling counts as 260 s, as in OrcaSlicer's estimate

## v1.2.1 (2026-10-09)
- G-code panel keeps the running line centred while playing
- G-code panel button moved to the front of the current line

## v1.2.0 (2026-10-09)
- G-code panel: expand the current-line readout to scroll through the whole file; it follows playback, and clicking a line jumps to that moment

## v1.1.1 (2026-10-09)
- Packaging aligned with the OrcaSlicer plugin rules for Orca Cloud upload

## v1.1.0 (2026-10-08)
- Opening the tab loads a new slice automatically when nothing is loaded, and asks before replacing one that is
- Playback pauses when you leave the tab
- Shading options: round lit lines, layer contrast, height shading, flat colours
- Hot end and gantry can be shown or hidden separately
- Playback controls centred in the bottom bar

## v1.0.0 (2026-10-08)
- Playback tab: real-time playback of the sliced G-code
- Motion planner with acceleration and cornering, synced to the slicer's time estimate
- Timeline with layer bands and filament change, pause and heating markers
- Colour by line type, actual speed, set speed, volumetric flow, layer time or filament
- Moving-bed view for bed slingers such as the A1 mini
- Loads the latest slice, or a .gcode / .gcode.3mf file
- Playback capture step for loading slices without permission prompts
