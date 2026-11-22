"""Soundtrack for promo.html: French voice-over + synthesized music bed + UI sound effects.

Usage: python audio.py cues.json out.wav
  cues.json = window.AUDIO from promo.html (dumped by render.js): {vo:[[t,name]], sfx:[[t,type]], duration}

Voice-over: Piper TTS, voice fr_FR-siwis-medium (rhasspy/piper-voices). The clips are
generated once into $SCR/vo/<name>.wav when missing (needs PIPER=/path/to/piper and
PIPER_VOICE=/path/to/fr_FR-siwis-medium.onnx). Music and effects are synthesized here
with numpy (no samples, no third-party audio). Output: 48 kHz stereo 16-bit WAV.
"""

import json
import os
import subprocess
import sys
import wave

import numpy as np

SR = 48000
SCR = "/tmp/claude-0/-home-user-BirdS/27eb98ec-b9ba-5cf1-a125-8008c93c0d55/scratchpad/video2"
VO_DIR = os.path.join(SCR, "vo")
VO_TEXT = {
    "hook1": "Toujours plus gros ?",
    "hook2": "Nous, on fait tout petit.",
    "mail": "Il écrit vos mails. Vous relisez.",
    "deck": "Il prépare vos présentations.",
    "invoice": "Il comprend vos photos de factures.",
    "receipt": "Et chaque réponse affiche ce qu'elle a coûté.",
    "credo": "Nous créons de tout petits modèles, performants et sobres, plutôt que toujours plus gros.",
}
rng = np.random.default_rng(7)


def read_wav(path):
    w = wave.open(path)
    sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
    x = np.frombuffer(w.readframes(n), np.int16).astype(np.float64) / 32768
    if ch == 2:
        x = x.reshape(-1, 2).mean(1)
    if sr != SR:
        m = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x) - 1, m), np.arange(len(x)), x)
    return x


def vo_clip(name):
    path = os.path.join(VO_DIR, name + ".wav")
    if not os.path.exists(path):
        os.makedirs(VO_DIR, exist_ok=True)
        subprocess.run(
            [os.environ["PIPER"], "-m", os.environ["PIPER_VOICE"], "-f", path],
            input=VO_TEXT[name].encode(),
            check=True,
            capture_output=True,
        )
    x = read_wav(path)
    # trim leading silence, light compression-ish normalisation
    nz = np.nonzero(np.abs(x) > 0.01)[0]
    if len(nz):
        x = x[max(0, nz[0] - int(0.02 * SR)) :]
    return x / (np.max(np.abs(x)) + 1e-9) * 0.9


def env_adsr(n, a, r):
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def note(f):
    return 440.0 * 2 ** ((f - 69) / 12)


def tone(freq, dur, harm=(1.0, 0.3, 0.12), detune=0.0):
    t = np.arange(int(dur * SR)) / SR
    out = np.zeros_like(t)
    for k, amp in enumerate(harm, 1):
        out += amp * np.sin(2 * np.pi * freq * k * (1 + detune) * t)
    return out


def add(buf, x, t0, gain=1.0):
    i = int(t0 * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(x))
    buf[i:j] += gain * x[: j - i]


# ---------------- music ----------------
def music(dur):
    L = np.zeros(int(dur * SR))
    R = np.zeros_like(L)
    beat = 0.6  # 100 bpm
    bar = 4 * beat
    # F maj7, A min7, D min7, C add9 (MIDI)
    chords = [[53, 57, 60, 64], [57, 60, 64, 67], [50, 57, 60, 65], [48, 55, 62, 64]]
    roots = [41, 45, 38, 36]
    t = 0.0
    k = 0
    while t < 25.0:
        ch = chords[k % 4]
        for m in ch:
            for side, det in ((L, -0.0025), (R, 0.0025)):
                x = tone(note(m), bar + 0.5, harm=(1.0, 0.25, 0.08), detune=det) * env_adsr(
                    int((bar + 0.5) * SR), 0.35, 0.6
                )
                add(side, x, t, 0.05)
        b = tone(note(roots[k % 4]), bar, harm=(1.0, 0.4)) * env_adsr(int(bar * SR), 0.02, 0.3)
        b *= np.exp(-np.arange(len(b)) / SR / 1.6)
        if t >= 3.0:
            add(L, b, t, 0.11)
            add(R, b, t, 0.11)
        # plucked arpeggio, 8th notes, from the drop at 3.0 s
        if t >= 2.9:
            arp = [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[3] + 12, ch[2] + 12, ch[1] + 12, ch[3] + 12, ch[2] + 24]
            for i, m in enumerate(arp):
                tt = t + i * beat / 2
                if tt >= 24.9:
                    break
                x = tone(note(m), 0.4, harm=(1.0, 0.18)) * np.exp(-np.arange(int(0.4 * SR)) / SR / 0.11)
                x *= env_adsr(len(x), 0.004, 0.05)
                pan = 0.35 if i % 2 else -0.35
                add(L, x, tt, 0.05 * (1 - pan))
                add(R, x, tt, 0.05 * (1 + pan))
        # soft kick + hat from the drop
        if t >= 3.0:
            for i in range(4):
                tt = t + i * beat
                if tt >= 24.8:
                    break
                n = int(0.22 * SR)
                tk = np.arange(n) / SR
                f = 50 + 70 * np.exp(-tk / 0.03)
                kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tk / 0.09)
                add(L, kick, tt, 0.16)
                add(R, kick, tt, 0.16)
                hn = int(0.05 * SR)
                hat = np.diff(rng.standard_normal(hn + 1)) * np.exp(-np.arange(hn) / SR / 0.012)
                add(L, hat, tt + beat / 2, 0.012)
                add(R, hat, tt + beat / 2, 0.016)
        t += bar
        k += 1
    # hook (0-3 s): rising pad on F, no drums
    for m in (53, 60, 64, 69):
        x = tone(note(m), 3.2, harm=(1.0, 0.2)) * env_adsr(int(3.2 * SR), 0.8, 0.4)
        add(L, x, 0.0, 0.03)
        add(R, x, 0.0, 0.03)
    # credo (25-31 s): sustained, warm Fmaj9 -> Cmaj9 -> Fadd9 tag
    for t0, ch, d in (
        (25.0, [41, 53, 57, 60, 64, 67], 3.2),
        (28.0, [36, 48, 55, 59, 62, 64], 3.3),
        (31.1, [41, 53, 60, 64, 67, 72], 1.6),
    ):
        for m in ch:
            for side, det in ((L, -0.002), (R, 0.002)):
                x = tone(note(m), d + 0.4, harm=(1.0, 0.2), detune=det) * env_adsr(int((d + 0.4) * SR), 0.5, 0.8)
                add(side, x, t0, 0.045)
    for i in range(10):  # slow bell arpeggio under the credo
        tt = 25.3 + i * 0.6
        m = [72, 76, 79, 84, 79, 76, 72, 74, 79, 84][i]
        x = tone(note(m), 1.2, harm=(1.0, 0.1)) * np.exp(-np.arange(int(1.2 * SR)) / SR / 0.4)
        add(L, x, tt, 0.022)
        add(R, x, tt, 0.022)
    return L, R


# ---------------- sound effects ----------------
def noise(d):
    return rng.standard_normal(int(d * SR))


def sweep_noise(d, f0, f1, peak=0.5):
    n = int(d * SR)
    x = noise(d)
    # crude band-pass: difference of two one-pole low-passes with moving cutoff
    y = np.empty(n)
    a1 = a2 = 0.0
    for i in range(n):
        p = i / n
        fc = f0 + (f1 - f0) * p
        c1 = 1 - np.exp(-2 * np.pi * fc * 1.6 / SR)
        c2 = 1 - np.exp(-2 * np.pi * fc * 0.6 / SR)
        a1 += c1 * (x[i] - a1)
        a2 += c2 * (x[i] - a2)
        y[i] = a1 - a2
    e = np.sin(np.pi * np.clip(np.arange(n) / (n * peak), 0, 1) / 2) * np.clip(
        (n - np.arange(n)) / (n * (1 - peak)), 0, 1
    )
    return y * e / (np.max(np.abs(y)) + 1e-9)


def chirp(f0, f1, d, decay):
    n = int(d * SR)
    t = np.arange(n) / SR
    f = f0 * (f1 / f0) ** (t / d)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / decay) * env_adsr(n, 0.003, 0.02)


def bell(f, d, decay):
    t = np.arange(int(d * SR)) / SR
    x = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t / (decay / 3))
    return x * np.exp(-t / decay) * env_adsr(len(t), 0.002, 0.03)


def sfx(kind):
    if kind == "whoosh":
        return sweep_noise(0.45, 300, 2400, 0.6) * 0.32
    if kind == "whip":
        return sweep_noise(0.22, 500, 3500, 0.5) * 0.26
    if kind == "swish":
        return sweep_noise(0.16, 1200, 4000, 0.4) * 0.16
    if kind == "boom":
        n = int(0.8 * SR)
        t = np.arange(n) / SR
        f = 45 + 60 * np.exp(-t / 0.05)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.28) * 0.7
    if kind == "squeeze":
        return chirp(900, 220, 0.28, 0.2) * 0.22
    if kind == "pop":
        out = np.pad(bell(1760, 0.35, 0.12), (int(0.02 * SR), 0))[: int(0.35 * SR)] * 0.12
        c = chirp(700, 1400, 0.07, 0.05) * 0.22
        out[: len(c)] += c
        return out
    if kind == "send":
        return chirp(420, 1500, 0.14, 0.1) * 0.22 + sweep_noise(0.14, 800, 3000, 0.3) * 0.05
    if kind == "tick":
        return bell(2400, 0.08, 0.02) * 0.18
    if kind == "shimmer":
        out = np.zeros(int(1.2 * SR))
        for i, f in enumerate((2093, 2637, 3136, 4186)):
            b = bell(f, 1.0, 0.35) * 0.06
            s = int(i * 0.06 * SR)
            out[s : s + len(b)] += b[: len(out) - s]
        return out
    if kind == "sting":
        out = np.zeros(int(1.6 * SR))
        for f in (349.2, 523.3, 659.3, 1046.5):
            b = bell(f, 1.6, 0.6) * 0.07
            out[: len(b)] += b
        t = np.arange(len(out)) / SR
        out += np.sin(2 * np.pi * 43.65 * t) * np.exp(-t / 0.5) * 0.25
        return out
    raise ValueError(kind)


def main():
    cues = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    dur = cues["duration"]
    n = int(dur * SR)
    mL, mR = music(dur)
    voice = np.zeros(n)
    for t0, name in cues["vo"]:
        add(voice, vo_clip(name), t0, 1.0)
    fx = np.zeros(n)
    for t0, kind in cues["sfx"]:
        add(fx, sfx(kind), t0, 1.0)
    # duck the music under the voice (attack 60 ms, release 300 ms)
    lvl = np.abs(voice) > 0.02
    env = np.zeros(n)
    acc = 0.0
    up, dn = 1 - np.exp(-1 / (0.06 * SR)), 1 - np.exp(-1 / (0.3 * SR))
    hold = 0
    for i in range(n):
        if lvl[i]:
            hold = int(0.15 * SR)
        tgt = 1.0 if hold > 0 else 0.0
        hold -= 1
        acc += (up if tgt > acc else dn) * (tgt - acc)
        env[i] = acc
    duck = 1 - 0.55 * env
    L = mL * duck + voice * 0.82 + fx * 0.9
    R = mR * duck + voice * 0.82 + fx * 0.9
    # fades
    fi, fo = int(0.03 * SR), int(0.5 * SR)
    for ch in (L, R):
        ch[:fi] *= np.linspace(0, 1, fi)
        ch[-fo:] *= np.linspace(1, 0, fo)
    peak = max(np.max(np.abs(L)), np.max(np.abs(R)))
    g = 0.89 / peak
    st = np.stack([L * g, R * g], 1)
    pcm = (np.clip(st, -1, 1) * 32767).astype(np.int16)
    w = wave.open(out, "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
    w.close()
    print("audio", out, f"{dur:.2f}s", "peak gain", round(g, 3))


if __name__ == "__main__":
    main()
