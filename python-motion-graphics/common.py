"""共通の設定：テンポ・解像度・イージング。
映像も音もすべてここの「拍」を基準に動く。128BPM × 32拍 = ちょうど15秒。
"""
import math

BPM = 128
BEATS = 32
FPS = 30
W, H = 1280, 720
SPB = 60.0 / BPM                   # 1拍の秒数 (0.46875秒)
DURATION = BEATS * SPB             # 15.0秒
N_FRAMES = round(DURATION * FPS)   # 450コマ

DROP_BEAT = 28                     # 爆発する拍
SILENCE_SEC = 0.1                  # 爆発直前の完全な無音
SILENCE_BEAT = DROP_BEAT - SILENCE_SEC / SPB


def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def prog(b, start, length):
    """拍 b が start から length 拍かけて 0→1 に進む割合"""
    return clamp01((b - start) / length)


def lerp(a, b, t):
    return a + (b - a) * t


# ---- イージング（0→1 の進み方を曲げる数式） ----
def ease_out_expo(x):          # 最初速く、最後ゆっくり止まる
    x = clamp01(x)
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def ease_in_expo(x):
    x = clamp01(x)
    return 0.0 if x <= 0 else 2 ** (10 * x - 10)


def ease_out_back(x, s=1.70158):   # 少し行き過ぎて戻る
    x = clamp01(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def ease_out_bounce(x):        # 跳ねて止まる
    x = clamp01(x)
    n1, d1 = 7.5625, 2.75
    if x < 1 / d1:
        return n1 * x * x
    if x < 2 / d1:
        x -= 1.5 / d1
        return n1 * x * x + 0.75
    if x < 2.5 / d1:
        x -= 2.25 / d1
        return n1 * x * x + 0.9375
    x -= 2.625 / d1
    return n1 * x * x + 0.984375


def ease_in_cubic(x):
    return clamp01(x) ** 3


def ease_in_out_cubic(x):
    x = clamp01(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def beat_pulse(b, decay=5.0):
    """拍の瞬間に 1 へ跳ね上がり、次の拍に向けて減衰する値"""
    if b < 0:
        return 0.0
    return math.exp(-decay * (b % 1.0))
