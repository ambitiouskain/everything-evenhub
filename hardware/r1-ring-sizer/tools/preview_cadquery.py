"""Rebuild the R1 sizer outside Fusion (CadQuery) to check geometry and export STLs.

Uses the same compute_layout() as the Fusion script, so the numbers match.
Usage: python preview_cadquery.py <out_dir> [finger_d ...]
Requires: cadquery.
"""

import math
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.join(os.path.dirname(HERE), 'R1RingSizer')


def _load_layout_module():
    # Stub just enough of the Fusion API for the module to import.
    adsk = types.ModuleType('adsk')
    core = types.ModuleType('adsk.core')
    fusion = types.ModuleType('adsk.fusion')
    core.CommandCreatedEventHandler = object
    core.CommandEventHandler = object
    adsk.core, adsk.fusion = core, fusion
    sys.modules.update({'adsk': adsk, 'adsk.core': core, 'adsk.fusion': fusion})
    sys.path.insert(0, SCRIPT_DIR)
    import R1RingSizer
    return R1RingSizer


def band_wire(cq, band, z):
    o, i = band['outer'], band['inner']
    return (cq.Workplane('XY', origin=(0, 0, z))
            .moveTo(*o[0]).threePointArc(o[1], o[2])
            .threePointArc(band['cap_r'], i[2])
            .threePointArc(i[1], i[0])
            .threePointArc(band['cap_l'], o[0])
            .close())


def revolve_cut(cq, cut):
    solids = []
    for loop in cut['loops']:
        edges = []
        for seg in loop:
            pts = [cq.Vector(*pt) for pt in seg[1:]]
            if seg[0] == 'line':
                edges.append(cq.Edge.makeLine(*pts))
            else:
                edges.append(cq.Edge.makeThreePointArc(*pts))
        wire = cq.Wire.assembleEdges(edges)
        solids.append(cq.Solid.revolve(wire, [], 360.0, cut['axis'][0], cut['axis'][1]))
    return solids


def build(cq, layout):
    """Same feature order as build_insert() in the Fusion script."""
    solid = band_wire(cq, layout['shim'], 0.0).extrude(layout['height']).val()
    for z0, z1 in layout['lip_z']:
        lip = band_wire(cq, layout['lip'], z0).extrude(z1 - z0).val()
        solid = solid.fuse(lip).clean()
    for key in ('hole_cut', 'lip_cut'):
        if layout[key]:
            for tool in revolve_cut(cq, layout[key]):
                solid = solid.cut(tool).clean()
    return solid


def main():
    import cadquery as cq
    mod = _load_layout_module()
    out = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.makedirs(out, exist_ok=True)
    fingers = [float(v) for v in sys.argv[2:]] or [mod.DEFAULTS['finger_d']]
    for fd in fingers:
        p = dict(mod.DEFAULTS)
        p['finger_d'] = fd
        layout = mod.compute_layout(p)
        solid = build(cq, layout)
        assert solid.isValid(), 'invalid solid'
        name = 'R1_sizer_{:.1f}'.format(layout['target_d'])
        cq.exporters.export(cq.Workplane().add(solid), os.path.join(out, name + '.stl'),
                            tolerance=0.02, angularTolerance=0.1)
        print(name, {k: round(v, 3) for k, v in layout.items() if isinstance(v, float)},
              'warnings:', layout['warnings'])


if __name__ == '__main__':
    main()
