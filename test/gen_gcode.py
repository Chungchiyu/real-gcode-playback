"""Generate synthetic but realistic Orca/Bambu-style G-code for tests.

  python gen_gcode.py bambu out.gcode   -> A1 mini flavour (; FEATURE:, ; CHANGE_LAYER, G2/G3, M620/T, header estimate)
  python gen_gcode.py marlin out.gcode  -> generic Orca flavour (;TYPE:, ;LAYER_CHANGE, config block at the end)
"""
import math
import sys

flavor, out = sys.argv[1], sys.argv[2]
bambu = flavor == "bambu"
L = []
w = L.append

E = 0.0
area = 0.42 * 0.2
fil_area = math.pi * (1.75 / 2) ** 2
pos = [90.0, 90.0, 0.0]
naive_t = 0.0


def g1(x=None, y=None, z=None, extrude=False, f=None, width=0.42, h=0.2):
    global E, naive_t
    nx = pos[0] if x is None else x
    ny = pos[1] if y is None else y
    nz = pos[2] if z is None else z
    d = math.dist(pos, (nx, ny, nz))
    parts = ["G1"]
    if x is not None: parts.append(f"X{nx:.3f}")
    if y is not None: parts.append(f"Y{ny:.3f}")
    if z is not None: parts.append(f"Z{nz:.3f}")
    if extrude and d > 0:
        de = d * width * h / fil_area
        parts.append(f"E{de:.5f}")
    if f: parts.append(f"F{f}")
    w(" ".join(parts))
    if f: g1.f = f
    naive_t += d / (g1.f / 60)
    pos[:] = [nx, ny, nz]


g1.f = 3000


def feature(name):
    w(f"; FEATURE: {name}" if bambu else f";TYPE:{name}")


def arc_circle(cx, cy, r, f):
    """full circle as two G3 half arcs starting at (cx+r, cy)"""
    global naive_t
    g1(cx + r, cy, f=30000)
    for (sx, sy, ex, ey) in ((cx + r, cy, cx - r, cy), (cx - r, cy, cx + r, cy)):
        de = math.pi * r * 0.42 * 0.2 / fil_area
        w(f"G3 X{ex:.3f} Y{ey:.3f} I{cx - sx:.3f} J{cy - sy:.3f} E{de:.5f} F{f}")
        naive_t += math.pi * r / (f / 60)
        pos[0], pos[1] = ex, ey


def retract():
    w("G1 E-.8 F1800")


def unretract():
    w("G1 E.8 F1800")


layers = 50
if bambu:
    w("; HEADER_BLOCK_START")
    w("; BambuStudio 02.04.00.70")
    w("; model printing time: @MODEL@; total estimated time: @TOTAL@")
    w("; total layer number: 50")
    w("; HEADER_BLOCK_END")
    w("; CONFIG_BLOCK_START")
cfg = {
    "printable_area": "0x0,180x0,180x180,0x180", "printable_height": "180",
    "printer_structure": "i3" if bambu else "corexy",
    "gcode_flavor": "marlin" if bambu else "marlin2",
    "machine_max_acceleration_x": "20000,20000", "machine_max_acceleration_y": "20000,20000",
    "machine_max_acceleration_z": "1500,1500", "machine_max_acceleration_e": "5000,5000",
    "machine_max_speed_x": "500,200", "machine_max_speed_y": "500,200", "machine_max_speed_z": "30,30",
    "machine_max_speed_e": "30,30", "machine_max_jerk_x": "9,9", "machine_max_jerk_y": "9,9",
    "machine_max_jerk_z": "5,5", "machine_max_jerk_e": "3,3", "default_acceleration": "6000",
    "travel_acceleration": "10000", "filament_diameter": "1.75,1.75", "nozzle_diameter": "0.4",
    "filament_colour": "#00AE42;#F72323", "filament_type": "PLA;PLA",
}
if bambu:
    for k, v in cfg.items():
        w(f"; {k} = {v}")
    w("; CONFIG_BLOCK_END")
    w("; EXECUTABLE_BLOCK_START")
w("M73 P0 R0")
w("M201 X20000 Y20000 Z1500 E5000")
w("M204 S6000" if bambu else "M204 P6000 T10000")
w("G28")
w("M190 S65")
w("M109 S220")
w("G90")
w("M83")
w("G1 X10 Y-0.5 Z0.3 F18000")
w("G1 X100 E12 F1500 ; prime line")
w("M400 S3")

tool = 0
for layer in range(layers):
    z = 0.2 * (layer + 1)
    if bambu:
        w("; CHANGE_LAYER")
        w(f"; Z_HEIGHT: {z:.2f}")
        w("; LAYER_HEIGHT: 0.2")
        w(f"; layer num/total_layer_count: {layer + 1}/{layers}")
        w(f"M73 L{layer + 1}")
    else:
        w(";LAYER_CHANGE")
        w(f";Z:{z:.2f}")
        w(";HEIGHT:0.2")
    retract()
    g1(z=z + 0.4, f=1200)
    g1(70, 90, f=30000)
    g1(z=z, f=1200)
    unretract()
    if layer == 25 and bambu:
        w("M620 S1A")
        w("M400")
        w("G1 X180 F18000")
        w("T1")
        tool = 1
        w("; FLUSH_START")
        w("G1 E23.7 F523")
        w("G1 E2 F50")
        w("; FLUSH_END")
        w("M621 S1A")
        g1(70, 90, f=30000)
    # outer wall: circle r=20 centred (90,90)
    feature("Outer wall")
    if bambu:
        arc_circle(90, 90, 20, 12000)
    else:
        n = 72
        g1(110, 90, f=30000)
        for k in range(1, n + 1):
            a = 2 * math.pi * k / n
            g1(90 + 20 * math.cos(a), 90 + 20 * math.sin(a), extrude=True, f=12000)
    # inner wall: square 30x30
    feature("Inner wall")
    g1(75.4, 75.4, f=30000)
    for (x, y) in ((104.6, 75.4), (104.6, 104.6), (75.4, 104.6), (75.4, 75.4)):
        g1(x, y, extrude=True, f=18000)
    # infill
    top = layer >= layers - 3 or layer < 3
    feature("Top surface" if layer >= layers - 3 else "Bottom surface" if layer < 3 else "Sparse infill")
    step = 0.42 if top else 3.0
    yy = 76.0
    flip = False
    g1(76.0, yy, f=30000)
    while yy < 104.0:
        g1(104.0 if not flip else 76.0, yy, extrude=True, f=15000 if not top else 9000)
        yy += step
        g1(y=yy, extrude=True, f=15000 if not top else 9000)
        flip = not flip
    if layer == 10 and not bambu:
        w("M600")

w("M400")
w("M104 S0")
w("G1 Z60 F600")
w("M73 P100 R0")

text = "\n".join(L) + "\n"
if not bambu:
    text += "; estimated printing time (normal mode) = @TOTAL@\n"
    text += "; CONFIG_BLOCK_START\n" + "".join(f"; {k} = {v}\n" for k, v in cfg.items()) + "; CONFIG_BLOCK_END\n"

# fake slicer estimate: naive time * 1.15 + 60s; M73 percent markers placed by naive cumulative time
total = naive_t * 1.15 + 60


def fmt(s):
    s = int(round(s))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return (f"{h}h " if h else "") + f"{m}m {sec}s"


text = text.replace("@TOTAL@", fmt(total)).replace("@MODEL@", fmt(total - 60))
# insert M73 P markers every ~2% of naive time
out_lines, acc_t, nextp = [], 0.0, 2
pos = [90.0, 90.0, 0.0]
f = 3000
import re
for line in text.split("\n"):
    m = re.match(r"G[0123] (.*)", line)
    if m:
        d = dict((t[0], float(t[1:])) for t in m.group(1).split() if t[0] in "XYZF" and len(t) > 1)
        if "F" in d: f = d["F"]
        np_ = [d.get("X", pos[0]), d.get("Y", pos[1]), d.get("Z", pos[2])]
        acc_t += math.dist(pos, np_) / (f / 60)
        pos = np_
        pct = acc_t / naive_t * 100
        while pct >= nextp and nextp < 100:
            out_lines.append(f"M73 P{nextp} R{int((total - total * nextp / 100) / 60)}")
            nextp += 2
    out_lines.append(line)
open(out, "w").write("\n".join(out_lines))
print(out, "naive", round(naive_t), "estimate", round(total))
