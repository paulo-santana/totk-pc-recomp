# Adapted from MacNativeGames games/totk/scripts/make_button_icons.py @ 933b6a0 (MIT, Copyright (c) 2026
# MacNativeGames contributors).
"""Xbox, PlayStation and keyboard-and-mouse button icons for the game's prompts, drawn on the player's machine for
tools/make_romfs_patches.py --prompts.
The outlines are our own shapes with letters cut out of them in the game's own text fonts: nothing of the game is in
the repository.

Every prompt except the button guide in play is text in the button font, scft/External.bfotf of each
Font/Font*.Nin_NX_NVN.bfarc.zs: private-use code points from U+E040 (A, B, X, Y, then L, R, ZL, ZR, the d-pad, Plus and
Minus, the sticks). A .bfotf is an OpenType (CFF) font after an 8-byte header; from offset 4 on, every byte is XORed
with a 4-byte key, which the size in the header's second word gives away (bfotf_decode). redraw_font draws the shoulder
buttons, the triggers, Plus, Minus and the d-pad as an Xbox controller names them (LB RB, LT RT, Menu and View, a
cross), the face buttons as the PlayStation shapes (○ × △ □) with L1 R1 L2 R2, Options and Share, or every button as
the key or mouse button the keyboard presses it with (pc_icons), can swap the glyphs of the face buttons (A with B, X
with Y), and has fontTools write the font again. The archive then grows by a kilobyte or two, more than the game's
resource size table allows it: grow_restbl raises those entries (without it the game stops at start, MacNativeGames
found).

The button guide in play (bottom right) draws its buttons, L and ZL among them, from images of the common layout
archive instead (timg/__Combined.bntx, Nt_KeyTexL_00 and Nt_KeyTexZL_00): bntx_redraw paints the same icons into them,
the size unchanged. The Xbox prompts redraw L and ZL, the PlayStation prompts the face buttons and L and ZL, the
keyboard and mouse ones every image (PC_HUD_TEXTURES: A, B, X, Y, L, ZL and the stick's two) with the keys of pc_binds. The font's glyphs use pc_binds(text=True): a text prompt
shows Y as T, the button guide the left mouse button. Prompts drawn as fixed images (some tutorial animations) keep the
Switch icons.

Needs fontTools (tools/requirements-installer.txt, tools/requirements-py314.txt).
"""
import functools
import io
import math
import os
import struct
import zlib

from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FONT = 'scft/External.bfotf'
# The letters on the keys come from the text fonts of the default archive; the regional archives lack them.
TEXT_ARCHIVE = 'Font/Font.Nin_NX_NVN.bfarc.zs'
TEXT_FONTS = ('scft/ninP_RodinNTLG-B_DH_003_subset.bfotf', 'scft/nintendo_NTLG-DB_DH_002.bfotf')
# The button guide's images and the glyph each one shows.
HUD_TEXTURES = {'Nt_KeyTexL_00': 0xE044, 'Nt_KeyTexZL_00': 0xE046}


def xor(data, key):
    """data with byte i XORed with key[i % 4]."""
    pad = (key * (len(data) // 4 + 1))[:len(data)]
    return (int.from_bytes(data, 'little') ^ int.from_bytes(pad, 'little')).to_bytes(len(data), 'little')


def bfotf_decode(blob):
    """(OpenType font, key) of a .bfotf (the module docstring). The font fills the rest of the file."""
    key = xor(blob[4:8], struct.pack('>I', len(blob) - 8))
    otf = xor(blob[8:], key)
    assert otf[:4] == b'OTTO', 'not a CFF OpenType font'
    return otf, key


def bfotf_encode(otf, key, head):
    """The .bfotf of otf: head (the original's first word) and the size, the rest XORed with key as bfotf_decode reads
    it. The size field holds the whole font, so its length has to be a multiple of 4 (fontTools pads its tables)."""
    assert len(otf) % 4 == 0, len(otf)
    return head[:4] + xor(struct.pack('>I', len(otf)) + otf, key)


# ---- drawing, in units of the font's 1000-unit em; the round A/B/X/Y icons fill y 20..585
Y0, Y1 = 20, 585
CY, R = (Y0 + Y1) / 2, (Y1 - Y0) / 2
K = 0.5523   # control point distance of a quarter circle drawn with one cubic curve, per unit of radius


class Glyphs:
    """Outlines of letters from the game's own text fonts, drawn as holes in a shape."""
    def __init__(self, fonts):
        self.fonts = fonts

    def outline(self, ch):
        for font in self.fonts:
            cmap = font.getBestCmap()
            if ord(ch) in cmap:
                glyphs = font.getGlyphSet(); g = glyphs[cmap[ord(ch)]]
                rec = RecordingPen(); g.draw(rec); box = BoundsPen(glyphs); g.draw(box)
                return rec, box.bounds, font['head'].unitsPerEm, g.width
        raise KeyError(f'no text font has {ch!r}')

    def hole(self, pen, text, cx, cy, cap, max_width):
        """text centred on (cx, cy), at most cap high and max_width wide, its contours reversed so they cut holes."""
        parts, x, ink = [], 0.0, [1e9, 1e9, -1e9, -1e9]
        for ch in text:
            rec, b, upm, advance = self.outline(ch); k = 1000 / upm
            parts.append((rec, k, x))
            ink = [min(ink[0], x + b[0] * k), min(ink[1], b[1] * k), max(ink[2], x + b[2] * k), max(ink[3], b[3] * k)]
            x += advance * k * 0.96
        width, height = ink[2] - ink[0], ink[3] - ink[1]
        scale = min(cap / height, max_width / width)
        ox, oy = cx - (ink[0] + width / 2) * scale, cy - (ink[1] + height / 2) * scale
        reverse = ReverseContourPen(pen)
        for rec, k, x in parts:
            rec.replay(TransformPen(reverse, (scale * k, 0, 0, scale * k, ox + x * scale, oy)))


def text_glyphs(blobs):
    """Glyphs over the text fonts in blobs (.bfotf files), the first that has a letter giving it."""
    return Glyphs([TTFont(io.BytesIO(bfotf_decode(blob)[0])) for blob in blobs])


def circle(pen, cx, cy, r):
    k = K * r
    pen.moveTo((cx + r, cy))
    pen.curveTo((cx + r, cy + k), (cx + k, cy + r), (cx, cy + r))
    pen.curveTo((cx - k, cy + r), (cx - r, cy + k), (cx - r, cy))
    pen.curveTo((cx - r, cy - k), (cx - k, cy - r), (cx, cy - r))
    pen.curveTo((cx + k, cy - r), (cx + r, cy - k), (cx + r, cy))
    pen.closePath()


def rounded(pen, x0, y0, x1, y1, bottom, top=None):
    """Counter-clockwise rounded rectangle (bottom and top corner radii)."""
    top = bottom if top is None else top
    kb, kt = K * bottom, K * top
    pen.moveTo((x0 + bottom, y0)); pen.lineTo((x1 - bottom, y0))
    pen.curveTo((x1 - bottom + kb, y0), (x1, y0 + bottom - kb), (x1, y0 + bottom)); pen.lineTo((x1, y1 - top))
    pen.curveTo((x1, y1 - top + kt), (x1 - top + kt, y1), (x1 - top, y1)); pen.lineTo((x0 + top, y1))
    pen.curveTo((x0 + top - kt, y1), (x0, y1 - top + kt), (x0, y1 - top)); pen.lineTo((x0, y0 + bottom))
    pen.curveTo((x0, y0 + bottom - kb), (x0 + bottom - kb, y0), (x0 + bottom, y0)); pen.closePath()


def polygon(pen, points):
    pen.moveTo(points[0])
    for p in points[1:]:
        pen.lineTo(p)
    pen.closePath()


def bumper(g, label, advance=820):
    """A shoulder button: a rounded key with its label cut out."""
    def draw(pen):
        rounded(pen, 40, Y0 + 70, advance - 40, Y1 - 70, 70, 150); g.hole(pen, label, advance / 2, CY, 230, advance - 200)
    return advance, draw


def trigger(g, label, advance=760):
    """A trigger: a taller key with its label cut out."""
    def draw(pen):
        rounded(pen, 60, Y0, advance - 60, Y1, 60, 230); g.hole(pen, label, advance / 2, CY - 20, 230, advance - 220)
    return advance, draw


def menu_key(advance=640):   # three bars, as on the Menu button
    def draw(pen):
        circle(pen, advance / 2, CY, R); reverse = ReverseContourPen(pen)
        for dy in (-115, 0, 115):
            rounded(reverse, advance / 2 - 150, CY + dy - 38, advance / 2 + 150, CY + dy + 38, 38)
    return advance, draw


def view_key(advance=640):   # two overlapping windows, as on the View button
    def draw(pen):
        circle(pen, advance / 2, CY, R); reverse = ReverseContourPen(pen); s = 150
        rounded(reverse, advance / 2 - s - 15, CY + 15, advance / 2 - 15, CY + s + 15, 16)
        rounded(reverse, advance / 2 + 15, CY - s - 15, advance / 2 + s + 15, CY - 15, 16)
    return advance, draw


def dpad_key(*lit, advance=640):   # a cross with an arrow cut into each direction the prompt means
    def draw(pen):
        cx, length, arm = advance / 2, R, R * 0.40
        polygon(pen, [(cx + length, CY - arm), (cx + length, CY + arm), (cx + arm, CY + arm), (cx + arm, CY + length),
                      (cx - arm, CY + length), (cx - arm, CY + arm), (cx - length, CY + arm), (cx - length, CY - arm),
                      (cx - arm, CY - arm), (cx - arm, CY - length), (cx + arm, CY - length), (cx + arm, CY - arm)])
        m, t, h = (length + arm) / 2, arm * 0.72, arm * 0.80   # arm centre, half base and height of the arrow
        heads = {'up': [(cx - t, CY + m - h / 2), (cx, CY + m + h / 2), (cx + t, CY + m - h / 2)],
                 'down': [(cx + t, CY - m + h / 2), (cx, CY - m - h / 2), (cx - t, CY - m + h / 2)],
                 'left': [(cx - m + h / 2, CY - t), (cx - m - h / 2, CY), (cx - m + h / 2, CY + t)],
                 'right': [(cx + m - h / 2, CY + t), (cx + m + h / 2, CY), (cx + m - h / 2, CY - t)]}
        for d in lit:
            polygon(pen, heads[d])   # already clockwise: a hole
    return advance, draw


def xbox_icons(g):
    """Code point -> (advance, draw(pen)) for the buttons an Xbox controller names differently from a Switch: L R = LB
    RB, ZL ZR = LT RT, Plus and Minus = Menu and View, the d-pad as a cross. g: Glyphs for the letters. The face
    buttons keep the game's own glyphs (redraw_font swaps them for the Nintendo layout)."""
    return {
        0xE044: bumper(g, 'LB'), 0xE045: bumper(g, 'RB'), 0xE046: trigger(g, 'LT'), 0xE047: trigger(g, 'RT'),
        0xE04B: menu_key(), 0xE04C: view_key(),
        0xE049: dpad_key('up', 'down', 'left', 'right'), 0xE060: dpad_key('up'), 0xE061: dpad_key('down'),
        0xE062: dpad_key('left'), 0xE063: dpad_key('right'), 0xE064: dpad_key('up', 'down'),
        0xE065: dpad_key('left', 'right'),
    }


# ---- PlayStation prompts (--prompts playstation, playstation-xbox): the shapes on a PlayStation pad, in the same
# filled-shape style. The game's text fonts have ○ U+25CB, × U+00D7, △ U+25B3 and □ U+25A1, so the diamond's letters
# become those characters (make_romfs_patches.py pane_letters). The face buttons are the shapes; the shoulders and
# triggers carry L1/R1/L2/R2; Plus and Minus show Options (three bars) and Share (a box with an arrow).
PS_FACE = {
    'nintendo': {'A': '○', 'B': '×', 'X': '△', 'Y': '□'},   # A east, B south, X north, Y west
    'xbox': {'A': '×', 'B': '○', 'X': '□', 'Y': '△'},       # A south, B east, X west, Y north
}
PS_HUD_TEXTURES = {'Nt_KeyTexA_00': 0xE040, 'Nt_KeyTexB_00': 0xE041, 'Nt_KeyTexX_00': 0xE042,
                   'Nt_KeyTexY_00': 0xE043, 'Nt_KeyTexL_00': 0xE044, 'Nt_KeyTexZL_00': 0xE046}


def ps_shape(shape, advance):
    """The filled outline of a PlayStation face button (○ × △ □) in the font's 1000-unit em, centred on the glyph's
    advance. The ring, square and triangle are outlines about a tenth of their size wide, as on the controller; the
    cross is a thick X."""
    cx, cy = advance / 2, CY
    if shape == '○':
        def draw(pen):
            circle(pen, cx, cy, R)
            circle(ReverseContourPen(pen), cx, cy, R * 0.81)
    elif shape == '×':
        def draw(pen):
            l, w = 270.0, 55.0
            polygon(pen, [(cx - l, cy - l + w), (cx - l + w, cy - l), (cx, cy - w), (cx + l - w, cy - l),
                          (cx + l, cy - l + w), (cx + w, cy), (cx + l, cy + l - w), (cx + l - w, cy + l),
                          (cx, cy + w), (cx - l + w, cy + l), (cx - l, cy + l - w), (cx - w, cy)])
    elif shape == '△':
        def draw(pen):
            polygon(pen, [(cx - 280, cy - 270), (cx + 280, cy - 270), (cx, cy + 270)])
            polygon(ReverseContourPen(pen), [(cx - 215, cy - 205), (cx + 215, cy - 205), (cx, cy + 205)])
    elif shape == '□':
        def draw(pen):
            polygon(pen, [(cx - 270, cy - 270), (cx + 270, cy - 270), (cx + 270, cy + 270), (cx - 270, cy + 270)])
            polygon(ReverseContourPen(pen), [(cx - 216, cy - 216), (cx + 216, cy - 216), (cx + 216, cy + 216),
                                             (cx - 216, cy + 216)])
    else:
        raise ValueError(f'no PlayStation shape {shape!r}')
    return draw


def share_key(advance=640):   # a box with an arrow, as on the Share button
    def draw(pen):
        cx = advance / 2
        circle(pen, cx, CY, R)
        reverse = ReverseContourPen(pen)
        rounded(reverse, cx - 150, CY - 150, cx + 60, CY + 40, 20)
        polygon(reverse, [(cx - 15, CY + 10), (cx + 15, CY + 10), (cx + 15, CY + 140), (cx - 15, CY + 140)])
        polygon(reverse, [(cx, CY + 205), (cx + 70, CY + 120), (cx - 70, CY + 120)])
    return advance, draw


def playstation_icons(g, adv, layout='nintendo'):
    """Code point -> (advance, draw(pen)) for the PlayStation prompts: the face buttons as ○ × △ □ on the button the
    pad layout presses, L1 R1 L2 R2, Plus and Minus as Options and Share, and the d-pad cross. g: Glyphs for the
    labels; adv: the game's advance of each glyph (font_advances), which each drawing keeps."""
    face = PS_FACE[layout]
    icons = {cp: (adv[cp], ps_shape(face[b], adv[cp]))
             for b, cp in (('A', 0xE040), ('B', 0xE041), ('X', 0xE042), ('Y', 0xE043))}
    icons.update({
        0xE044: bumper(g, 'L1', adv[0xE044]), 0xE045: bumper(g, 'R1', adv[0xE045]),
        0xE046: trigger(g, 'L2', adv[0xE046]), 0xE047: trigger(g, 'R2', adv[0xE047]),
        0xE04B: menu_key(adv[0xE04B]), 0xE04C: share_key(adv[0xE04C]),
        0xE049: dpad_key('up', 'down', 'left', 'right', advance=adv[0xE049]),
    })
    for cp, lit in ((0xE060, ('up',)), (0xE061, ('down',)), (0xE062, ('left',)), (0xE063, ('right',)),
                    (0xE064, ('up', 'down')), (0xE065, ('left', 'right'))):
        icons[cp] = dpad_key(*lit, advance=adv[cp])
    return icons


# ---- keyboard and mouse prompts (--prompts pc): every button the keyboard drives, drawn as the key or mouse button
# bound to it, in the same filled-shape style. Each glyph keeps the advance of the game's own (a wider glyph runs into
# the text of a right-aligned guide).
# The keyboard defaults of runtime/input_map.c (input_map_reset; the totk.ini bind_ lines apply on top, pc_binds). The
# right stick is the camera, which the mouse drives; SHAKE is the key that shakes it (the mouse never does).
PC_BINDS = {
    'A': 'e', 'B': 'lshift', 'X': 'space', 'Y': 'mouse_l', 'L': 'q', 'R': 'r', 'ZL': 'mouse_r', 'ZR': 'f',
    'PLUS': 'tab', 'MINUS': 'm', 'LEFT': '1', 'UP': '2', 'RIGHT': '3', 'DOWN': '4', 'LCLICK': 'lctrl', 'RCLICK': 'c',
    'LSTICK_UP': 'w', 'LSTICK_LEFT': 'a', 'LSTICK_DOWN': 's', 'LSTICK_RIGHT': 'd', 'SHAKE': 'g',
}
# What a key shows: its letter, a symbol or a short name (key names as in totk.ini; the rest show their name).
PC_LABELS = {
    'lshift': 'SHIFT', 'rshift': 'SHIFT', 'lctrl': 'CTRL', 'rctrl': 'CTRL', 'lalt': 'ALT', 'tab': 'TAB',
    'enter': 'ENT', 'backspace': 'BKSP', 'capslock': 'CAPS', 'insert': 'INS', 'delete': 'DEL', 'home': 'HOME',
    'end': 'END', 'pageup': 'PGUP', 'pagedown': 'PGDN', 'up': '↑', 'down': '↓', 'left': '←',
    'right': '→', 'num_add': '+', 'num_sub': '-', 'num_mul': '*', 'num_div': '/', 'num_decimal': '.',
    'minus': '-', 'equals': '=', 'lbracket': '[', 'rbracket': ']', 'semicolon': ';', 'apostrophe': "'", 'comma': ',',
    'period': '.', 'slash': '/', 'backslash': '\\', 'grave': '`', 'mouse_x1': 'M4', 'mouse_x2': 'M5',
}
# The one-letter panes around the action prompt (T_A_00 ...) are in the Normal font (Rodin B and Symbol): one character
# of it per key.
PC_LETTER_LABELS = {'lshift': '↑', 'rshift': '↑', 'space': '▬', 'mouse_l': 'L', 'mouse_r': 'R',
                    'mouse_m': 'M', 'lctrl': 'C', 'rctrl': 'C', 'tab': 'T'}
# The button guide's images in the pc style: every symbol mask of the action prompt. In the 1.4.3 Common archive
# LSt_00 shows the left stick tilted up (as U+E052) and LSt_01 the left stick (as U+E05E).
PC_HUD_TEXTURES = {'Nt_KeyTexA_00': 0xE040, 'Nt_KeyTexB_00': 0xE041, 'Nt_KeyTexX_00': 0xE042, 'Nt_KeyTexY_00': 0xE043,
                   'Nt_KeyTexL_00': 0xE044, 'Nt_KeyTexZL_00': 0xE046, 'Nt_KeyTexLSt_00': 0xE052,
                   'Nt_KeyTexLSt_01': 0xE05E}
PC_MOUSE = ('mouse_l', 'mouse_r', 'mouse_m')
# The text prompts (the button font: the menus' guides, the dialogue log's) show Y as T, the key runtime/input_map.c
# binds next to the left mouse button: while a game menu has the pointer the left button is that menu's A
# (runtime/menu_cursor.c), and T presses Y everywhere. The button guide in play and the action prompt keep the left
# button (PC_BINDS), which attacks there.
PC_TEXT_KEYS = {'Y': 't'}


def pc_binds(ini_text=None, text=False):
    """PC_BINDS with the first key of each bind_<action> line of a totk.ini text over it (a line without a key entry,
    or with key:default, keeps the default). text: the binds the button font is drawn with, where a button of
    PC_TEXT_KEYS shows its first key that is not a mouse button (PC_TEXT_KEYS's without a line)."""
    binds = dict(PC_BINDS, **(PC_TEXT_KEYS if text else {}))
    for line in (ini_text or '').splitlines():
        line = line.split('#')[0].split(';')[0].strip()
        if not line.lower().startswith('bind_') or '=' not in line:
            continue
        action, value = (s.strip() for s in line.split('=', 1))
        keys = [e.strip()[4:].strip().lower() for e in value.split(',') if e.strip().lower().startswith('key:')]
        keys = [k for k in keys if k != 'default']
        button = action[5:].upper()
        if text and button in PC_TEXT_KEYS:
            keys = [k for k in keys if not k.startswith('mouse_')] or keys
        if keys and button in binds:
            binds[button] = keys[0]
    return binds


def font_advances(blob):
    """Code point -> advance of every glyph of the button font (a .bfotf)."""
    font = TTFont(io.BytesIO(bfotf_decode(blob)[0]))
    return {cp: font['hmtx'][name][0] for cp, name in font.getBestCmap().items()}


def pc_letter(key):
    """The one character the panes around the action prompt show for key."""
    if key in PC_LETTER_LABELS:
        return PC_LETTER_LABELS[key]
    return PC_LABELS.get(key, key.upper())[0]


def pc_icons(g, adv, binds=PC_BINDS):
    """Code point -> (advance, draw(pen)) for every button glyph but Home and Capture, drawn as the key or mouse button
    binds puts on it. g: Glyphs for the key labels; adv: the game's advance of each glyph (font_advances), which each
    drawing keeps."""
    def mouse_body(pen, cx, y0, y1, lit=None):
        """A mouse seen from above; lit ('l', 'r', 'm' or None) its pressed button, filled, the others hollow."""
        h = y1 - y0; r = h * 0.33; t = h * 0.07; gap = h * 0.035
        x0, x1, mid = cx - r, cx + r, y0 + h * 0.52
        rounded(pen, x0, y0, x1, y1, r * 0.9, r)
        reverse = ReverseContourPen(pen)   # holes; they never overlap each other or leave the body
        ri = r - t
        if lit in ('l', 'r'):   # the seams around the pressed button
            sx0, sx1 = (x0 + t, cx - gap) if lit == 'l' else (cx + gap, x1 - t)
            polygon(reverse, [(sx0, mid - gap), (sx1, mid - gap), (sx1, mid + gap), (sx0, mid + gap)])
            polygon(reverse, [(cx - gap, mid + gap), (cx + gap, mid + gap), (cx + gap, y1 - t), (cx - gap, y1 - t)])
        if lit != 'l':   # hollow left button, its outer top corner following the body
            ix0, ix1 = x0 + t, cx - gap
            reverse.moveTo((ix1, mid + gap)); reverse.lineTo((ix1, y1 - t)); reverse.lineTo((ix0 + ri, y1 - t))
            reverse.curveTo((ix0 + ri - K * ri, y1 - t), (ix0, y1 - t - ri + K * ri), (ix0, y1 - t - ri))
            reverse.lineTo((ix0, mid + gap)); reverse.closePath()
        if lit != 'r':
            ix0, ix1 = cx + gap, x1 - t
            reverse.moveTo((ix0, mid + gap)); reverse.lineTo((ix1, mid + gap)); reverse.lineTo((ix1, y1 - t - ri))
            reverse.curveTo((ix1, y1 - t - ri + K * ri), (ix1 - ri + K * ri, y1 - t), (ix1 - ri, y1 - t))
            reverse.lineTo((ix0, y1 - t)); reverse.closePath()
        if lit == 'm':   # the wheel, filled over the gap between the hollow buttons
            rounded(pen, cx - h * 0.06, mid + h * 0.12, cx + h * 0.06, mid + h * 0.36, h * 0.06)

    def key_cap(pen, x0, y0, x1, y1, key):
        """A key: a rounded square with its label cut out; a mouse button draws the mouse."""
        if key in PC_MOUSE:
            mouse_body(pen, (x0 + x1) / 2, y0, y1, key[6:])
            return
        w, h = x1 - x0, y1 - y0
        rounded(pen, x0, y0, x1, y1, min(w, h) * 0.18)
        if key == 'space':   # an open bracket lying on its back
            t = h * 0.09
            bx0, bx1, by0, by1 = x0 + w * 0.22, x1 - w * 0.22, y0 + h * 0.36, y0 + h * 0.60
            polygon(ReverseContourPen(pen), [(bx0, by0), (bx1, by0), (bx1, by1), (bx1 - t, by1), (bx1 - t, by0 + t),
                                             (bx0 + t, by0 + t), (bx0 + t, by1), (bx0, by1)])
            return
        if key in ('lshift', 'rshift'):   # a solid arrow and the name under it: the arrow alone read as a direction
            cx, ab, at, hw, sw = (x0 + x1) / 2, y0 + h * 0.46, y0 + h * 0.86, w * 0.20, w * 0.09
            neck = ab + h * 0.18
            polygon(ReverseContourPen(pen), [(cx - sw, ab), (cx + sw, ab), (cx + sw, neck), (cx + hw, neck), (cx, at),
                                             (cx - hw, neck), (cx - sw, neck)])
            g.hole(pen, 'SHIFT', cx, y0 + h * 0.25, h * 0.21, w * 0.84)
            return
        label = PC_LABELS.get(key, key.upper())
        cap = h * (0.52 if len(label) == 1 else 0.36 if len(label) == 2 else 0.26)
        g.hole(pen, label, (x0 + x1) / 2, (y0 + y1) / 2, cap, w * 0.74)

    def arrow(pen, cx, cy, d, s):
        """A filled arrowhead pointing d, s its half size."""
        polygon(pen, {'up': [(cx - s, cy - s * 0.6), (cx + s, cy - s * 0.6), (cx, cy + s * 0.8)],
                      'down': [(cx + s, cy + s * 0.6), (cx - s, cy + s * 0.6), (cx, cy - s * 0.8)],
                      'left': [(cx + s * 0.6, cy - s), (cx + s * 0.6, cy + s), (cx - s * 0.8, cy)],
                      'right': [(cx - s * 0.6, cy + s), (cx - s * 0.6, cy - s), (cx + s * 0.8, cy)]}[d])

    def one(key, advance):
        def draw(pen):
            side = min(advance - 80, Y1 - Y0)
            key_cap(pen, (advance - side) / 2, Y0, (advance + side) / 2, Y1, key)
        return advance, draw

    def grid(cells, advance):
        """Small keys in a grid: cells = [(key, column, row)], row 0 on top."""
        def draw(pen):
            cols, rows = max(c for _, c, _ in cells) + 1, max(r for _, _, r in cells) + 1
            gap = 24; size = min((advance - 60 - gap * (cols - 1)) / cols, (Y1 - Y0 - gap * (rows - 1)) / rows)
            left, top = (advance - cols * size - gap * (cols - 1)) / 2, CY + (rows * size + gap * (rows - 1)) / 2
            for key, c, r in cells:
                x, y = left + c * (size + gap), top - (r + 1) * size - r * gap
                key_cap(pen, x, y, x + size, y + size, key)
        return advance, draw

    def mouse_move(advance, *dirs):
        """The mouse, no button pressed, with an arrow for each direction the prompt means."""
        def draw(pen):
            mouse_body(pen, advance / 2, Y0 + 30, Y1 - 30)
            off = (Y1 - Y0 - 60) * 0.33 + 70
            spots = {'up': (advance / 2 + off, CY + 110), 'down': (advance / 2 + off, CY - 110),
                     'left': (advance / 2 - off, CY), 'right': (advance / 2 + off, CY)}
            for d in dirs:
                arrow(pen, *spots[d], d, 52)
        return advance, draw

    b = binds
    up, left, down, right = b['LSTICK_UP'], b['LSTICK_LEFT'], b['LSTICK_DOWN'], b['LSTICK_RIGHT']
    du, dl, dd, dr = b['UP'], b['LEFT'], b['DOWN'], b['RIGHT']
    return {
        **{cp: one(b[name], adv[cp]) for cp, name in ((0xE040, 'A'), (0xE041, 'B'), (0xE042, 'X'), (0xE043, 'Y'),
                                                      (0xE044, 'L'), (0xE045, 'R'), (0xE046, 'ZL'), (0xE047, 'ZR'),
                                                      (0xE04B, 'PLUS'), (0xE04C, 'MINUS'), (0xE056, 'LCLICK'),
                                                      (0xE057, 'RCLICK'))},
        # the d-pad: its four keys as a cross (up on top), or the keys of the directions the prompt means
        0xE049: grid([(du, 1, 0), (dl, 0, 1), (dd, 1, 1), (dr, 2, 1)], adv[0xE049]),
        0xE060: one(du, adv[0xE060]), 0xE061: one(dd, adv[0xE061]), 0xE062: one(dl, adv[0xE062]),
        0xE063: one(dr, adv[0xE063]), 0xE064: grid([(du, 0, 0), (dd, 0, 1)], adv[0xE064]),
        0xE065: grid([(dl, 0, 0), (dr, 1, 0)], adv[0xE065]),
        # the left stick: its keys (W A S D)
        0xE05E: grid([(up, 1, 0), (left, 0, 1), (down, 1, 1), (right, 2, 1)], adv[0xE05E]),
        0xE052: one(up, adv[0xE052]), 0xE050: one(down, adv[0xE050]), 0xE05A: one(left, adv[0xE05A]),
        0xE058: one(right, adv[0xE058]), 0xE05C: grid([(up, 0, 0), (down, 0, 1)], adv[0xE05C]),
        0xE054: grid([(left, 0, 0), (right, 1, 0)], adv[0xE054]),
        # the right stick: the mouse
        0xE05F: mouse_move(adv[0xE05F]), 0xE053: mouse_move(adv[0xE053], 'up'),
        0xE051: mouse_move(adv[0xE051], 'down'), 0xE05B: mouse_move(adv[0xE05B], 'left'),
        0xE059: mouse_move(adv[0xE059], 'right'), 0xE05D: mouse_move(adv[0xE05D], 'up', 'down'),
        0xE055: mouse_move(adv[0xE055], 'left', 'right'),
        # the right stick shaken: the shake key
        0xE068: one(b['SHAKE'], adv[0xE068]),
    }


def redraw_font(otf, icons, swaps=()):
    """The OpenType font otf with the glyphs of each (code point, code point) pair of swaps trading places (outlines and
    horizontal metrics), then every code point of icons (code point -> (advance, draw)) drawn anew, written again by
    fontTools. The timestamps stay, so the same input gives the same bytes."""
    font = TTFont(io.BytesIO(otf), recalcTimestamp=False)
    assert font['head'].unitsPerEm == 1000, f'em of {font["head"].unitsPerEm} units, the drawings assume 1000'
    cff = font['CFF '].cff
    top = cff.topDictIndex[0]
    assert not hasattr(top, 'ROS'), 'CID-keyed CFF'   # its glyphs can use different private dictionaries
    charstrings, private, hmtx, cmap = top.CharStrings, top.Private, font['hmtx'], font.getBestCmap()
    nominal = getattr(private, 'nominalWidthX', 0)
    for a, b in swaps:
        ga, gb = cmap[a], cmap[b]
        outline_a, outline_b = charstrings[ga], charstrings[gb]
        charstrings[ga], charstrings[gb] = outline_b, outline_a
        hmtx[ga], hmtx[gb] = hmtx[gb], hmtx[ga]
    for cp, (advance, draw) in icons.items():
        pen = T2CharStringPen(advance - nominal, None); draw(pen)   # the width operand is relative to nominalWidthX
        charstrings[cmap[cp]] = pen.getCharString(private=private, globalSubrs=cff.GlobalSubrs)
    glyphs = font.getGlyphSet()
    for cp, (advance, _) in icons.items():
        box = BoundsPen(glyphs); glyphs[cmap[cp]].draw(box)
        hmtx[cmap[cp]] = (advance, int(round(box.bounds[0])))
    out = io.BytesIO(); font.save(out)
    return out.getvalue()


# ---- the button guide's images: square R8_UNORM masks (white key, black letter), one mip, block-linear, 72x72 up to
# 1.2.1 and 108x108 in 1.4.3. Each is drawn from the icon of the same Switch button, fitted into the square.
R8_UNORM, HUD_MARGIN, SUPERSAMPLE = 0x201, 4, 4


def gob_offset(x, y, width_gobs, block_height):
    """Byte offset of (x, y) in a Tegra block-linear surface of 1 byte per pixel (GOBs of 64 bytes x 8 rows)."""
    return ((y // (8 * block_height)) * 512 * block_height * width_gobs + (x // 64) * 512 * block_height
            + ((y % (8 * block_height)) // 8) * 512 + ((x % 64) // 32) * 256 + ((y % 8) // 2) * 64
            + ((x % 32) // 16) * 32 + (y % 2) * 16 + (x % 16))


class PolygonPen(BasePen):
    """Outlines flattened to closed polygons."""
    def __init__(self):
        super().__init__(None); self.polygons = []

    def _moveTo(self, pt):
        self.polygons.append([pt])

    def _lineTo(self, pt):
        self.polygons[-1].append(pt)

    def _curveToOne(self, pt1, pt2, pt3):
        p0 = self.polygons[-1][-1]
        for i in range(1, 17):
            t = i / 16; u = 1 - t
            self.polygons[-1].append(tuple(u ** 3 * p0[k] + 3 * u * u * t * pt1[k] + 3 * u * t * t * pt2[k] + t ** 3 * pt3[k]
                                           for k in (0, 1)))

    def _qCurveToOne(self, pt1, pt2):
        p0 = self.polygons[-1][-1]
        for i in range(1, 17):
            t = i / 16; u = 1 - t
            self.polygons[-1].append(tuple(u * u * p0[k] + 2 * u * t * pt1[k] + t * t * pt2[k] for k in (0, 1)))


def rasterize(draw, size):
    """A size x size coverage mask (0..255, rows top down) of draw's outline, fitted into the square, nonzero winding."""
    return rasterize_rect(draw, size, size, HUD_MARGIN)


def rasterize_rect(draw, width, height, margin, fit=None):
    """A width x height coverage mask (0..255, rows top down) of draw's outline, fitted and centred into the rectangle
    inside margin pixels on each side (or into fit, (left, top, right, bottom) in pixels), nonzero winding."""
    rec = RecordingPen(); draw(rec)
    box = BoundsPen(None); rec.replay(box); x0, y0, x1, y1 = box.bounds
    left, top, right, bottom = fit or (margin, margin, width - margin, height - margin)
    inner_w, inner_h = right - left, bottom - top
    scale = min(inner_w / (x1 - x0), inner_h / (y1 - y0))
    ox = left + (inner_w - (x1 - x0) * scale) / 2 - x0 * scale
    oy = top + (inner_h - (y1 - y0) * scale) / 2 - y0 * scale
    flat = PolygonPen(); rec.replay(TransformPen(flat, (scale, 0, 0, -scale, ox, height - oy)))   # font y up -> rows down
    edges = [(a, b) for poly in flat.polygons for a, b in zip(poly, poly[1:] + poly[:1]) if a[1] != b[1]]
    nx, ny = width * SUPERSAMPLE, height * SUPERSAMPLE; cover = [0] * (width * height)
    for row in range(ny):
        y = (row + 0.5) / SUPERSAMPLE
        crossings = sorted((a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), 1 if b[1] > a[1] else -1)
                           for a, b in edges if min(a[1], b[1]) <= y < max(a[1], b[1]))
        winding, start = 0, None
        for x, d in crossings:
            if winding == 0:
                start = x
            winding += d
            if winding == 0:
                for col in range(max(0, round(start * SUPERSAMPLE)), min(nx, round(x * SUPERSAMPLE))):
                    cover[(row // SUPERSAMPLE) * width + col // SUPERSAMPLE] += 1
    return bytes(min(255, c * 255 // (SUPERSAMPLE * SUPERSAMPLE)) for c in cover)


def bntx_redraw(data, base, textures, icons):
    """Paint the icon of each texture of textures (name without the ^ suffix -> code point; icons: code point ->
    (advance, draw)) over its image in the BNTX at data[base:] (a bytearray), in place. Returns the names painted."""
    assert data[base:base + 4] == b'BNTX' and data[base + 0x20:base + 0x24] == b'NX  '
    count, table = struct.unpack_from('<IQ', data, base + 0x24)
    done = []
    for k in range(count):
        info = base + struct.unpack_from('<Q', data, base + table + 8 * k)[0]
        assert data[info:info + 4] == b'BRTI'
        at = base + struct.unpack_from('<Q', data, info + 0x60)[0]
        name = data[at + 2:at + 2 + struct.unpack_from('<H', data, at)[0]].decode().split('^')[0]
        if name not in textures:
            continue
        mips, fmt = struct.unpack_from('<H', data, info + 0x16)[0], struct.unpack_from('<I', data, info + 0x1c)[0]
        (w, h), layout = struct.unpack_from('<II', data, info + 0x24), struct.unpack_from('<I', data, info + 0x34)[0]
        assert fmt == R8_UNORM and w == h and mips == 1, f'{name}: format {fmt:#x}, {w}x{h}, {mips} mips'
        start = base + struct.unpack_from('<Q', data, base + struct.unpack_from('<Q', data, info + 0x70)[0])[0]
        size, block = struct.unpack_from('<I', data, info + 0x50)[0], 1 << (layout & 7)
        mask = rasterize(icons[textures[name]][1], w)
        for y in range(h):
            for x in range(w):
                at = gob_offset(x, y, (w + 63) // 64, block)
                assert at < size, f'{name}: pixel ({x}, {y}) past the image'
                data[start + at] = mask[y * w + x]
        done.append(name)
    missing = sorted(set(textures) - set(done))
    assert not missing, f'not in the texture list: {", ".join(missing)}'
    return done


# ---- the controller picture. The game draws its Pro Controller (Controller_Pro, and Controller_Pro1 in the tutorials'
# button guide, PaActionGuide_00) as a flat illustration: a dark body outlined in black, lighter buttons, on a transparent
# background, ASTC 4x4 sRGB. With --prompts playstation the same textures hold a DualSense in that style, from the
# controller_playstation5 glyph of Kenney's Input Prompts font (CC0, tools/data/kenney_input): the glyph's holes
# (buttons, touchpad) become the lighter grey, and an outline is grown around it. The R and ZR guide lines sit on the
# shoulders at the top, where the DualSense has its own.
CONTROLLER_TEXTURES = ('Controller_Pro', 'Controller_Pro1')
SHOULDER_TEXTURES = ('ConProR_00', 'ConProR_Line', 'ConProZR_00', 'ConProZR_Line')
CONTROLLER_GLYPH = 'controller_playstation5'
CONTROLLER_FONT = os.path.join(os.path.dirname(__file__), 'data', 'kenney_input', 'kenney_input_playstation_series.otf')
CONTROLLER_COLORS = dict(body=(0x2E, 0x2E, 0x2E), button=(0x74, 0x74, 0x74), outline=(0x10, 0x10, 0x10))
CONTROLLER_OUTLINE = 3
# The Pro Controller fills x 75..505, y 20..325 of its 580 x 340 picture, and the guide's highlights (circles, lines)
# sit on its buttons: the left stick top left, the d-pad under it, the right stick lower right, the face buttons top right,
# Minus and Plus either side of the top. The DualSense is fitted to the same box (inside the outline) and its d-pad and
# left stick, which it has the other way round, trade places, so each highlight lands on the button it names.
CONTROLLER_DPAD_SCALE, CONTROLLER_DPAD_RISE, CONTROLLER_DPAD_SHIFT = 0.85, 40, -12   # the rise and shift in glyph units
CONTROLLER_BOX = (78 / 580, 23 / 340, 502 / 580, 322 / 340)
ASTC_4X4_SRGB = 0x2D06


def controller_draw(pen):
    """The controller_playstation5 outline with its d-pad (four 82-unit arrows) and left stick (a 123-unit circle left of
    the middle) swapped, so the stick is where a Pro Controller has it. Made for the glyph of tools/data/kenney_input."""
    contours, current = [], []
    glyph = TTFont(CONTROLLER_FONT).getGlyphSet()[CONTROLLER_GLYPH]
    recording = RecordingPen(); glyph.draw(recording)
    for step in recording.value:
        current.append(step)
        if step[0] in ('closePath', 'endPath'):
            contours.append(current); current = []
    boxes = []
    for contour in contours:
        bounds, rec = BoundsPen(None), RecordingPen(); rec.value = contour; rec.replay(bounds)
        x0, y0, x1, y1 = bounds.bounds
        boxes.append(((x0 + x1) / 2, (y0 + y1) / 2, round(x1 - x0)))
    dpad = [i for i, b in enumerate(boxes) if b[2] == 82]
    stick = [i for i, b in enumerate(boxes) if b[2] == 123 and b[0] < 512]
    assert len(dpad) == 4 and len(stick) == 1, boxes
    cx = sum(boxes[i][0] for i in dpad) / 4; cy = (min(boxes[i][1] for i in dpad) + max(boxes[i][1] for i in dpad)) / 2
    sx, sy = boxes[stick[0]][:2]
    for i, contour in enumerate(contours):
        # The body's lower edge is higher than the Pro's, so the d-pad, in the stick's place, is a little smaller, higher and to the left (clear of the touchpad's corner).
        matrix = ((CONTROLLER_DPAD_SCALE, 0, 0, CONTROLLER_DPAD_SCALE, sx + CONTROLLER_DPAD_SHIFT - CONTROLLER_DPAD_SCALE * cx,
                   sy + CONTROLLER_DPAD_RISE - CONTROLLER_DPAD_SCALE * cy) if i in dpad
                  else (1, 0, 0, 1, cx - sx, cy - sy) if i in stick else (1, 0, 0, 1, 0, 0))
        rec = RecordingPen(); rec.value = contour
        rec.replay(TransformPen(pen, matrix))


@functools.lru_cache(maxsize=None)
def controller_cover(width, height):
    """(cover, outside) of the DualSense in a width x height picture: the glyph's coverage mask (0..255, rows top down)
    and a flag per pixel for those the picture's border reaches without crossing the glyph (the body's holes, its
    buttons, are the ones that are not)."""
    fit = (CONTROLLER_BOX[0] * width, CONTROLLER_BOX[1] * height, CONTROLLER_BOX[2] * width, CONTROLLER_BOX[3] * height)
    cover = rasterize_rect(controller_draw, width, height, 0, fit)
    # What the glyph does not cover and the picture's border cannot reach is a hole inside the body: a button.
    outside, queue = bytearray(width * height), []
    for x in range(width):
        queue += [x, (height - 1) * width + x]
    for y in range(height):
        queue += [y * width, y * width + width - 1]
    while queue:
        i = queue.pop()
        if outside[i] or cover[i] >= 128:
            continue
        outside[i] = 1
        x = i % width
        if x:
            queue.append(i - 1)
        if x < width - 1:
            queue.append(i + 1)
        if i >= width:
            queue.append(i - width)
        if i < width * (height - 1):
            queue.append(i + width)
    return cover, outside


def controller_rgba(width, height):
    """width x height RGBA bytes of the DualSense picture (straight alpha, sRGB colours)."""
    cover, outside = controller_cover(width, height)
    body, button, edge = (CONTROLLER_COLORS[k] for k in ('body', 'button', 'outline'))
    reach = CONTROLLER_OUTLINE + 1
    out = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            i = y * width + x
            c = cover[i]
            if not outside[i]:   # on the glyph, or in a hole of it
                t = c / 255
                rim = c < 255 and (x == 0 or outside[i - 1] or x == width - 1 or outside[i + 1] or y == 0
                                   or outside[i - width] or y == height - 1 or outside[i + width])
                under = edge if rim else button   # antialiasing at the body's rim blends into the outline, in a hole into a button
                rgb = tuple(round(under[k] + (body[k] - under[k]) * t) for k in range(3))
                alpha = 255
            elif c:   # the glyph's antialiased edge, over the outline
                t = c / 255
                rgb, alpha = tuple(round(edge[k] + (body[k] - edge[k]) * t) for k in range(3)), 255
            else:
                # an outline CONTROLLER_OUTLINE pixels wide around the body: its distance to the nearest covered pixel
                best = reach * reach
                for yy in range(max(0, y - reach), min(height, y + reach + 1)):
                    row = yy * width
                    for xx in range(max(0, x - reach), min(width, x + reach + 1)):
                        if cover[row + xx] >= 128:
                            d = (xx - x) ** 2 + (yy - y) ** 2
                            if d < best:
                                best = d
                alpha = round(255 * max(0.0, min(1.0, CONTROLLER_OUTLINE + 0.5 - best ** 0.5)))
                rgb = edge
            out[i * 4:i * 4 + 4] = bytes(rgb) + bytes([alpha])
    return bytes(out)


def astc_blocks(rgba, width, height):
    """The ASTC 4x4 sRGB blocks (16 bytes each, row-major) of width x height RGBA bytes."""
    try:
        import astc_encoder as astc
    except ImportError as err:
        raise SystemExit('the DualSense controller picture needs astc-encoder-py (tools/requirements-py314.txt)') from err
    context = astc.ASTCContext(astc.ASTCConfig(astc.ASTCProfile.LDR_SRGB, 4, 4, 1, astc.ASTCQualityPreset.THOROUGH))
    return bytes(context.compress(astc.ASTCImage(astc.ASTCType.U8, width, height, 1, rgba),
                                  astc.ASTCSwizzle.from_str('RGBA')))


def block_offset(x, y, width_gobs, block_height, bytes_per_block=16):
    """Byte offset of block (x, y) in a Tegra block-linear surface of bytes_per_block per block (gob_offset's general form)."""
    xb = x * bytes_per_block
    return ((y // (8 * block_height)) * 512 * block_height * width_gobs + (xb // 64) * 512 * block_height
            + ((y % (8 * block_height)) // 8) * 512 + ((xb % 64) // 32) * 256 + ((y % 8) // 2) * 64
            + ((xb % 32) // 16) * 32 + (y % 2) * 16 + (xb % 16))


def bntx_blocks(data, base, textures, fmt, bytes_per_block, blocks_of):
    """Write blocks_of(name, width, height) (the compressed blocks, 4x4 pixels each, row-major) as the image of each
    texture of textures (name without the ^ suffix) in the BNTX at data[base:] (a bytearray), in place; they must be of
    format fmt with one mip. Returns the names written."""
    assert data[base:base + 4] == b'BNTX' and data[base + 0x20:base + 0x24] == b'NX  '
    count, table = struct.unpack_from('<IQ', data, base + 0x24)
    done = []
    for k in range(count):
        info = base + struct.unpack_from('<Q', data, base + table + 8 * k)[0]
        assert data[info:info + 4] == b'BRTI'
        at = base + struct.unpack_from('<Q', data, info + 0x60)[0]
        name = data[at + 2:at + 2 + struct.unpack_from('<H', data, at)[0]].decode().split('^')[0]
        if name not in textures:
            continue
        mips, found = struct.unpack_from('<H', data, info + 0x16)[0], struct.unpack_from('<I', data, info + 0x1c)[0]
        (w, h), layout = struct.unpack_from('<II', data, info + 0x24), struct.unpack_from('<I', data, info + 0x34)[0]
        assert found == fmt and mips == 1, f'{name}: format {found:#x}, {w}x{h}, {mips} mips'
        blocks = blocks_of(name, w, h)
        start = base + struct.unpack_from('<Q', data, base + struct.unpack_from('<Q', data, info + 0x70)[0])[0]
        size, block_height = struct.unpack_from('<I', data, info + 0x50)[0], 1 << (layout & 7)
        columns, rows = (w + 3) // 4, (h + 3) // 4
        assert len(blocks) == columns * rows * bytes_per_block, name
        for by in range(rows):
            for bx in range(columns):
                at = block_offset(bx, by, (columns * bytes_per_block + 63) // 64, block_height, bytes_per_block)
                assert at + bytes_per_block <= size, f'{name}: block ({bx}, {by}) past the image'
                n = (by * columns + bx) * bytes_per_block
                data[start + at:start + at + bytes_per_block] = blocks[n:n + bytes_per_block]
        done.append(name)
    missing = sorted(set(textures) - set(done))
    assert not missing, f'not in the texture list: {", ".join(missing)}'
    return done


def bntx_controller(data, base, textures):
    """Paint the DualSense picture over each texture of textures (ASTC 4x4 sRGB) of the BNTX at data[base:]; returns the
    names painted."""
    return bntx_blocks(data, base, textures, ASTC_4X4_SRGB, 16,
                       lambda name, w, h: astc_blocks(controller_rgba(w, h), w, h))


# The guide's R and ZR highlights (PaActionGuide_00; L and ZL are the same images mirrored): a fill (ConPro<K>_00) and an
# outline (ConPro<K>_Line), BC4 masks stretched over a pane that sits on the Pro Controller's shoulder. Each is
# (pane centre in the controller picture's pixels, pane size in layout units); the picture is shown at 0.9, so a layout
# unit is 1.1111 picture pixels tall and, the 570-wide pane showing a 580-wide image, 1.1306 wide. On the DualSense they
# are two crescents along the outline of its shoulder: the trigger's at the edge, the bumper's just inside it.
SHOULDER_PANES = {'ConProR': ((407.6, 62.2), (102, 44), (17, 33), (392, 466)),
                  'ConProZR': ((418.9, 45.6), (74, 49), (0, 16), (398, 464))}   # ..., band's distances, its x span
SMOOTH_OUTLINE = 6   # the outline the crescents follow is the body's blurred by this many pixels, so the trigger's step does not show
SHOULDER_UNIT = (580 / 570 / 0.9, 1 / 0.9)
SHOULDER_LINE = 2   # the outline's width in texels
BC4_UNORM = 0x1D01


def outline_distance(outside, width, height):
    """Per pixel, the distance (chamfer 3-4) to the nearest pixel of outside, for the whole picture."""
    inf = 1 << 20
    dist = [0 if outside[i] else inf for i in range(width * height)]
    for y in range(height):
        for x in range(width):
            i = y * width + x
            if dist[i]:
                best = dist[i]
                if x:
                    best = min(best, dist[i - 1] + 3)
                if y:
                    best = min(best, dist[i - width] + 3)
                    if x:
                        best = min(best, dist[i - width - 1] + 4)
                    if x < width - 1:
                        best = min(best, dist[i - width + 1] + 4)
                dist[i] = best
    for y in range(height - 1, -1, -1):
        for x in range(width - 1, -1, -1):
            i = y * width + x
            if dist[i]:
                best = dist[i]
                if x < width - 1:
                    best = min(best, dist[i + 1] + 3)
                if y < height - 1:
                    best = min(best, dist[i + width] + 3)
                    if x < width - 1:
                        best = min(best, dist[i + width + 1] + 4)
                    if x:
                        best = min(best, dist[i + width - 1] + 4)
                dist[i] = best
    return [d / 3 for d in dist]


@functools.lru_cache(maxsize=None)
def shoulder_distance(width, height):
    """(distance of each pixel to the body's smoothed outline, whether it is outside that outline) for the picture."""
    outside = controller_cover(width, height)[1]
    inside = [0.0 if outside[i] else 1.0 for i in range(width * height)]
    r = SMOOTH_OUTLINE   # a box blur along the rows, then along the columns
    rows = []
    for y in range(height):
        acc = [0.0]
        for v in inside[y * width:(y + 1) * width]:
            acc.append(acc[-1] + v)
        rows += [(acc[min(width, x + r + 1)] - acc[max(0, x - r)]) / (min(width, x + r + 1) - max(0, x - r))
                 for x in range(width)]
    inside = [0.0] * (width * height)
    for x in range(width):
        acc = [0.0]
        for y in range(height):
            acc.append(acc[-1] + rows[y * width + x])
        for y in range(height):
            lo, hi = max(0, y - r), min(height, y + r + 1)
            inside[y * width + x] = (acc[hi] - acc[lo]) / (hi - lo)
    smooth = bytearray(1 if v < 0.5 else 0 for v in inside)
    return outline_distance(smooth, width, height), smooth


def shoulder_mask(name, width, height, picture=(580, 340)):
    """width x height bytes (0..255) of the fill or outline texture `name` (ConProR_00, ConProR_Line, ConProZR_00,
    ConProZR_Line) for the DualSense: its R or ZR crescent, with rounded ends inside the pane."""
    key, kind = name.rsplit('_', 1)
    (cx, cy), (pane_w, pane_h), (near, far), (span_lo, span_hi) = SHOULDER_PANES[key]
    dist, outside = shoulder_distance(*picture)
    ux, uy = SHOULDER_UNIT
    mid, half_w, half_h, radius = (span_lo + span_hi) / 2, (span_hi - span_lo) / 2, pane_h * uy / 2 - 2, 10

    def band(px, py):   # 0..1 coverage of the crescent at a point of the picture
        x, y = min(picture[0] - 1, max(0, round(px - 0.5))), min(picture[1] - 1, max(0, round(py - 0.5)))
        d = dist[y * picture[0] + x]
        if outside[y * picture[0] + x]:
            return 0.0
        qx, qy = abs(px - mid) - half_w + radius, abs(py - cy) - half_h + radius   # a rounded rectangle's distance
        box = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius
        return (max(0.0, min(1.0, d - near + 0.5)) * max(0.0, min(1.0, far - d + 0.5))
                * max(0.0, min(1.0, 0.5 - box)))
    fill = []
    for j in range(height):
        for i in range(width):
            total = 0.0
            for sj in range(3):
                for si in range(3):
                    total += band(cx + (i + (si + 0.5) / 3 - width / 2) * pane_w / width * ux,
                                  cy + (j + (sj + 0.5) / 3 - height / 2) * pane_h / height * uy)
            fill.append(total / 9)
    if kind == '00':
        return bytes(round(255 * v) for v in fill)
    # the outline: the fill less itself shrunk by SHOULDER_LINE texels (a square window's minimum)
    r, out = SHOULDER_LINE, bytearray(width * height)
    for j in range(height):
        for i in range(width):
            inner = min(fill[jj * width + ii] if 0 <= ii < width and 0 <= jj < height else 0.0
                        for jj in range(j - r, j + r + 1) for ii in range(i - r, i + r + 1))
            out[j * width + i] = round(255 * max(0.0, fill[j * width + i] - inner))
    return bytes(out)


def bc4_blocks(mask, width, height):
    """The BC4 blocks (8 bytes each, row-major) of width x height bytes; the edge pixels repeat out to a multiple of 4."""
    out = bytearray()
    for by in range((height + 3) // 4):
        for bx in range((width + 3) // 4):
            px = [mask[min(height - 1, by * 4 + j) * width + min(width - 1, bx * 4 + i)] for j in range(4) for i in range(4)]
            hi, lo = max(px), min(px)
            palette = [hi, lo] + [((7 - k) * hi + k * lo) // 7 for k in range(1, 7)] if hi > lo else [hi] * 8
            bits = 0
            for n, v in enumerate(px):
                bits |= min(range(8), key=lambda k: abs(palette[k] - v)) << (3 * n)
            out += bytes([hi, lo]) + bits.to_bytes(6, 'little')
    return bytes(out)


def bntx_shoulders(data, base, textures):
    """Draw the DualSense's R and ZR highlights into the BC4 textures of textures (ConProR_00, ConProR_Line, ConProZR_00,
    ConProZR_Line) of the BNTX at data[base:]; returns the names written."""
    return bntx_blocks(data, base, textures, BC4_UNORM, 8, lambda name, w, h: bc4_blocks(shoulder_mask(name, w, h), w, h))


# ---- the resource size table: System/Resource/ResourceSizeTable.Product.<n>.Nin_NX_NVN.rsizetable.zs, a RESTBL whose
# entries are keyed by the CRC32 of the RomFS path without .zs. The game sizes the buffer it loads a file into from its
# entry, so an archive that grew needs its entry raised by as much.
def restbl_offsets(table):
    """CRC32 of a path -> offset of its size in the RESTBL table."""
    assert table[:6] == b'RESTBL', 'not a RESTBL'
    count = struct.unpack_from('<I', table, 14)[0]
    return {struct.unpack_from('<I', table, 22 + i * 8)[0]: 22 + i * 8 + 4 for i in range(count)}


def grow_restbl(table, growth):
    """table with the entry of each RomFS path of growth (path -> bytes it grew) raised by that much."""
    at, out = restbl_offsets(table), bytearray(table)
    for path, extra in growth.items():
        h = zlib.crc32(path.removesuffix('.zs').encode())
        assert h in at, f'{path} has no entry in the resource size table'
        struct.pack_into('<I', out, at[h], struct.unpack_from('<I', out, at[h])[0] + extra)
    return bytes(out)
