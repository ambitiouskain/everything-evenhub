# -*- coding: utf-8 -*-
"""R1 Ring Sizer: parametric comfort insert for the Even R1 smart ring.

Run from Fusion: Utilities > Add-Ins > Scripts and Add-Ins > + (script from my
computer) > select the "R1RingSizer" folder > Run. A dialog asks for the sizes,
then a new design is filled with the insert (one body per size variant).

Shape: an eccentric C-shaped shim ("crescent"). Its inner circle is the target
finger size, shifted toward the sensor so that it touches the ring's own inner
surface at the bottom. The thick part sits on the back of the finger and the
bottom (sensor side) is left open, so the finger is pressed onto the sensor
instead of being held away from it. Optional lips hook over the ring's side
faces so the insert cannot slide out.

Coordinates: ring axis = +Z (the part prints flat on the bed, no supports),
+Y = top of the ring (back of the finger), -Y = sensor side (palm side).
"""

import math
import os
import traceback

import adsk.core
import adsk.fusion

# Defaults shown in the dialog (millimetres / degrees).
DEFAULTS = {
    'ring_id': 20.5,      # R1 inner diameter
    'ring_w': 6.0,        # R1 band width
    'finger_d': 16.6,     # 18.5 measured; fit tests: 18.9 hole too loose, ~16.4 stack snug
    'fit': 0.2,           # added to finger_d; final hole = finger_d + fit
    'grip': 0.2,          # diametral press fit of the insert inside the ring
    'bias': 100.0,        # % of the gap moved to the top (100 = finger touches sensor)
    'window': 90.0,       # minimum open angle at the bottom for the sensor
    'min_tip': 0.8,       # thinnest wall allowed at the tips of the C
    'lips': 1,            # 0 none, 1 one side, 2 both sides
    'lip_t': 0.6,         # lip thickness (along the ring axis)
    'lip_h': 0.8,         # how far the lip reaches over the ring's side face
    'lip_span': 120.0,    # angular length of each lip, centred on the top
    'edge_fillet': 0.45,  # rounding of the finger-side edges
    'variants': 1,        # number of sizes to generate side by side
    'step': 0.2,          # finger_d step between variants
}

AXIAL_CLEARANCE = 0.2   # total play between the two lips and the ring faces
EDGE_INSET = 0.2        # keeps lip-less edges just inside the ring faces
LIP_FILLET = 0.2
LIP_END_MARGIN = 10.0   # degrees kept between a lip end and the C tip

CMD_ID = 'evenR1RingSizerScript'
CMD_NAME = 'R1 Ring Sizer'

_app = None
_ui = None
_handlers = []
_inputs = {}


class LayoutError(Exception):
    pass


# ---------------------------------------------------------------------------
# Geometry (pure Python, millimetres and degrees, testable outside Fusion)
# ---------------------------------------------------------------------------

def _polar(r, phi_deg, cx=0.0, cy=0.0):
    """Point at radius r and angle phi measured clockwise from +Y."""
    a = math.radians(phi_deg)
    return (cx + r * math.sin(a), cy + r * math.cos(a))


def _cap_mid(p_out, p_in, tangent, bulge):
    return ((p_out[0] + p_in[0]) / 2.0 + tangent[0] * bulge,
            (p_out[1] + p_in[1]) / 2.0 + tangent[1] * bulge)


def compute_layout(p, x0=0.0):
    """Return the insert geometry for parameter dict p (mm / deg)."""
    warnings = []
    ring_r = p['ring_id'] / 2.0
    ro = ring_r + p['grip'] / 2.0
    target_d = p['finger_d'] + p['fit']
    ri = target_d / 2.0
    if ri > ring_r - 0.15:
        raise LayoutError('目标内径 {:.2f} mm 不小于戒指内径 {:.2f} mm，不需要垫片。'
                          .format(target_d, p['ring_id']))
    bias = max(0.0, min(100.0, p['bias'])) / 100.0
    e = (ring_r - ri) * bias

    def s_at(phi):
        a = math.radians(phi)
        return -e * math.cos(a) + math.sqrt(ri * ri - (e * math.sin(a)) ** 2)

    def t_at(phi):
        return ro - s_at(phi)

    t_min = p['min_tip']
    t_top = t_at(0.0)
    if t_top < t_min - 1e-6:
        raise LayoutError('最厚处只有 {:.2f} mm，小于最小壁厚 {:.2f} mm。'
                          '请减小最小壁厚或检查尺寸。'.format(t_top, t_min))

    # Angle where the wall thins down to t_min (thickness falls monotonically).
    if e < 1e-9:
        phi_t = 180.0
    else:
        s_t = ro - t_min
        c = (ri * ri - e * e - s_t * s_t) / (2.0 * s_t * e)
        phi_t = 180.0 if c <= -1.0 else math.degrees(math.acos(min(1.0, c)))
    phi_end = min(phi_t, 180.0 - p['window'] / 2.0)
    if phi_end <= 30.0:
        raise LayoutError('垫片太短（{:.0f}°），无法固定。'.format(2 * phi_end))
    span = 2.0 * phi_end
    if span < 200.0 and int(p['lips']) == 0:
        warnings.append('C 形包角只有 {:.0f}°（小于 200°），无侧唇时靠自身弹力夹持可能不够，'
                        '建议加侧唇或减小传感器窗口。'.format(span))
    t_end = t_at(phi_end)

    a_end = math.radians(phi_end)
    tan_r = (math.cos(a_end), -math.sin(a_end))   # away from the shim, right tip
    tan_l = (-math.cos(a_end), -math.sin(a_end))  # away from the shim, left tip
    outer = [_polar(ro, -phi_end, x0), _polar(ro, 0.0, x0), _polar(ro, phi_end, x0)]
    inner = [_polar(s_at(-phi_end), -phi_end, x0), (x0, ri - e),
             _polar(s_at(phi_end), phi_end, x0)]
    shim = {
        'outer': outer,
        'inner': inner,
        'cap_r': _cap_mid(outer[2], inner[2], tan_r, t_end / 2.0),
        'cap_l': _cap_mid(outer[0], inner[0], tan_l, t_end / 2.0),
    }

    lips = int(p['lips'])
    lip_t = p['lip_t']
    ring_w = p['ring_w']
    if lips >= 2:
        height = ring_w + AXIAL_CLEARANCE + 2.0 * lip_t
        lip_z = [(0.0, lip_t), (height - lip_t, height)]
    elif lips == 1:
        height = lip_t + ring_w - EDGE_INSET
        lip_z = [(0.0, lip_t)]
    else:
        height = ring_w - 2.0 * EDGE_INSET
        lip_z = []

    lip = None
    if lip_z:
        lip_half = min(p['lip_span'] / 2.0, phi_end - LIP_END_MARGIN)
        if lip_half < 15.0:
            raise LayoutError('侧唇太短，请减小传感器窗口或关闭侧唇。')
        r_out = ring_r + p['lip_h']
        r_in = ro - min(0.4, 0.5 * t_at(lip_half))
        bulge = (r_out - r_in) / 2.0
        a_l = math.radians(lip_half)
        lo = [_polar(r_out, -lip_half, x0), _polar(r_out, 0.0, x0), _polar(r_out, lip_half, x0)]
        li = [_polar(r_in, -lip_half, x0), _polar(r_in, 0.0, x0), _polar(r_in, lip_half, x0)]
        lip = {
            'outer': lo,
            'inner': li,
            'cap_r': _cap_mid(lo[2], li[2], (math.cos(a_l), -math.sin(a_l)), bulge),
            'cap_l': _cap_mid(lo[0], li[0], (-math.cos(a_l), -math.sin(a_l)), bulge),
            'r_out': r_out,
            'r_in': r_in,
            'half_angle': lip_half,
        }

    fillet = p['edge_fillet']
    max_fillet = min(0.6 * t_min, height / 2.0 - 0.5)
    if fillet > max_fillet:
        warnings.append('内边圆角 {:.2f} mm 过大，已改为 {:.2f} mm。'.format(fillet, max_fillet))
        fillet = max_fillet

    # Revolve cutters (profiles in the vertical plane x = x0, +Y side of each axis).
    hole_cut = None
    if fillet > 0.01:
        hole_cut = {
            'axis': [(x0, -e, -2.0), (x0, -e, height + 2.0)],
            'loops': [_hole_flare_loop(x0, -e, ri, fillet, height)],
        }
    lip_cut = None
    if lip and LIP_FILLET > 0:
        loops = []
        for z0, z1 in lip_z:
            loops.extend(_corner_loops(x0, lip['r_out'], LIP_FILLET, z0, z1))
        lip_cut = {'axis': [(x0, 0.0, -2.0), (x0, 0.0, height + 2.0)], 'loops': loops}

    return {
        'x0': x0,
        'ring_r': ring_r,
        'ro': ro,
        'ri': ri,
        'e': e,
        'target_d': target_d,
        'inner_center': (x0, -e),
        'phi_end': phi_end,
        'window': 360.0 - span,
        'span': span,
        't_top': t_top,
        't_side': t_at(90.0),
        't_end': t_end,
        'height': height,
        'lip_z': lip_z,
        'lip_t': lip_t,
        'shim': shim,
        'lip': lip,
        'edge_fillet': fillet,
        'hole_cut': hole_cut,
        'lip_cut': lip_cut,
        'warnings': warnings,
    }


_K = 1.0 / math.sqrt(2.0)


def _hole_flare_loop(x0, cy, ri, r, height):
    """Cutter around the hole axis: removes the convex inner edges at z=0 and z=height."""
    def pt(u, z):
        return (x0, cy + u, z)
    u0 = 1.0
    return [
        ('line', pt(u0, -1.0), pt(ri + r, -1.0)),
        ('line', pt(ri + r, -1.0), pt(ri + r, 0.0)),
        ('arc', pt(ri + r, 0.0), pt(ri + r - r * _K, r - r * _K), pt(ri, r)),
        # Between the two arcs the cutter steps 1 mm into the empty hole, so it never
        # shares the hole's cylindrical face (coincident faces upset booleans).
        ('line', pt(ri, r), pt(ri - 1.0, r)),
        ('line', pt(ri - 1.0, r), pt(ri - 1.0, height - r)),
        ('line', pt(ri - 1.0, height - r), pt(ri, height - r)),
        ('arc', pt(ri, height - r), pt(ri + r - r * _K, height - r + r * _K), pt(ri + r, height)),
        ('line', pt(ri + r, height), pt(ri + r, height + 1.0)),
        ('line', pt(ri + r, height + 1.0), pt(u0, height + 1.0)),
        ('line', pt(u0, height + 1.0), pt(u0, -1.0)),
    ]


def _corner_loops(x0, r_out, rf, z0, z1):
    """Two small cutters that round the outer edges of a lip spanning z0..z1."""
    def pt(u, z):
        return (x0, u, z)
    a = r_out - rf
    bottom = [
        ('line', pt(a, z0 - 1.0), pt(r_out + 1.0, z0 - 1.0)),
        ('line', pt(r_out + 1.0, z0 - 1.0), pt(r_out + 1.0, z0 + rf)),
        ('line', pt(r_out + 1.0, z0 + rf), pt(r_out, z0 + rf)),
        ('arc', pt(r_out, z0 + rf), pt(a + rf * _K, z0 + rf - rf * _K), pt(a, z0)),
        ('line', pt(a, z0), pt(a, z0 - 1.0)),
    ]
    top = [
        ('line', pt(a, z1 + 1.0), pt(r_out + 1.0, z1 + 1.0)),
        ('line', pt(r_out + 1.0, z1 + 1.0), pt(r_out + 1.0, z1 - rf)),
        ('line', pt(r_out + 1.0, z1 - rf), pt(r_out, z1 - rf)),
        ('arc', pt(r_out, z1 - rf), pt(a + rf * _K, z1 - rf + rf * _K), pt(a, z1)),
        ('line', pt(a, z1), pt(a, z1 + 1.0)),
    ]
    return [bottom, top]


def variant_finger_diameters(p):
    n = max(1, int(p['variants']))
    return [p['finger_d'] + (i - (n - 1) / 2.0) * p['step'] for i in range(n)]


# ---------------------------------------------------------------------------
# Fusion modelling
# ---------------------------------------------------------------------------

def _p3(x_mm, y_mm, z_mm):
    return adsk.core.Point3D.create(x_mm / 10.0, y_mm / 10.0, z_mm / 10.0)


def _draw_band(sketch, band, z_mm):
    """Closed loop: outer arc, right cap, inner arc, left cap (all 3-point arcs)."""
    def sp(pt):
        return sketch.modelToSketchSpace(_p3(pt[0], pt[1], z_mm))

    arcs = sketch.sketchCurves.sketchArcs
    o, i = band['outer'], band['inner']
    arcs.addByThreePoints(sp(o[0]), sp(o[1]), sp(o[2]))
    arcs.addByThreePoints(sp(o[2]), sp(band['cap_r']), sp(i[2]))
    arcs.addByThreePoints(sp(i[0]), sp(i[1]), sp(i[2]))
    arcs.addByThreePoints(sp(o[0]), sp(band['cap_l']), sp(i[0]))


def _largest_profile(sketch):
    best, best_area = None, -1.0
    for k in range(sketch.profiles.count):
        prof = sketch.profiles.item(k)
        area = prof.areaProperties().area
        if area > best_area:
            best, best_area = prof, area
    if best is None:
        raise LayoutError('草图没有生成封闭轮廓（sketch has no closed profile）。')
    return best


def _offset_plane(comp, base_plane, axis, offset_mm):
    """Plane parallel to base_plane at model coordinate offset_mm along axis 'x' or 'z'.

    The sign of the plane normal is read from the base plane, so the plane lands at
    the intended coordinate whichever way Fusion orients that normal.
    """
    if abs(offset_mm) < 1e-9:
        return base_plane
    normal = base_plane.geometry.normal
    component = normal.x if axis == 'x' else normal.z
    sign = 1.0 if component > 0 else -1.0
    planes = comp.constructionPlanes
    plane_input = planes.createInput()
    plane_input.setByOffset(base_plane, adsk.core.ValueInput.createByReal(sign * offset_mm / 10.0))
    plane = planes.add(plane_input)
    plane.isLightBulbOn = False
    return plane


def _draw_loops(sketch, loops):
    def sp(pt):
        return sketch.modelToSketchSpace(_p3(pt[0], pt[1], pt[2]))

    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    for loop in loops:
        for seg in loop:
            if seg[0] == 'line':
                lines.addByTwoPoints(sp(seg[1]), sp(seg[2]))
            else:
                arcs.addByThreePoints(sp(seg[1]), sp(seg[2]), sp(seg[3]))


def _revolve_cut(comp, body, plane, cut, name):
    """Revolve the cutter loops 360 deg about cut['axis'] and subtract them from body."""
    sketch = comp.sketches.add(plane)
    sketch.name = name
    _draw_loops(sketch, cut['loops'])
    a, b = cut['axis']
    axis = sketch.sketchCurves.sketchLines.addByTwoPoints(
        sketch.modelToSketchSpace(_p3(*a)), sketch.modelToSketchSpace(_p3(*b)))
    axis.isConstruction = True
    profiles = adsk.core.ObjectCollection.create()
    for k in range(sketch.profiles.count):
        profiles.add(sketch.profiles.item(k))
    if profiles.count != len(cut['loops']):
        raise LayoutError('{} 草图轮廓数量异常（{} 个，应为 {} 个）。'
                          .format(name, profiles.count, len(cut['loops'])))
    revolves = comp.features.revolveFeatures
    rev_input = revolves.createInput(profiles, axis,
                                     adsk.fusion.FeatureOperations.CutFeatureOperation)
    rev_input.setAngleExtent(False, adsk.core.ValueInput.createByReal(2.0 * math.pi))
    rev_input.participantBodies = [body]
    revolves.add(rev_input)


def build_insert(root, layout, name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = name
    extrudes = comp.features.extrudeFeatures

    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.name = 'shim'
    _draw_band(sketch, layout['shim'], 0.0)
    ext_input = extrudes.createInput(_largest_profile(sketch),
                                     adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(layout['height'] / 10.0))
    body = extrudes.add(ext_input).bodies.item(0)
    body.name = name

    for idx, (z0, z1) in enumerate(layout['lip_z']):
        mid = (z0 + z1) / 2.0
        lip_sketch = comp.sketches.add(_offset_plane(comp, comp.xYConstructionPlane, 'z', mid))
        lip_sketch.name = 'lip{}'.format(idx + 1)
        _draw_band(lip_sketch, layout['lip'], mid)
        lip_input = extrudes.createInput(_largest_profile(lip_sketch),
                                         adsk.fusion.FeatureOperations.JoinFeatureOperation)
        # Symmetric extent: independent of which way the sketch normal points.
        lip_input.setSymmetricExtent(adsk.core.ValueInput.createByReal((z1 - z0) / 10.0), True)
        lip_input.participantBodies = [body]
        extrudes.add(lip_input)

    # Rounded edges are carved with revolved cutters rather than fillets: the
    # fillets would have to stop at the tips of the C, which kernels often reject.
    if layout['hole_cut'] or layout['lip_cut']:
        side_plane = _offset_plane(comp, comp.yZConstructionPlane, 'x', layout['x0'])
        if layout['hole_cut']:
            _revolve_cut(comp, body, side_plane, layout['hole_cut'], 'edge_round')
        if layout['lip_cut']:
            _revolve_cut(comp, body, side_plane, layout['lip_cut'], 'lip_round')
    body = comp.bRepBodies.item(0)
    body.name = name
    return body


def _export_stl(design, body, folder, name):
    path = os.path.join(folder, name + '.stl')
    export_mgr = design.exportManager
    options = export_mgr.createSTLExportOptions(body, path)
    options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    export_mgr.execute(options)
    return path


def _read_params():
    def mm(key):
        return _inputs[key].value * 10.0

    def deg(key):
        return math.degrees(_inputs[key].value)

    return {
        'ring_id': mm('ring_id'),
        'ring_w': mm('ring_w'),
        'finger_d': mm('finger_d'),
        'fit': mm('fit'),
        'grip': mm('grip'),
        'bias': _inputs['bias'].value,
        'window': deg('window'),
        'min_tip': mm('min_tip'),
        'lips': 2 - _inputs['lips'].selectedItem.index,
        'lip_t': mm('lip_t'),
        'lip_h': mm('lip_h'),
        'lip_span': deg('lip_span'),
        'edge_fillet': mm('edge_fillet'),
        'variants': _inputs['variants'].value,
        'step': mm('step'),
        'export_stl': _inputs['export_stl'].value,
    }


def generate(params):
    design = adsk.fusion.Design.cast(_app.activeProduct)
    if not design:
        raise LayoutError('请在设计（Design）工作空间中运行。')
    root = design.rootComponent

    finger_ds = variant_finger_diameters(params)
    layouts = []
    for fd in finger_ds:
        p = dict(params)
        p['finger_d'] = fd
        layouts.append(compute_layout(p))
    pitch = 2.0 * max(l['lip']['r_out'] if l['lip'] else l['ro'] for l in layouts) + 6.0

    export_folder = None
    if params['export_stl']:
        dialog = _ui.createFolderDialog()
        dialog.title = '选择 STL 导出文件夹'
        if dialog.showDialog() == adsk.core.DialogResults.DialogOK:
            export_folder = dialog.folder

    lines = []
    warned = []
    for idx, fd in enumerate(finger_ds):
        p = dict(params)
        p['finger_d'] = fd
        layout = compute_layout(p, x0=idx * pitch)
        name = 'R1_sizer_{:.1f}'.format(layout['target_d'])
        body = build_insert(root, layout, name)
        lines.append('{}: 孔径 {:.2f} mm | 顶部 {:.2f} / 侧面 {:.2f} / 尖端 {:.2f} mm | '
                     '包角 {:.0f}°, 传感器窗口 {:.0f}° | 高 {:.2f} mm | 内边圆角 {:.2f} mm'
                     .format(name, layout['target_d'], layout['t_top'], layout['t_side'],
                             layout['t_end'], layout['span'], layout['window'],
                             layout['height'], layout['edge_fillet']))
        if export_folder:
            _export_stl(design, body, export_folder, name)
        for w in layout['warnings']:
            if w not in warned:
                warned.append(w)
    lines.extend('注意: ' + w for w in warned)

    _app.activeViewport.fit()
    if export_folder:
        lines.append('STL 已导出到: ' + export_folder)
    if len(finger_ds) > 1:
        lines.append('多个尺寸从左到右依次排列（X 正方向孔径递增）。')
    _ui.messageBox('\n'.join(lines), CMD_NAME)


# ---------------------------------------------------------------------------
# Command dialog
# ---------------------------------------------------------------------------

class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            cmd = args.command
            cmd.okButtonText = '生成'
            inputs = cmd.commandInputs
            d = DEFAULTS

            def length(key, label, value):
                _inputs[key] = inputs.addValueInput(
                    key, label, 'mm', adsk.core.ValueInput.createByString('{} mm'.format(value)))

            def angle(key, label, value):
                _inputs[key] = inputs.addValueInput(
                    key, label, 'deg', adsk.core.ValueInput.createByString('{} deg'.format(value)))

            inputs.addTextBoxCommandInput(
                'info', '',
                '偏心 C 形垫片：顶部最厚，底部（传感器侧）留空，把手指压向传感器。'
                '建议用 TPU 95A 打印，方便套过指关节。', 3, True)
            length('ring_id', '戒指内径 Ring ID', d['ring_id'])
            length('ring_w', '戒指宽度 Ring width', d['ring_w'])
            length('finger_d', '手指直径 Finger Ø', d['finger_d'])
            length('fit', '舒适余量 Fit allowance', d['fit'])
            _inputs['variants'] = inputs.addIntegerSpinnerCommandInput(
                'variants', '尺寸数量 Variants', 1, 5, 1, d['variants'])
            length('step', '尺寸步进 Variant step', d['step'])
            angle('window', '传感器窗口(最小) Sensor window', d['window'])
            length('min_tip', '最小壁厚 Min wall', d['min_tip'])
            _inputs['bias'] = inputs.addValueInput(
                'bias', '偏心 % (100=贴紧传感器)', '', adsk.core.ValueInput.createByReal(d['bias']))
            lips = inputs.addDropDownCommandInput(
                'lips', '侧唇 Lips', adsk.core.DropDownStyles.TextListDropDownStyle)
            lips.listItems.add('两侧 Both sides (TPU)', d['lips'] == 2, '')
            lips.listItems.add('单侧 One side', d['lips'] == 1, '')
            lips.listItems.add('无 None', d['lips'] == 0, '')
            _inputs['lips'] = lips
            length('lip_t', '侧唇厚度 Lip thickness', d['lip_t'])
            length('lip_h', '侧唇覆盖 Lip overlap', d['lip_h'])
            angle('lip_span', '侧唇长度 Lip span', d['lip_span'])
            length('grip', '夹紧过盈 Grip interference', d['grip'])
            length('edge_fillet', '内边圆角 Edge fillet', d['edge_fillet'])
            _inputs['export_stl'] = inputs.addBoolValueInput(
                'export_stl', '导出 STL Export STL', True, '', False)

            on_execute = _ExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)
            on_destroy = _DestroyHandler()
            cmd.destroy.add(on_destroy)
            _handlers.append(on_destroy)
        except Exception:
            _ui.messageBox('创建对话框失败:\n{}'.format(traceback.format_exc()))


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            generate(_read_params())
        except LayoutError as err:
            _ui.messageBox(str(err), CMD_NAME)
        except Exception:
            _ui.messageBox('生成失败:\n{}'.format(traceback.format_exc()), CMD_NAME)


class _DestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        adsk.terminate()


def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        # Work in a fresh design so the user's open document is never touched.
        _app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)

        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
        cmd_def = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID, CMD_NAME, 'Parametric comfort insert for the Even R1 ring')
        on_created = _CreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)
        cmd_def.execute()
        adsk.autoTerminate(False)
    except Exception:
        if _ui:
            _ui.messageBox('启动失败:\n{}'.format(traceback.format_exc()))


def stop(context):
    try:
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID) if _ui else None
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        pass
