"""Effective hole when two printed inserts are clipped together (one curled inside the other).

Usage: python stack_fit.py <hole_a> <hole_b>      e.g. python stack_fit.py 18.9 18.5
Prints the diameter of the largest finger that fits the stack. A single insert
about 0.3-0.5 mm larger than that feels like the stack minus the squeeze.
Requires: shapely >= 2.1.
"""
import sys, math, types
import shapely
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
adsk = types.ModuleType('adsk'); core = types.ModuleType('adsk.core'); fusion = types.ModuleType('adsk.fusion')
core.CommandCreatedEventHandler = object; core.CommandEventHandler = object
adsk.core, adsk.fusion = core, fusion
sys.modules.update({'adsk': adsk, 'adsk.core': core, 'adsk.fusion': fusion})
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'R1RingSizer'))
import R1RingSizer as M

def layout(hole):
    p = dict(M.DEFAULTS, lips=1, finger_d=hole - M.DEFAULTS['fit'])
    return M.compute_layout(p)

def thickness_fn(L):
    ro, ri, e = L['ro'], L['ri'], L['e']
    def t(phi):
        a = math.radians(phi)
        return ro - (-e * math.cos(a) + math.sqrt(ri * ri - (e * math.sin(a)) ** 2))
    return t

def band_polygon(cx, cy, r_outer, t, phi_end, scale=1.0, n=600):
    """Crescent hugging a circle of radius r_outer around (cx, cy); thickness t(phi/scale)."""
    pts_o, pts_i = [], []
    for k in range(n + 1):
        psi = -phi_end * scale + 2 * phi_end * scale * k / n
        a = math.radians(psi); th = t(psi / scale)
        pts_o.append((cx + r_outer * math.sin(a), cy + r_outer * math.cos(a)))
        pts_i.append((cx + (r_outer - th) * math.sin(a), cy + (r_outer - th) * math.cos(a)))
    return Polygon(pts_o + pts_i[::-1]).buffer(0)

ring = Point(0, 0).buffer(10.25, 1024)
a, b = (float(v) for v in sys.argv[1:3])
for outer_hole, inner_hole in ((a, b), (b, a)):
    Lo, Li = layout(outer_hole), layout(inner_hole)
    outer = band_polygon(0, 0, Lo['ro'], thickness_fn(Lo), Lo['phi_end'])
    # inner insert curled into the outer insert's hole: keep outer-surface arc length
    R2, c2 = Lo['ri'], (0.0, -Lo['e'])
    scale = Li['ro'] / R2
    inner = band_polygon(c2[0], c2[1], R2, thickness_fn(Li), Li['phi_end'], scale=scale)
    free = ring.difference(unary_union([outer, inner]))
    mic = shapely.maximum_inscribed_circle(free, tolerance=0.001)
    c = mic.coords[0]; d = 2 * math.dist(mic.coords[0], mic.coords[1])
    top = 10.25 - c[1] - d / 2  # material above the circle
    print('outer %.1f + inner %.1f (inner wraps %.0f deg): effective hole D=%.2f mm, centre y=%.2f, '
          'stack at top %.2f mm, stack at side %.2f mm'
          % (outer_hole, inner_hole, 2 * Li['phi_end'] * scale, d, c[1],
             thickness_fn(Lo)(0) + thickness_fn(Li)(0), thickness_fn(Lo)(90) + thickness_fn(Li)(90 / scale)))
