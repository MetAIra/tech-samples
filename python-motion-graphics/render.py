"""1コマずつ描いて ffmpeg に流し込み、計算で作った音楽と合わせて MP4 にする。

使い方:
  python render.py                  # 本番（モーションブラー4回描き）
  python render.py --blur 1         # 速いプレビュー
  python render.py --still 2.5 12   # 指定した拍の1枚をPNGで確認
"""
import argparse
import functools
import os
import shutil
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from PIL import Image

import make_audio
import scenes
from common import FPS, H, N_FRAMES, SPB, W

OUT = Path(__file__).resolve().parent / "output"


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("ffmpeg が見つかりません。インストールするか `pip install imageio-ffmpeg` してください。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blur", type=int, default=4, help="モーションブラーで1コマを何回描くか")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--still", type=float, nargs="+", help="指定した拍の1枚をPNGで書き出す")
    ap.add_argument("--out", default=str(OUT / "motion.mp4"))
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    if args.still:
        for b in args.still:
            img = scenes.render_frame(round(b * SPB * FPS), args.blur)
            p = OUT / f"still_{b:05.2f}.png"
            Image.fromarray(img).save(p)
            print(p)
        return

    t0 = time.time()
    wav = make_audio.main(OUT / "music.wav")
    print(f"音楽: {wav}  ({time.time() - t0:.1f}s)")

    cmd = [find_ffmpeg(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav),
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    job = functools.partial(scenes.render_frame, blur=args.blur)
    with Pool(args.workers) as pool:
        for i, frame in enumerate(pool.imap(job, range(N_FRAMES), chunksize=2)):
            proc.stdin.write(frame.tobytes())
            if (i + 1) % 30 == 0 or i + 1 == N_FRAMES:
                print(f"{i + 1}/{N_FRAMES} コマ  {time.time() - t0:5.1f}s", flush=True)
    proc.stdin.close()
    proc.wait()
    print(f"完成: {args.out}  ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
