"""Soundtrack for promo.html (v3): rhythmic synthesized music bed + UI sound effects. No voice.

Usage: python audio.py cues.json out.wav
  cues.json = window.AUDIO from promo.html (dumped by render.js):
    {bpm, music:{drop, brk, build, drop2, end}, sfx:[[t, type]], duration}

Everything is synthesized here with numpy (no samples, no third-party audio, no TTS), so the
track is royalty-free by construction. 120 BPM, A minor (Am - F - C - G), bar downbeats at
0.5 + 2k s so the picture cuts land on downbeats. Output: 48 kHz stereo 16-bit WAV.

Arrangement
  0.0 - drop   intro: word hits, an "inflating" riser, plucks, then a filtered four-on-the-floor
               and a riser + snare roll into the drop
  drop - brk   full groove: kick, clap, hats, pumping bass, off-beat chord stabs, arp
  brk - build  breakdown under the credo: pad + bells + soft hats, riser
  build-drop2  two-beat snare build
  drop2 - end  final groove (F - G) and a C major hit at `end`, ringing out
"""

import json
import sys
import wave

import numpy as np

SR = 48000
rng = np.random.default_rng(11)


# ---------------- primitives ----------------
def note(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tt(d):
    return np.arange(int(d * SR)) / SR


def add(buf, x, t0, gain=1.0):
    i = int(round(t0 * SR))
    if i >= len(buf) or i + len(x) <= 0:
        return
    if i < 0:
        x, i = x[-i:], 0
    j = min(len(buf), i + len(x))
    buf[i:j] += gain * x[: j - i]


def env(n, a, r):
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, min(n, int(r * SR)))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def saw(f, d, nh=14, bright=1.0, detune=0.0, phase=0.0):
    """band-limited-ish saw by additive synthesis; bright<1 rolls off highs."""
    t = tt(d)
    out = np.zeros_like(t)
    for k in range(1, nh + 1):
        if f * k > 16000:
            break
        out += np.sin(2 * np.pi * f * k * (1 + detune) * t + phase * k) / k * bright ** (k - 1)
    return out


def lowpass(x, fc):
    """one-pole low-pass with a (possibly time-varying) cutoff array or scalar."""
    fc = np.broadcast_to(np.asarray(fc, float), x.shape)
    a = 1 - np.exp(-2 * np.pi * fc / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def band(x, lo, hi):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def noise(d):
    return rng.standard_normal(int(d * SR))


# ---------------- drums ----------------
def kick(d=0.42, punch=1.0):
    t = tt(d)
    f = 46 + 130 * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.18)
    click = band(noise(0.012), 1500, 6000) * np.exp(-tt(0.012) / 0.003) * 0.5
    body[: len(click)] += click * punch
    return np.tanh(body * 1.6) * env(len(t), 0.001, 0.05)


def clap():
    d = 0.32
    n = noise(d)
    n = band(n, 900, 5200)
    t = tt(d)
    e = np.exp(-t / 0.11)
    for o in (0.0, 0.011, 0.022):  # three quick re-triggers
        e += 0.8 * np.exp(-np.clip(t - o, 0, None) / 0.006) * (t >= o)
    x = n * e
    return x / (np.max(np.abs(x)) + 1e-9)


def snare(d=0.18):
    t = tt(d)
    x = band(noise(d), 1200, 8000) * np.exp(-t / 0.05) + 0.4 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.04)
    return x / (np.max(np.abs(x)) + 1e-9)


def hat(d=0.05, decay=0.014):
    x = band(noise(d), 7000, 16000) * np.exp(-tt(d) / decay)
    return x / (np.max(np.abs(x)) + 1e-9)


# ---------------- tonal ----------------
CHORDS = {  # voicings (MIDI)
    "Am": [57, 60, 64, 69],
    "F": [57, 60, 65, 69],
    "C": [55, 60, 64, 67],
    "G": [55, 59, 62, 67],
}
ROOTS = {"Am": 45, "F": 41, "C": 48, "G": 43}
PROG = ["Am", "F", "C", "G"]


def stab(ch, d=0.22, gain=1.0):
    """detuned super-saw chord stab, plucky."""
    n = int(d * SR)
    out = np.zeros(n)
    for m in CHORDS[ch]:
        for det in (-0.006, 0.0, 0.006):
            out += saw(note(m), d, nh=10, bright=0.72, detune=det, phase=rng.uniform(0, 6.28))
    e = np.exp(-tt(d) / 0.09) * env(n, 0.003, 0.03)
    return out * e * gain / 12


def pluck(m, d=0.3):
    x = saw(note(m), d, nh=8, bright=0.55) * np.exp(-tt(d) / 0.08)
    return x * env(len(x), 0.002, 0.03)


def bass(m, d):
    x = saw(note(m), d, nh=9, bright=0.6) + 0.8 * np.sin(2 * np.pi * note(m) * tt(d))
    return x * env(len(x), 0.004, 0.04) * np.exp(-tt(d) / 0.35)


def pad(ch, d, gain=1.0):
    out = np.zeros(int(d * SR))
    for m in CHORDS[ch] + [ROOTS[ch] + 12]:
        for det in (-0.004, 0.004):
            out += saw(note(m), d, nh=6, bright=0.45, detune=det, phase=rng.uniform(0, 6.28))
    return out * env(len(out), 0.25, 0.5) * gain / 10


def bell(f, d, decay):
    t = tt(d)
    x = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t / (decay / 3))
    return x * np.exp(-t / decay) * env(len(t), 0.002, 0.03)


def riser(d, f0=400, f1=6000, gain=1.0):
    n = noise(d)
    p = np.linspace(0, 1, len(n))
    fc = f0 * (f1 / f0) ** p
    x = lowpass(n, fc) - lowpass(n, fc * 0.35)
    tone = np.sin(2 * np.pi * np.cumsum(220 * 2 ** (2 * p)) / SR) * 0.25
    x = x / (np.max(np.abs(x)) + 1e-9) + tone
    return x * p**2 * gain


# ---------------- music ----------------
def music(dur, M):
    n = int(dur * SR)
    drums = np.zeros(n)
    sideL = np.zeros(n)  # sidechained material (bass, stabs, pads)
    sideR = np.zeros(n)
    free = np.zeros(n)  # non-ducked (risers, bells)
    beat = 0.5
    bar0 = 0.5
    drop, brk, build, drop2, end = M["drop"], M["brk"], M["build"], M["drop2"], M["end"]
    kicks = []

    def chord_at(t):
        k = int(np.floor((t - bar0) / 2.0)) % 4
        return PROG[k]

    # --- intro (0 - drop) ---
    for _t0 in (0.5, 0.75):  # a pulse under "grossir." rising
        pass
    add(free, riser(0.45, 300, 3000, 0.25), 0.5)
    for i, t0 in enumerate(np.arange(1.0, 2.5, 0.25)):  # plucks under "toute petite."
        m = [69, 72, 76, 81, 76, 72][i % 6]
        add(sideL, pluck(m), t0, 0.10 * (1 - 0.35 * (i % 2)))
        add(sideR, pluck(m), t0 + 0.012, 0.10 * (0.65 + 0.35 * (i % 2)))
    add(sideL, pad("F", 1.6, 0.5), 1.0)
    add(sideR, pad("F", 1.6, 0.5), 1.0)
    # 2.5 - drop: filtered groove builds
    sec = np.zeros(n)
    for t0 in np.arange(2.5, drop, beat):
        kicks.append(t0)
        add(drums, kick(), t0, 0.75)
        add(sec, bass(ROOTS[chord_at(t0)], 0.24), t0 + 0.25, 0.22)
        add(sec, bass(ROOTS[chord_at(t0)] + 12, 0.2), t0 + 0.375, 0.12)
    i0, i1 = int(2.5 * SR), int(drop * SR)
    fc = np.full(n, 300.0)
    fc[i0:i1] = 300 * (6000 / 300) ** np.linspace(0, 1, i1 - i0)
    sec[i0:i1] = lowpass(sec[i0:i1], fc[i0:i1])
    sideL += sec
    sideR += sec
    for c, t0 in (("Am", 2.5), ("F", 3.5)):
        add(sideL, pad(c, 1.1, 0.7), t0)
        add(sideR, pad(c, 1.1, 0.7), t0 + 0.01)
    add(free, riser(1.0, 300, 9000, 0.32), drop - 1.0)
    for k, t0 in enumerate(np.arange(drop - 1.0, drop, 0.0625)):  # snare roll
        add(drums, snare(), t0, 0.06 + 0.2 * (k / 16) ** 2)

    # --- groove helper ---
    def groove(a, b, full=True):
        for t0 in np.arange(a, b - 1e-6, beat):
            kicks.append(t0)
            add(drums, kick(), t0, 0.9)
            bi = int(round((t0 - bar0) / beat)) % 4
            if bi in (1, 3):
                add(drums, clap(), t0, 0.34)
            add(drums, hat(0.12, 0.05), t0 + 0.25, 0.10)  # open hat on the off-beat
            for s in (0.125, 0.375):
                add(drums, hat(), t0 + s, 0.05)
            ch = chord_at(t0)
            r = ROOTS[ch]
            for s, m, g in ((0.25, r, 0.30), (0.375, r + 12, 0.16)):  # off-beat pumping bass
                add(sideL, bass(m, 0.2), t0 + s, g)
                add(sideR, bass(m, 0.2), t0 + s, g)
            add(sideL, stab(ch), t0 + 0.25, 0.34)
            add(sideR, stab(ch), t0 + 0.26, 0.34)
            if full:  # 16th arp, panned
                for q in range(4):
                    m = CHORDS[ch][(bi * 4 + q) % 4] + 12
                    pan = 0.3 if q % 2 else -0.3
                    add(sideL, pluck(m, 0.2), t0 + q * 0.125, 0.035 * (1 - pan))
                    add(sideR, pluck(m, 0.2), t0 + q * 0.125, 0.035 * (1 + pan))

    groove(drop, brk)
    # small fills + risers into each 4-second cut
    for cut in np.arange(drop + 4.0, brk - 1e-6, 4.0):
        add(free, riser(0.5, 800, 9000, 0.16), cut - 0.5)
        for k, t0 in enumerate(np.arange(cut - 0.25, cut, 0.0625)):
            add(drums, snare(0.12), t0, 0.08 + 0.05 * k)
    add(free, riser(1.0, 300, 9000, 0.3), brk - 1.0)

    # --- breakdown under the credo ---
    for c, t0, d in (("F", brk, 1.0), ("C", brk + 1.0, 1.0), ("G", brk + 2.0, 1.0)):
        add(sideL, pad(c, d + 0.3, 1.0), t0)
        add(sideR, pad(c, d + 0.3, 1.0), t0 + 0.012)
        add(sideL, bass(ROOTS[c], d), t0, 0.22)
        add(sideR, bass(ROOTS[c], d), t0, 0.22)
    for i, t0 in enumerate(np.arange(brk, build, 0.25)):
        m = [81, 84, 88, 84, 79, 84, 88, 91, 79, 83, 86, 91][i % 12]
        add(free, bell(note(m), 0.8, 0.25), t0, 0.05)
        add(drums, hat(), t0 + 0.125, 0.04)
    add(drums, kick(), brk, 0.9)
    kicks.append(brk)

    # --- build (two beats) then final drop ---
    add(free, riser(drop2 - build, 400, 10000, 0.32), build)
    for k, t0 in enumerate(np.arange(build, drop2, 0.0625)):
        add(drums, snare(0.12), t0, 0.05 + 0.25 * (k / 16) ** 2)
    for t0 in (build, build + 0.5):
        add(drums, kick(), t0, 0.8)
        kicks.append(t0)
    for t0 in np.arange(drop2, end - 1e-6, beat):
        kicks.append(t0)
        add(drums, kick(), t0, 0.9)
        bi = int(round((t0 - bar0) / beat)) % 4
        if bi in (1, 3):
            add(drums, clap(), t0, 0.34)
        add(drums, hat(0.12, 0.05), t0 + 0.25, 0.10)
        for s in (0.125, 0.375):
            add(drums, hat(), t0 + s, 0.05)
        ch = "F" if t0 < drop2 + 1.0 else "G"
        r = ROOTS[ch]
        for s, m, g in ((0.25, r, 0.30), (0.375, r + 12, 0.16)):
            add(sideL, bass(m, 0.2), t0 + s, g)
            add(sideR, bass(m, 0.2), t0 + s, g)
        add(sideL, stab(ch), t0 + 0.25, 0.34)
        add(sideR, stab(ch), t0 + 0.26, 0.34)
    # final C major hit, rings out
    tail = dur - end + 0.2
    add(drums, kick(0.6), end, 1.0)
    kicks.append(end)
    for side, det in ((sideL, 0), (sideR, 0.01)):
        x = np.zeros(int(tail * SR))
        for m in (48, 55, 60, 64, 67, 72):
            x += saw(note(m), tail, nh=8, bright=0.6, detune=det * 0.4, phase=rng.uniform(0, 6))
        x *= np.exp(-tt(tail) / 0.5) * env(len(x), 0.004, 0.1) / 6
        add(side, x, end, 0.8)
        add(side, bass(36, tail), end, 0.3)

    # sidechain: duck the tonal stems on every kick
    duck = np.ones(n)
    shape = 1 - 0.7 * np.exp(-tt(0.35) / 0.07)
    for k in kicks:
        i = int(k * SR)
        j = min(n, i + len(shape))
        if i < n:
            duck[i:j] = np.minimum(duck[i:j], shape[: j - i])
    L = drums + sideL * duck + free
    R = drums + sideR * duck + free
    return L, R


# ---------------- sound effects ----------------
def sweep_noise(d, f0, f1, peak=0.5):
    x = noise(d)
    p = np.linspace(0, 1, len(x))
    fc = f0 + (f1 - f0) * p
    y = lowpass(x, fc * 1.6) - lowpass(x, fc * 0.6)
    k = np.arange(len(x))
    e = np.sin(np.pi * np.clip(k / (len(x) * peak), 0, 1) / 2) * np.clip((len(x) - k) / (len(x) * (1 - peak)), 0, 1)
    return y * e / (np.max(np.abs(y)) + 1e-9)


def chirp(f0, f1, d, decay):
    t = tt(d)
    f = f0 * (f1 / f0) ** (t / d)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / decay) * env(len(t), 0.003, 0.02)


def sfx(kind):
    if kind == "whoosh":
        return sweep_noise(0.5, 300, 3000, 0.7) * 0.34
    if kind == "whip":
        return sweep_noise(0.24, 500, 4500, 0.55) * 0.3
    if kind == "swish":
        return sweep_noise(0.16, 1200, 4000, 0.4) * 0.15
    if kind == "boom":
        t = tt(1.0)
        f = 38 + 70 * np.exp(-t / 0.06)
        return np.tanh(1.5 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.35)) * 0.6
    if kind == "hit":  # short low punch for word slams
        t = tt(0.3)
        f = 60 + 160 * np.exp(-t / 0.02)
        return (
            np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.08) * 0.5
            + band(noise(0.3), 2000, 8000) * np.exp(-t / 0.015) * 0.12
        )
    if kind == "inflate":  # balloon-ish rising wobble under "grossir."
        t = tt(0.42)
        f = 180 * 2 ** (1.6 * t / 0.42) * (1 + 0.03 * np.sin(2 * np.pi * 18 * t))
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(t), 0.05, 0.03) * 0.16
    if kind == "squeeze":
        return chirp(1400, 160, 0.16, 0.12) * 0.26
    if kind == "pop":
        out = np.pad(bell(1760, 0.3, 0.09), (int(0.015 * SR), 0))[: int(0.3 * SR)] * 0.09
        c = chirp(700, 1500, 0.06, 0.04) * 0.2
        out[: len(c)] += c
        return out
    if kind == "chirp":  # little bird flutter for the mark
        out = np.zeros(int(0.3 * SR))
        for i, (a, b) in enumerate(((2600, 3600), (2900, 4200), (3100, 4600))):
            c = chirp(a, b, 0.06, 0.03) * 0.09
            add(out, c, i * 0.07)
        return out
    if kind == "stab":
        return stab("Am", 0.5, 1.0) * 0.6
    if kind == "send":
        return chirp(420, 1500, 0.14, 0.1) * 0.2 + sweep_noise(0.14, 800, 3000, 0.3) * 0.05
    if kind == "tick":
        return bell(2400, 0.08, 0.02) * 0.14
    if kind == "shimmer":
        out = np.zeros(int(1.0 * SR))
        for i, f in enumerate((2093, 2637, 3136, 4186)):
            add(out, bell(f, 0.8, 0.25) * 0.05, i * 0.05)
        return out
    if kind == "sting":
        out = np.zeros(int(1.0 * SR))
        for f in (523.3, 659.3, 783.99, 1046.5):
            add(out, bell(f, 1.0, 0.45) * 0.06, 0)
        return out
    raise ValueError(kind)


def main():
    cues = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    dur = cues["duration"]
    n = int(dur * SR)
    assert cues.get("bpm") == 120, "the arrangement is written for 120 BPM"
    mL, mR = music(dur, cues["music"])
    fx = np.zeros(n)
    for t0, kind in cues["sfx"]:
        add(fx, sfx(kind), t0, 1.0)
    L = mL * 0.8 + fx
    R = mR * 0.8 + fx
    fi, fo = int(0.01 * SR), int(0.35 * SR)
    for ch in (L, R):
        ch[:fi] *= np.linspace(0, 1, fi)
        ch[-fo:] *= np.linspace(1, 0, fo)
    # gentle bus saturation then peak-normalise
    st = np.stack([L, R], 1)
    st = np.tanh(st / (np.max(np.abs(st)) + 1e-9) * 1.3) / np.tanh(1.3)
    st *= 0.89
    pcm = (np.clip(st, -1, 1) * 32767).astype(np.int16)
    w = wave.open(out, "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
    w.close()
    print("audio", out, f"{dur:.2f}s")


if __name__ == "__main__":
    main()
