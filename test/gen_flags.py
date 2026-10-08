"""Make bambu_flags.gcode: bambu.gcode plus Bambu-style conditional blocks (bed leveling, flow
calibration, per-layer timelapse), with a slicer estimate that, like OrcaSlicer's, counts every block."""
src = open('bambu.gcode').read().split('\n')
start = '''M1002 judge_flag build_plate_detect_flag
M622 S1
G1 X90 Y170 F12000
M623
M1002 judge_flag g29_before_print_flag
M622 J1
M1002 gcode_claim_action : 1
G29 A1 X70 Y70 I40 J40
M400
M623
M1002 judge_flag g29_before_print_flag
M622 J0
G28 T145
G1 X10 Y10 F12000
M623
M1002 judge_flag extrude_cali_flag
M622 J1
G1 X10 Y5 Z0.3 F12000
G1 X170 Y5 E8 F3000
G1 X170 Y7 E0.2 F3000
G1 X10 Y7 E8 F3000
M1002 judge_last_extrude_cali_success
M622 J0
G1 X10 Y9 E0.2 F3000
G1 X170 Y9 E8 F3000
M623
M623'''.split('\n')
timelapse = '''M622.1 S1
M1002 judge_flag timelapse_record_flag
M622 J1
G92 E0
G1 Z12
G1 X0 Y90 F18000
G1 X-13.0 F3000
M400
M400 P300
G92 E0
G1 X0 F18000
M623'''.split('\n')
out = []
for line in src:
    out.append(line)
    if line.startswith('M109 S220'):
        out += start
    if line.startswith('M73 L'):
        out += timelapse
text = '\n'.join(out).replace('total estimated time: 4m 43s', 'total estimated time: 10m 13s', 1)
open('bambu_flags.gcode', 'w').write(text)
print('bambu_flags.gcode')
