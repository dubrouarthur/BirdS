"""Soundtrack for promo.html (v5): a licensed music track placed on the video's beat grid. No voice.

Usage: python audio.py cues.json out.wav
  cues.json = window.AUDIO from promo.html (dumped by render.js):
    {clips: [[video_t, track_t0, track_t1], ...], fadeOut: [t0, t1], whoosh: [t, ...], duration}

Music: « Bright Tomorrow », John Bartmann, album « Machine Learning » (2021), CC0 1.0 Universal
(see music/LICENSE). 122 BPM, downbeats at 1.882 + n x 1.9672 s in the track.
The edit: the opening swell (track 0.750-1.882 s) under the first title, then, from the first
downbeat, the track from its bar 79 (157.291 s) to its own ending (breakdown, final hit, ring-out).
Both pieces meet on a downbeat with a 25 ms equal-power crossfade, so the grid never slips.
Sound design: two very soft, low-passed air whooshes on the main transitions, about 20 dB under
the music; nothing else.
Mastering: two-pass ffmpeg loudnorm (linear) to -14 LUFS integrated, true peak <= -1 dBTP;
a final true-peak measurement is printed. Output: 48 kHz stereo 24-bit WAV.
"""

import json
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
TRACK = os.path.join(HERE, "music", "John_Bartmann_-_Bright_Tomorrow.mp3")
XF = 0.025  # crossfade at the splice (s)


def decode(path):
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def whoosh(rng, d=0.9, peak=0.62):
    """soft air movement: band-limited noise swelling to `peak` of its length, then falling away."""
    n = int(d * SR)
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    X *= np.exp(-((np.log(f + 1) - np.log(900)) ** 2) / (2 * 0.9**2))  # gentle band around 900 Hz
    x = np.fft.irfft(X, n)
    k = np.arange(n) / n
    e = np.where(k < peak, np.sin(np.pi / 2 * k / peak) ** 2, np.cos(np.pi / 2 * (k - peak) / (1 - peak)) ** 2)
    x = x * e
    return x / (np.max(np.abs(x)) + 1e-9)


def write_wav(path, st, bits=24):
    st = np.clip(st, -1, 1)
    if bits == 24:
        v = (st * (2**23 - 1)).astype(np.int32).reshape(-1)
        b = np.stack([(v & 0xFF), (v >> 8) & 0xFF, (v >> 16) & 0xFF], 1).astype(np.uint8).tobytes()
    else:
        b = (st * 32767).astype(np.int16).tobytes()
    w = wave.open(path, "wb")
    w.setnchannels(2)
    w.setsampwidth(bits // 8)
    w.setframerate(SR)
    w.writeframes(b)
    w.close()


def loudnorm(src, dst):
    target = "I=-14:TP=-1.5:LRA=11"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", src, "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    m = json.loads(r[r.rindex("{") : r.rindex("}") + 1])
    af = (
        f"loudnorm={target}:linear=true:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-af", af, "-ar", str(SR), "-c:a", "pcm_s24le", dst],
        check=True,
    )
    return m


def measure(path):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    tail = r[r.rindex("Summary:") :]
    return " ".join(tail.split())


def main():
    cues = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    dur = cues["duration"]
    n = int(round(dur * SR))
    track = decode(TRACK)
    mix = np.zeros((n, 2))
    x = int(XF * SR)
    for k, (vt, a, b) in enumerate(cues["clips"]):
        last = k == len(cues["clips"]) - 1
        i0 = int(round(vt * SR))
        # each clip starts XF/2 early and ends XF/2 late, so the two overlap around the splice point
        ta = int(round(a * SR)) - (x // 2 if k else 0)
        tb = int(round(b * SR)) + (0 if last else x // 2)
        seg = track[max(0, ta) : tb].copy()
        dst = i0 - (x // 2 if k else 0)
        if k:  # equal-power fade in
            seg[:x] *= np.sin(np.linspace(0, np.pi / 2, x))[:, None]
        if not last:
            seg[-x:] *= np.cos(np.linspace(0, np.pi / 2, x))[:, None]
        j = min(n, dst + len(seg))
        mix[dst:j] += seg[: j - dst]
    # a 10 ms fade-in from silence, then the fade-out under the end card
    fi = int(0.01 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    f0, f1 = cues["fadeOut"]
    i0, i1 = int(f0 * SR), min(n, int(f1 * SR))
    mix[i0:i1] *= (np.cos(np.linspace(0, np.pi / 2, i1 - i0)) ** 2)[:, None]
    mix[i1:] = 0
    # two soft whooshes, ending on their cut, about 20 dB under the music's RMS
    rng = np.random.default_rng(5)
    rms = np.sqrt(np.mean(mix**2))
    for t in cues.get("whoosh", []):
        w = whoosh(rng)
        g = rms * 10 ** (-20 / 20) / (np.sqrt(np.mean(w**2)) + 1e-9)
        s = int((t - 0.62 * 0.9) * SR)
        j = min(n, s + len(w))
        mix[s:j, 0] += w[: j - s] * g * 0.95
        mix[s:j, 1] += w[: j - s] * g * 1.05
    with tempfile.TemporaryDirectory() as d:
        raw = os.path.join(d, "raw.wav")
        peak = np.max(np.abs(mix))
        write_wav(raw, mix / max(1.0, peak))
        m = loudnorm(raw, out)
    print("audio", out, f"{dur:.2f}s", "pre:", m["input_i"], "LUFS", m["input_tp"], "dBTP")
    print("final:", measure(out))


if __name__ == "__main__":
    main()
