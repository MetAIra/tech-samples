"""音楽：楽器の音を波の計算で作り、映像と同じ拍番号で鳴らす。"""
import math
import wave
from pathlib import Path

import numpy as np

from common import DROP_BEAT, DURATION, SILENCE_BEAT, SPB

SR = 44100
N = int(round(DURATION * SR))
rng = np.random.default_rng(11)


def at(beat):
    return int(round(beat * SPB * SR))


def tvec(sec):
    return np.arange(int(sec * SR)) / SR


def mix(bus, sig, beat, gain=1.0, pan=0.0):
    """bus の beat 拍目から sig を足し込む（pan: -1 左 〜 +1 右）"""
    if sig.ndim == 1:
        a = (pan + 1) * math.pi / 4
        sig = np.stack([sig * math.cos(a), sig * math.sin(a)], 1) * math.sqrt(2)
    start = at(beat)
    end = min(N, start + len(sig))
    if start < end:
        bus[start:end] += gain * sig[:end - start]


def lowpass(x, n):
    """移動平均（こもった音にする簡易フィルタ）"""
    return x if n <= 1 else np.convolve(x, np.ones(n) / n, mode="same")


def highpass(x, n=2):
    return x - lowpass(x, n)


def noise(sec):
    return rng.standard_normal(int(sec * SR))


# ---- 楽器 ----
def kick(length=0.42, f_hi=150, f_lo=46, decay=6.5):
    """低い音が一瞬で下がっていく波"""
    t = tvec(length)
    f = f_lo + (f_hi - f_lo) * np.exp(-t * 32)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * decay)
    click = highpass(noise(length)) * np.exp(-t * 300) * 0.4
    return np.tanh((body + click) * 1.6)


def hat(decay=45, length=0.12):
    """ザーッという雑音の低い成分を削って、短く切る"""
    t = tvec(length)
    n = highpass(highpass(noise(length)))
    return n / np.abs(n).max() * np.exp(-t * decay)


def snare(length=0.3):
    t = tvec(length)
    n = lowpass(highpass(noise(length)), 3)
    tone = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30)
    return n / np.abs(n).max() * np.exp(-t * 16) + 0.6 * tone


def whoosh(length):
    """「シュッ」：だんだん大きく明るくなる雑音。拍の頭でスパッと切れる"""
    x = np.linspace(0, 1, int(length * SR))
    n = noise(length)
    s = lowpass(n, 24) * 3 * (1 - x) + highpass(n) * x
    return s * x ** 2.5 * np.minimum(1, (1 - x) * 30)


def swish(length=0.28):
    x = np.linspace(0, 1, int(length * SR))
    n = noise(length)
    s = highpass(n) * (1 - x) + lowpass(n, 12) * 2 * x
    return s * np.exp(-x * 5) * (1 - np.exp(-x * 60))


def boom():
    """爆発：長く伸びるキック＋シンバルのような雑音"""
    t = tvec(2.0)
    crash = highpass(noise(2.0)) * np.exp(-t * 2.2) * 0.45
    k = np.zeros(len(t))
    k[:int(1.6 * SR)] = kick(1.6, 130, 32, 2.0)
    return k * 1.2 + crash


def ping(midi, length=0.5):
    t = tvec(length)
    f = midi_hz(midi)
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2.76 * t)) * np.exp(-t * 9)


def midi_hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def supersaw(midi, sec, harmonics, voices=7, cents=16):
    """少しずつ音程をずらしたノコギリ波を7本重ねる（倍音の数で明るさを調整）"""
    t = tvec(sec)
    out = np.zeros((len(t), 2))
    f0 = midi_hz(midi)
    for v in range(voices):
        d = (v - (voices - 1) / 2) / ((voices - 1) / 2)       # -1 〜 1
        f = f0 * 2 ** (d * cents / 1200)
        ph = rng.uniform(0, 2 * np.pi)
        s = np.zeros(len(t))
        for k in range(1, harmonics + 1):
            if k * f > SR * 0.45:
                break
            s += np.sin(2 * np.pi * k * f * t + k * ph) / k
        a = (d * 0.8 + 1) * math.pi / 4
        out[:, 0] += s * math.cos(a)
        out[:, 1] += s * math.sin(a)
    return out / voices


def bass(midi, sec):
    t = tvec(sec)
    f = midi_hz(midi)
    return np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)


def envelope(n, attack=0.015, release=0.08):
    e = np.ones(n)
    a, r = int(attack * SR), int(release * SR)
    e[:a] = np.linspace(0, 1, a)
    e[-r:] *= np.linspace(1, 0, r)
    return e


# 1小節（4拍）ごとのコード：Am7 Fmaj7 C G | Am7 Fmaj7 C | Am(add9) で決め
PROG = [([57, 60, 64, 67], 33), ([53, 57, 60, 64], 29), ([55, 60, 64, 67], 36), ([55, 59, 62, 67], 31),
        ([57, 60, 64, 67], 33), ([53, 57, 60, 64], 29), ([55, 60, 64, 67], 36), ([57, 64, 69, 71, 76], 33)]
BRIGHT = [4, 5, 7, 9, 11, 13, 15, 18]   # 小節ごとの倍音の数 → だんだん明るく開いていく


def build():
    drums = np.zeros((N, 2))
    music = np.zeros((N, 2))
    fx = np.zeros((N, 2))

    # ---- ドラム ----
    for beat in range(32):
        if beat != DROP_BEAT:
            mix(drums, kick(), beat, 0.95)
    mix(drums, boom(), DROP_BEAT, 1.1)
    for i in range(32):
        mix(drums, hat(), i + 0.5, 0.22 if i < 28 else 0.3, pan=0.25)
    for b in np.arange(16, 27.75, 0.25):
        if b % 0.5:
            mix(drums, hat(80), b, 0.08, pan=-0.35)
    for beat in list(range(8, 28)) + [29, 31]:
        if beat % 4 in (1, 3):
            mix(drums, snare(), beat, 0.5)
    roll = list(np.arange(26, 27, 0.25)) + list(np.arange(27, 27.75, 0.125))
    for b in roll:   # 爆発前のスネアロール
        mix(drums, snare(0.15), b, 0.1 + 0.4 * (b - 26) / 1.75)

    # ---- コードとベース ----
    for bar, (notes, root) in enumerate(PROG):
        sec = 4 * SPB
        env = envelope(int(sec * SR))[:, None]
        for m in notes:
            mix(music, supersaw(m, sec, BRIGHT[bar]) * env, bar * 4, 0.16)
        if bar >= 2:
            mix(music, bass(root, sec) * env[:, 0], bar * 4, 0.3)

    # キックが鳴るたびに他の音を一瞬小さくする（うねり）
    since = (np.arange(N) / SR) % SPB
    music *= (1 - 0.7 * np.exp(-since / 0.11))[:, None]

    # ---- 効果音 ----
    for b, pan in ((0, -0.5), (2, 0.0), (4, 0.5)):          # 文字が出る瞬間
        mix(fx, swish(), b, 0.35, pan)
    for b in (9, 11, 13, 15):                               # 図形の変形
        mix(fx, swish(0.22), b, 0.25, pan=0.3 if b % 4 == 1 else -0.3)
    mix(fx, whoosh(SPB), 7, 0.5)                            # 場面転換へ向かう「シュッ」
    mix(fx, whoosh(SPB), 15, 0.5)
    mix(fx, whoosh(0.5 * SPB), 23.5, 0.45)
    rise = (SILENCE_BEAT - 24) * SPB                        # 爆発まで上がっていく音
    x = np.linspace(0, 1, int(rise * SR))
    sweep = np.sin(2 * np.pi * np.cumsum(200 * 9 ** x) / SR) * 0.3 + highpass(noise(rise)) * 0.5
    mix(fx, sweep * x ** 2, 24, 0.5)
    prng = np.random.default_rng(4)                         # 粒子が集まるキラキラ
    for _ in range(36):
        b = prng.uniform(29, 30.6)
        mix(fx, ping(int(prng.choice([81, 84, 86, 88, 91, 93]))), b, 0.06, pan=prng.uniform(-0.9, 0.9))
    mix(fx, ping(81, 2.0) + ping(88, 2.0), 30.5, 0.25)      # 文字が完成した「チーン」

    master = drums + music * 0.9 + fx

    # 爆発の直前に 0.1 秒だけ完全な無音
    s0, s1 = at(SILENCE_BEAT), at(DROP_BEAT)
    master[s0 - 64:s0] *= np.linspace(1, 0, 64)[:, None]
    master[s0:s1] = 0
    fade = int(0.4 * SR)
    master[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2

    master = np.tanh(master * 1.1)
    return master / np.abs(master).max() * 0.93


def main(path):
    audio = build()
    pcm = (audio * 32767).astype(np.int16)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


if __name__ == "__main__":
    print(main(Path(__file__).resolve().parent / "output" / "music.wav"))
