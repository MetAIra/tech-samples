"""映像：1コマずつ絵を計算する。すべての出来事は拍番号 b で書いている。

 0〜 8拍  シーン1  MOVE / SHAPE / RHYTHM の文字アニメ
 8〜16拍  シーン2  丸→四角→三角→星→丸 の変形
16〜24拍  シーン3  3Dトンネルとワイヤーの立方体
24〜28拍  シーン4  グラフエディタ（イージング曲線そのものを見せる）
28〜32拍  シーン5  爆発 → 粒子が集まって PYTHON
"""
import functools
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from common import (BEATS, BPM, FPS, H, SILENCE_BEAT, SPB, W, beat_pulse,
                    clamp01, ease_in_cubic, ease_in_expo, ease_in_out_cubic,
                    ease_out_back, ease_out_bounce, ease_out_expo, lerp, prog)


def _find_font(candidates):
    """環境にある太字フォントを探す(見つからなければ None = Pillow の既定フォント)。
    環境変数 MG_FONT_TITLE / MG_FONT_MONO でパスを直接指定することもできる。"""
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


FONT_TITLE = _find_font([
    os.environ.get("MG_FONT_TITLE"),
    "C:/Windows/Fonts/ariblk.ttf",                                   # Windows: Arial Black
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",            # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",          # Linux
])
FONT_MONO = _find_font([
    os.environ.get("MG_FONT_MONO"),
    "C:/Windows/Fonts/consolab.ttf",                                 # Windows: Consolas Bold
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",       # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",      # Linux
])

INK = (14, 14, 26)
WHITE = (246, 246, 250)
ORANGE = (255, 94, 58)
YELLOW = (255, 214, 10)
CYAN = (40, 220, 255)
PINK = (255, 60, 160)
VIOLET = (110, 70, 255)

LAG = 2 / FPS / SPB   # 残像の遅れ（2コマ分を拍に換算）


# =====================================================================
# 基本の道具
# =====================================================================
def canvas(color):
    c = np.empty((H, W, 3), np.float32)
    c[...] = color
    return c


def blank():
    return np.zeros((H, W), np.uint8)


def comp(c, m, color, opacity=1.0):
    """マスク m の形に color（色 or 画像）を塗って重ねる"""
    if opacity <= 0:
        return
    a = m.astype(np.float32) * (opacity / 255.0) if m.dtype == np.uint8 else m * opacity
    c += a[..., None] * (np.asarray(color, np.float32) - c)


SHIFT = 4                # 1/16ピクセル単位で描いて、なめらかに動かす
ONE = 1 << SHIFT


def _fx(p):
    return np.round(np.asarray(p, np.float64) * ONE).astype(np.int32)


def fill_poly(img, pts, val=255):
    cv2.fillPoly(img, [_fx(pts).reshape(-1, 1, 2)], val, cv2.LINE_AA, SHIFT)


def stroke(img, pts, thick, closed=True, val=255):
    cv2.polylines(img, [_fx(pts).reshape(-1, 1, 2)], closed, val,
                  max(1, int(round(thick))), cv2.LINE_AA, SHIFT)


def disc(img, center, r, thick=-1, val=255):
    if r <= 0.5:
        return
    cx, cy = _fx(center)
    t = -1 if thick < 0 else max(1, int(round(thick)))
    cv2.circle(img, (int(cx), int(cy)), int(round(r * ONE)), val, t, cv2.LINE_AA, SHIFT)


def shifted(m, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(m, M, (W, H))


@functools.lru_cache(maxsize=None)
def _disk(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


@functools.lru_cache(maxsize=None)
def _font(path, size):
    if path is None:
        try:
            return ImageFont.load_default(size=size)   # Pillow 10.1 以降
        except TypeError:
            return ImageFont.load_default()
    return ImageFont.truetype(path, size)


@functools.lru_cache(maxsize=4096)
def text_mask(text, size, path=FONT_TITLE, pad=24):
    """文字を白黒のマスク画像にする（一度作ったら使い回す）"""
    f = _font(path, size)
    l, t, r, b = f.getbbox(text)
    img = Image.new("L", (r - l + 2 * pad, b - t + 2 * pad), 0)
    ImageDraw.Draw(img).text((pad - l, pad - t), text, font=f, fill=255)
    return np.asarray(img)


def place(src, cx, cy, scale=1.0, angle=0.0):
    """マスクを拡大・回転して、中心 (cx, cy) に置く"""
    if scale <= 1e-3:
        return blank()
    h, w = src.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    M[0, 2] += cx - w / 2
    M[1, 2] += cy - h / 2
    return cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LINEAR)


def label(c, text, size, x, y, color, font=FONT_MONO, anchor="l", opacity=1.0):
    """小さな文字を、その部分だけ計算して描く（速い）"""
    if opacity <= 0 or not text:
        return
    src = text_mask(text, size, font, pad=2)
    h, w = src.shape
    x = int(x - (w // 2 if anchor == "c" else w if anchor == "r" else 0))
    y = int(y - h // 2)
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    a = src[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32) * (opacity / 255)
    sub = c[y0:y1, x0:x1]
    sub += a[..., None] * (np.asarray(color, np.float32) - sub)


def sticker(c, m, fill, edge=WHITE, shadow=VIOLET, r=7, off=(10, 10), opacity=1.0):
    """ステッカー風：形を太らせたフチ＋ずらした影"""
    fat = cv2.dilate(m, _disk(r))
    comp(c, shifted(fat, *off), shadow, opacity)
    comp(c, fat, edge, opacity)
    comp(c, m, fill, opacity)


def gradient(u, stops=(ORANGE, PINK, CYAN)):
    """0〜1 の値を 3色のグラデーションに変換"""
    xs = np.linspace(0, 1, len(stops))
    s = np.asarray(stops, np.float32)
    return np.stack([np.interp(u, xs, s[:, ch]) for ch in range(3)], -1).astype(np.float32)


# 画面全体で使う素材は最初に1回だけ作る
_gx, _gy = np.meshgrid(np.arange(40, W, 64), np.arange(40, H, 64))
GRID_PTS = np.stack([_gx.ravel(), _gy.ravel()], 1).astype(np.float64)
GRID_DIST = np.hypot(GRID_PTS[:, 0] - W / 2, GRID_PTS[:, 1] - H / 2)

_yy, _xx = np.mgrid[0:H, 0:W].astype(np.float32)
VIGNETTE = 1 - 0.38 * (np.hypot((_xx - W / 2) / (W / 2), (_yy - H / 2) / (H / 2)) / 1.414) ** 2.2
GRAIN = np.random.default_rng(0).normal(0, 6.5, (H + 64, W + 64)).astype(np.float32)
TEXT_GRAD = np.broadcast_to(gradient(np.clip((_xx[0] - 180) / 920, 0, 1))[None], (H, W, 3))
del _gx, _gy, _yy, _xx


def dot_grid(c, b, color):
    """点の格子。拍ごとに中心から波紋が広がって点がふくらむ"""
    ripple = (b % 1.0) * 1100 if b >= 0 else -1e9
    r = 1.6 + 4.2 * np.exp(-((GRID_DIST - ripple) / 70) ** 2)
    m = blank()
    for p, rr in zip(GRID_PTS, r):
        disc(m, p, rr)
    comp(c, m, color)


def beat_ring(c, b, color, maxr=760):
    if b < 0:
        return
    f = b % 1.0
    m = blank()
    disc(m, (W / 2, H / 2), ease_out_expo(f) * maxr, 10 * (1 - f) + 1)
    comp(c, m, color, 1 - f)


# =====================================================================
# シーン1：キネティック・タイポ（0〜8拍）
# =====================================================================
def move_state(b):      # 滑り込み（expo）
    x = lerp(-560, W / 2, ease_out_expo(prog(b, 0, 1))) + lerp(0, 1800, ease_in_expo(prog(b, 6.5, 1)))
    return x, 190, 1.0, 0.0


def shape_state(b):     # ポンと出る（back）
    t = ease_out_back(prog(b, 2, 0.9))
    s = t * (1 - ease_in_cubic(prog(b, 6.75, 0.75)))
    return W / 2, 365, s, lerp(-14, 0, t)


def rhythm_state(b):    # 落ちて弾む（bounce）
    y = lerp(-170, 545, ease_out_bounce(prog(b, 4, 1.5))) + lerp(0, 520, ease_in_expo(prog(b, 7, 0.75)))
    return W / 2, y, 1.0, 0.0


def draw_word(c, text, size, state, b, fill, shadow):
    src = text_mask(text, size)
    x, y, s, a = state(b)
    # 3色の残像：2・4・6コマ前の位置に別の色で塗って後ろに敷く
    for k, col in ((3, CYAN), (2, YELLOW), (1, PINK)):
        px, py, ps, pa = state(b - k * LAG)
        if abs(px - x) + abs(py - y) + abs(ps - s) * 200 > 3:
            comp(c, place(src, px, py, ps, pa), col, 0.9)
    if s > 1e-3:
        sticker(c, place(src, x, y, s * (1 + 0.04 * beat_pulse(b)), a), fill, shadow=shadow)


def scene_a(b):
    c = canvas(INK)
    dot_grid(c, b, (52, 52, 88))
    beat_ring(c, b, (80, 64, 160))
    draw_word(c, "MOVE", 170, move_state, b, ORANGE, VIOLET)
    draw_word(c, "RHYTHM", 150, rhythm_state, b, CYAN, VIOLET)   # 落ちてくる途中は SHAPE の後ろを通る
    draw_word(c, "SHAPE", 150, shape_state, b, YELLOW, PINK)
    return c


# =====================================================================
# シーン2：図形の変形（8〜16拍）
# =====================================================================
N_PTS = 240   # 図形のまわりを240点で表す


def _resample(verts, n=N_PTS):
    """多角形の周囲を等間隔の n 点にする（上から時計回り）"""
    v = np.asarray(verts, float)
    v = np.vstack([v, v[:1]])
    cum = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(v, axis=0).T))])
    s = np.linspace(0, cum[-1], n, endpoint=False)
    return np.stack([np.interp(s, cum, v[:, 0]), np.interp(s, cum, v[:, 1])], 1)


def _polar(deg, r):
    a = math.radians(deg)
    return r * math.cos(a), r * math.sin(a)


_ang = np.linspace(0, 2 * np.pi, N_PTS, endpoint=False) - np.pi / 2
SHAPES = {
    "CIRCLE": np.stack([np.cos(_ang), np.sin(_ang)], 1),
    "SQUARE": _resample([(0, -.86), (.86, -.86), (.86, .86), (-.86, .86), (-.86, -.86)]),
    "TRIANGLE": _resample([_polar(-90, 1.2), _polar(30, 1.2), _polar(150, 1.2)]),
    "STAR": _resample([_polar(-90 + 36 * i, 1.18 if i % 2 == 0 else 0.5) for i in range(10)]),
}
ORDER = ["CIRCLE", "SQUARE", "TRIANGLE", "STAR", "CIRCLE"]


def shape_at(b):
    """9・11・13・15拍目に次の形へ。同じ番号の点同士を動かして変形させる"""
    pts, idx = SHAPES[ORDER[0]], 0
    for k in range(len(ORDER) - 1):
        start = 9 + 2 * k
        if b >= start:
            t = ease_out_back(prog(b, start, 0.8))
            pts = SHAPES[ORDER[k]] + (SHAPES[ORDER[k + 1]] - SHAPES[ORDER[k]]) * t
            idx = k + 1
    return pts, idx


def shape_poly(b, cx, cy):
    pts, _ = shape_at(b)
    r = 205 * ease_out_back(prog(b, 8, 0.6)) * (1 + 0.07 * beat_pulse(b))
    a = math.radians((b - 8) * 24)
    ca, sa = math.cos(a), math.sin(a)
    return pts @ np.array([[ca, sa], [-sa, ca]]) * r + (cx, cy)


def scene_b(b):
    c = canvas(YELLOW)
    cx, cy = W / 2, H / 2 - 12
    comp(c, place(text_mask("SHAPE", 400), W / 2 + 260 - (b - 8) * 55, H / 2), INK, 0.06)
    for k, col in enumerate((PINK, CYAN, ORANGE)):
        a = (b - 8) * 1.1 + k * 2 * math.pi / 3
        m = blank()
        disc(m, (cx + math.cos(a) * 390, cy + math.sin(a) * 250), 14)
        comp(c, m, col)
    if b >= 8:
        for k, col in ((3, CYAN), (2, PINK), (1, ORANGE)):
            m = blank()
            fill_poly(m, shape_poly(b - k * LAG, cx + k * 10, cy + k * 10))
            comp(c, m, col)
        m = blank()
        fill_poly(m, shape_poly(b, cx, cy))
        comp(c, m, INK)
        _, idx = shape_at(b)
        pop = 1 + 0.35 * math.exp(-8 * max(0.0, b - (7 + 2 * idx if idx else 8)))
        name = f"{idx + 1:02d}  {ORDER[idx]}"
        comp(c, place(text_mask(name, 40), W / 2, 668, pop * ease_out_back(prog(b, 8.2, 0.6))), INK)
    return c


# =====================================================================
# シーン3：3Dトンネルとワイヤーの立方体（16〜24拍）
# =====================================================================
BG_C = (8, 8, 22)
TUN_N, TUN_GAP, FOCAL = 18, 0.8, 560
CUBE_V = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float)
CUBE_E = [(i, j) for i in range(8) for j in range(i + 1, 8)
          if np.abs(CUBE_V[i] - CUBE_V[j]).sum() == 2]
_srng = np.random.default_rng(9)
STARS = np.stack([_srng.uniform(-4, 4, 140), _srng.uniform(-2.5, 2.5, 140),
                  _srng.uniform(0, TUN_N * TUN_GAP, 140)], 1)


def project(p):
    """遠近法：遠い物ほど小さく（x/z, y/z）"""
    z = np.maximum(p[:, 2], 0.05)
    return np.stack([W / 2 + FOCAL * p[:, 0] / z, H / 2 + FOCAL * p[:, 1] / z], 1)


def rot_xyz(ax, ay, az):
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def fade_col(col, bg, k):
    return tuple(int(bg[i] + (col[i] - bg[i]) * clamp01(k)) for i in range(3))


def scene_c(b):
    c8 = np.empty((H, W, 3), np.uint8)
    c8[:] = BG_C
    far = TUN_N * TUN_GAP
    step = math.floor(b) + ease_out_expo(b % 1.0)   # 拍ごとにグッと前進

    # 流れる光の筋
    zs = (STARS[:, 2] - step * TUN_GAP) % far + 0.3
    for (x, y, _), z in zip(STARS, zs):
        p = project(np.array([[x, y, z], [x, y, z + 0.5]]))
        stroke(c8, p, 1, closed=False, val=fade_col(WHITE, BG_C, 0.9 - z / far))

    # トンネルの輪（奥から手前へ）
    rings = sorted((((i - step) % TUN_N) * TUN_GAP + 0.3, i) for i in range(TUN_N))
    for z, i in reversed(rings):
        a = math.radians(b * 8 + i * 9)
        ca, sa = math.cos(a), math.sin(a)
        p = np.array([[x * ca - y * sa, x * sa + y * ca, z]
                      for x, y in ((-1.9, -1.1), (1.9, -1.1), (1.9, 1.1), (-1.9, 1.1))])
        k = (1.15 - z / far) * clamp01((z - 0.3) / 0.6)
        stroke(c8, project(p), min(14, 2 + 5 / z), val=fade_col(CYAN if i % 2 else VIOLET, BG_C, k))

    # ワイヤーの立方体（外側の白と、逆回転する内側の黄色）
    s = ease_out_back(prog(b, 16, 0.8)) * (1 + 0.16 * beat_pulse(b))
    if s > 0:
        kick = math.floor(b) + ease_out_back(b % 1.0)
        R = rot_xyz(0.31 * kick + 0.2 * b, 0.47 * kick, 0.1 * b)
        for size, col, Rm in ((1.25, WHITE, R), (0.55, YELLOW, R.T)):
            q = project((CUBE_V * size * s) @ Rm.T + (0, 0, 5.0))
            for th, cc in ((10, fade_col(col, BG_C, 0.22)), (3, col)):
                for i, j in CUBE_E:
                    stroke(c8, q[[i, j]], th, closed=False, val=cc)
            for p in q:
                disc(c8, p, 6, val=col)

    c = c8.astype(np.float32)
    t = ease_out_back(prog(b, 16.75, 0.8)) * (1 - ease_in_cubic(prog(b, 23.25, 0.6)))
    if t > 1e-3:
        sticker(c, place(text_mask("DEPTH", 96), W / 2, 628, t), WHITE,
                edge=VIOLET, shadow=PINK, r=5, off=(7, 7))
    return c


# =====================================================================
# シーン4：グラフエディタ（24〜28拍）
# =====================================================================
BG_D, PANEL, GRIDC, AXIS = (22, 22, 28), (31, 31, 40), (48, 48, 60), (96, 96, 116)
GX0, GY0, GW, GH = 100, 160, 660, 430
TX0, TX1 = 860, 1170
CURVES = (("easeOutExpo", ease_out_expo, ORANGE),
          ("easeOutBack", ease_out_back, YELLOW),
          ("easeOutBounce", ease_out_bounce, CYAN))


def gpt(u, v):
    return GX0 + u * GW, GY0 + GH - (0.08 + 0.8 * v) * GH


def diamond(img, p, r, val):
    x, y = p
    fill_poly(img, [(x, y - r), (x + r, y), (x, y + r), (x - r, y)], val)


def scene_d(b):
    if b >= SILENCE_BEAT:
        return canvas((0, 0, 0))
    c8 = np.empty((H, W, 3), np.uint8)
    c8[:] = BG_D
    cv2.rectangle(c8, (GX0 - 24, GY0 - 24), (GX0 + GW + 24, GY0 + GH + 24), PANEL, -1)
    for q in range(5):
        stroke(c8, [gpt(q / 4, -0.1), gpt(q / 4, 1.1)], 1, closed=False, val=GRIDC)
        stroke(c8, [gpt(0, q / 4), gpt(1, q / 4)], 1, closed=False, val=AXIS if q in (0, 4) else GRIDC)

    u = prog(b, 25, 2.0)   # 再生ヘッド（時間なので一定の速さ）
    for n, (name, fn, col) in enumerate(CURVES):
        r = ease_in_out_cubic(prog(b, 24 + 0.2 * n, 0.9))
        if r > 0:
            us = np.linspace(0, r, max(2, int(260 * r)))
            stroke(c8, [gpt(x, fn(x)) for x in us], 4, closed=False, val=col)
            diamond(c8, gpt(0, 0), 9, WHITE)
            if r >= 1:
                diamond(c8, gpt(1, 1), 9, WHITE)
        # 右側：同じ曲線で動く箱
        y = 270 + n * 130
        stroke(c8, [(TX0, y), (TX1, y)], 2, closed=False, val=GRIDC)
        s = 30 * ease_out_back(prog(b, 24.3 + 0.2 * n, 0.6))
        if s > 0:
            x = TX0 + fn(u) * (TX1 - TX0)
            fill_poly(c8, [(x - s, y - s), (x + s, y - s), (x + s, y + s), (x - s, y + s)], col)

    if b >= 25:
        x = GX0 + u * GW
        stroke(c8, [(x, GY0 - 24), (x, GY0 + GH + 24)], 2, closed=False, val=WHITE)
        for _, fn, col in CURVES:
            disc(c8, gpt(u, fn(u)), 11, val=WHITE)
            disc(c8, gpt(u, fn(u)), 8, val=col)

    c = c8.astype(np.float32)
    label(c, "GRAPH EDITOR", 30, GX0 - 24, 100, WHITE)
    label(c, "value", 18, GX0 - 16, GY0 - 6, AXIS)
    label(c, "time", 18, GX0 + GW, GY0 + GH + 44, AXIS, anchor="r")
    label(c, "PREVIEW", 30, TX0 - 20, 100, WHITE)
    for n, (name, _, col) in enumerate(CURVES):
        label(c, name, 22, TX0 - 20, 270 + n * 130 - 50, col, opacity=prog(b, 24.3 + 0.2 * n, 0.4))
    if b >= 25:
        label(c, f"t={u:.2f}", 18, GX0 + u * GW + 8, GY0 - 12, WHITE)

    # ブラウン管が消えるように、白く潰れて線になり、点になって消える
    t = prog(b, 27.2, SILENCE_BEAT - 27.2)
    if t > 0:
        sy = lerp(1.0, 0.004, ease_in_cubic(t))
        sx = lerp(1.0, 0.01, ease_in_cubic(prog(t, 0.8, 0.2)))
        hh, ww = max(2, int(H * sy)), max(2, int(W * sx))
        small = cv2.resize(c, (ww, hh), interpolation=cv2.INTER_AREA)
        small += (255 - small) * ease_in_cubic(t)
        c = canvas((0, 0, 0))
        y0, x0 = (H - hh) // 2, (W - ww) // 2
        c[y0:y0 + hh, x0:x0 + ww] = small
    return c


# =====================================================================
# シーン5：爆発 → 粒子が集まって文字に（28〜32拍）
# =====================================================================
N_PART = 5000
TEXT_Y = 340
TEXT_SIZE = 220


@functools.lru_cache(maxsize=None)
def particle_setup():
    """一度見えないところに文字を描き、文字の形の点を5,000個拾う"""
    rng = np.random.default_rng(5)
    ys, xs = np.nonzero(place(text_mask("PYTHON", TEXT_SIZE), W / 2, TEXT_Y) > 128)
    sel = rng.choice(len(xs), N_PART, replace=len(xs) < N_PART)
    tgt = np.stack([xs[sel], ys[sel]], 1).astype(np.float64) + rng.uniform(-0.5, 0.5, (N_PART, 2))
    ang = rng.uniform(0, 2 * np.pi, N_PART)
    spd = 120 + 560 * rng.random(N_PART) ** 0.8
    delay = rng.uniform(0, 0.45, N_PART)
    swirl = rng.uniform(-1.2, 1.2, N_PART)
    colors = gradient((tgt[:, 0] - tgt[:, 0].min()) / np.ptp(tgt[:, 0]))
    return tgt, ang, spd, delay, swirl, colors


def particles_at(b):
    tgt, ang, spd, delay, swirl, colors = particle_setup()
    e = ease_out_expo(prog(b, 28, 1.4))
    a = ang + swirl * 0.8 * e
    burst = np.stack([W / 2 + np.cos(a) * spd * e, H / 2 + np.sin(a) * spd * e], 1)
    g = np.clip((b - 29.0 - delay) / 1.3, 0, 1)
    g = np.where(g < 0.5, 4 * g ** 3, 1 - (-2 * g + 2) ** 3 / 2)
    return burst + (tgt - burst) * g[:, None], colors


def draw_particles(c, pos, colors, glow=1.6):
    xi = np.round(pos[:, 0]).astype(np.int64)
    yi = np.round(pos[:, 1]).astype(np.int64)
    ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    idx = yi[ok] * W + xi[ok]
    cnt = np.bincount(idx, minlength=H * W).reshape(H, W).astype(np.float32)
    rgb = np.stack([np.bincount(idx, weights=colors[ok, ch], minlength=H * W)
                    for ch in range(3)], -1).reshape(H, W, 3).astype(np.float32)
    rgb /= np.maximum(cnt, 1)[..., None]
    k = np.ones((3, 3), np.uint8)
    a = cv2.dilate(np.minimum(cnt, 1), k)
    rgb = cv2.dilate(rgb, k)
    comp(c, a, rgb)
    c += cv2.GaussianBlur(rgb * a[..., None], (0, 0), 5) * glow


def scene_e(b):
    c = canvas(INK)
    dot_grid(c, b, (34, 34, 62))
    for k, col in enumerate((ORANGE, YELLOW, CYAN)):   # 衝撃波
        t = prog(b, 28 + 0.08 * k, 1.3)
        if 0 < t < 1:
            m = blank()
            disc(m, (W / 2, H / 2), ease_out_expo(t) * (650 + 180 * k), 34 * (1 - t) + 1)
            comp(c, m, col, 1 - t)

    pos, colors = particles_at(b)
    draw_particles(c, pos, colors)

    op = prog(b, 30.45, 0.5)
    if op > 0:
        m = place(text_mask("PYTHON", TEXT_SIZE), W / 2, TEXT_Y)
        sticker(c, m, TEXT_GRAD, edge=WHITE, shadow=VIOLET, r=6, off=(10, 10), opacity=op)
        t = prog(b, 30.9, 0.8)
        if 0 < t < 1:   # 光がすっと横切る
            x = lerp(100, 1200, ease_in_out_cubic(t))
            band = blank()
            fill_poly(band, [(x, 0), (x + 70, 0), (x - 130, H), (x - 200, H)])
            comp(c, np.minimum(band, m), WHITE, 0.75)

    t = ease_out_expo(prog(b, 30.6, 0.8))
    label(c, "MADE WITH", 34, W / 2, TEXT_Y - 150 + 24 * (1 - t), WHITE, FONT_TITLE, "c", t)
    sub = "NumPy · OpenCV · Pillow · ffmpeg"
    n = int(len(sub) * prog(b, 30.9, 0.7))
    if n:
        x0 = W / 2 - text_mask(sub, 30, FONT_MONO, pad=2).shape[1] / 2
        cursor = "_" if n < len(sub) and (b * 4) % 1 < 0.5 else ""
        label(c, sub[:n] + cursor, 30, x0, TEXT_Y + 150, (205, 205, 225))

    flash = (1 - prog(b, 28, 0.4)) ** 2 if b >= 28 else 0
    c += (255 - c) * flash
    c *= 1 - ease_in_cubic(prog(b, 31.6, 0.4))
    return c


# =====================================================================
# 場面のつなぎ（斜めワイプ・アイリス）
# =====================================================================
def wipe(a_img, b_img, t, band=90):
    e = lerp(-band - 20, W + H * 0.5 + 40, ease_in_out_cubic(t))
    m = blank()
    fill_poly(m, [(-10, -10), (e, -10), (e - (H + 20) * 0.5, H + 10), (-10, H + 10)])
    stripe = blank()
    fill_poly(stripe, [(e, -10), (e + band, -10), (e + band - (H + 20) * 0.5, H + 10), (e - (H + 20) * 0.5, H + 10)])
    comp(a_img, stripe, ORANGE)
    comp(a_img, m, b_img)
    return a_img


def iris(a_img, b_img, t, ring=26):
    r = ease_in_out_cubic(t) * 790
    m = blank()
    disc(m, (W / 2, H / 2), r + ring)
    comp(a_img, m, PINK)
    m = blank()
    disc(m, (W / 2, H / 2), r)
    comp(a_img, m, b_img)
    return a_img


def compose(b):
    if b < 7.5:
        return scene_a(b)
    if b < 8:
        return wipe(scene_a(b), scene_b(b), prog(b, 7.5, 0.5))
    if b < 15.5:
        return scene_b(b)
    if b < 16:
        return iris(scene_b(b), scene_c(b), prog(b, 15.5, 0.5))
    if b < 24:
        return scene_c(b)
    if b < 28:
        return scene_d(b)
    return scene_e(b)


def scene_no(b):
    return 1 + (b >= 8) + (b >= 16) + (b >= 24) + (b >= 28)


# =====================================================================
# 仕上げ（グリッチ・色収差・周辺減光・フィルム粒子・四隅の表示）
# =====================================================================
GLITCHES = ((8.0, 0.25), (12.0, 0.08), (16.0, 0.22), (20.0, 0.08), (24.0, 0.3), (28.0, 0.5))


def glitch_amount(b):
    return max((1 - (b - s) / l for s, l in GLITCHES if s <= b < s + l), default=0.0)


def hud(img, f, b):
    """四隅の表示。白黒反転（差の絶対値）で重ねるので、どんな背景でも読める"""
    sec, fr = divmod(f, FPS)
    items = ((f"PY/MOTION  {BPM} BPM", 28, 30, "l"),
             (f"{sec // 60:02d}:{sec % 60:02d}:{fr:02d}", W - 28, 30, "r"),
             (f"BEAT {min(int(b) + 1, BEATS):02d}/{BEATS}", 28, H - 32, "l"),
             (f"SCENE {scene_no(b):02d}/05", W - 28, H - 32, "r"))
    m = blank()
    for text, x, y, anchor in items:
        src = text_mask(text, 20, FONT_MONO, pad=2)
        h, w = src.shape
        x = x - w if anchor == "r" else x
        m[y - h // 2:y - h // 2 + h, x:x + w] = src
    for i in range(4):   # 小節の中の何拍目かを四角で
        x = 190 + i * 16
        if i == int(b) % 4:
            m[H - 38:H - 26, x:x + 12] = 255
        else:
            m[H - 38:H - 26, x:x + 12][[0, -1]] = 255
            m[H - 38:H - 26, x:x + 12][:, [0, -1]] = 255
    for rows in (slice(0, 60), slice(H - 60, H)):
        a = m[rows].astype(np.float32)[..., None] / 255 * 0.9
        sub = img[rows]
        sub += a * (np.abs(255 - sub) - sub)


def post(img, f):
    b = f / FPS / SPB
    rng = np.random.default_rng(f * 7919 + 1)
    g = glitch_amount(b)
    if g > 0:   # 画面を横の帯に切ってずらす
        y = 0
        while y < H:
            h = int(rng.integers(6, 60))
            if rng.random() < 0.6:
                img[y:y + h] = np.roll(img[y:y + h], int(rng.normal(0, 1) * 80 * g), axis=1)
            y += h
    k = int(round(1.5 + 3 * beat_pulse(b) + 16 * g))   # 色収差：赤と青を左右にずらす
    img[..., 0] = np.roll(img[..., 0], k, axis=1)
    img[..., 2] = np.roll(img[..., 2], -k, axis=1)
    img *= VIGNETTE[..., None]
    ox, oy = rng.integers(0, 64, 2)
    img += GRAIN[oy:oy + H, ox:ox + W, None]
    np.clip(img, 0, 255, out=img)
    hud(img, f, b)
    return np.clip(img, 0, 255).astype(np.uint8)


SHUTTER = 0.5   # シャッターが開いている長さ（コマに対する割合）


def render_frame(f, blur=4):
    """モーションブラー：1コマを少しずつ時間をずらして blur 回描き、平均する"""
    acc = None
    for s in range(blur):
        dt = ((s + 0.5) / blur - 0.5) * SHUTTER if blur > 1 else 0.0
        img = compose((f + dt) / FPS / SPB)
        acc = img if acc is None else acc + img
    return post(acc / blur, f)
