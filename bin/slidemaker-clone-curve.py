#!/usr/bin/env python3
"""Voice-clone renderer — runs on the GPU host, driven by the excitement plan.

Reads plan.json (produced by `slidemaker-prosody json`) and renders every
sentence in your own cloned voice at the energy the script asks for.

Excitement here does not come from DSP. Pitch-shifting or speeding up a
clone is what makes it nasal and breathless. It comes from the reference:
refs/calm, refs/mid and refs/hot are spans of your own voice at three
energy levels.

The reference is held constant for a whole slide (--band-scope slide, the
default). F5 clones the *character* of whatever reference it is handed, so
changing reference between sentences changes the apparent tone mid-
paragraph — it sounds like the speaker was swapped, which is worse than a
flat read. Bands therefore change only at slide boundaries, where a visual
cut covers the seam.

Within a slide, dynamics come from things that do not touch timbre: the
planned pauses, a small speed change, and a gain envelope applied after
synthesis. Level is not identity.

The model is loaded once and reused for the whole deck — the CLI reloads it
per invocation, which is minutes of wasted GPU time over a deck.

Usage: slidemaker-clone-curve.py PLAN.json OUTDIR [--slide NN] [--mode M]
       --mode slide     one continuous pass per slide (default)
       --mode sentence  per-sentence render, spliced with room tone
"""

import hashlib
import json
import os
import sys

import numpy as np
import soundfile as sf

BANDS = ('calm', 'mid', 'hot')
FALLBACK = ('mid', 'hot', 'calm')   # if a band was never recorded
CUTS = ((0.45, 'calm'), (0.75, 'mid'))


def band_of(e):
    for thresh, name in CUTS:
        if e < thresh:
            return name
    return 'hot'


def load_bands(refdir):
    refs = {}
    for b in BANDS:
        wav, txt = os.path.join(refdir, b + '.wav'), os.path.join(refdir, b + '.txt')
        if os.path.exists(wav) and os.path.exists(txt):
            with open(txt) as fh:
                refs[b] = (wav, fh.read().strip())
    if not refs:
        sys.exit(f"no reference bands in {refdir}/ — run: slidemaker clone band ...")
    return refs


def pick(refs, band):
    if band in refs:
        return refs[band]
    for b in FALLBACK:
        if b in refs:
            return refs[b]
    raise AssertionError


def fade(x, sr, ms=12):
    """Short edge fades so concatenated sentences don't click."""
    n = min(int(sr * ms / 1000), len(x) // 2)
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n, dtype=x.dtype)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def room_tone(ref_wav, sr, seconds):
    """Fill pauses with the quiet part of your own recording, not digital
    silence.

    A gap of true zeros between two stretches of speech is something no
    microphone has ever produced. The ear hears the noise floor drop out
    and reads the result as uncanny long before anyone can say why. So
    pauses are filled with the quietest window of the reference take,
    tiled and crossfaded.
    """
    n = int(seconds * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    tone, tsr = sf.read(ref_wav, dtype='float32')
    if tone.ndim > 1:
        tone = tone.mean(axis=1)
    win = int(0.15 * tsr)
    if len(tone) < win * 2:
        return np.zeros(n, dtype=np.float32)
    # Quietest 150ms window = the breath between phrases.
    energy = np.convolve(tone ** 2, np.ones(win) / win, mode='valid')
    start = int(np.argmin(energy))
    bed = tone[start:start + win]
    reps = int(np.ceil(n / len(bed))) + 1
    out = np.tile(bed, reps)[:n].astype(np.float32).copy()
    # Taper the seams so the tile does not buzz at its period.
    k = min(int(0.01 * sr), len(bed) // 2)
    if k > 0:
        for edge in range(len(bed), n, len(bed)):
            lo, hi = max(0, edge - k), min(n, edge + k)
            out[lo:hi] *= np.linspace(1.0, 1.0, hi - lo)
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    plan_path, outdir = sys.argv[1], sys.argv[2]
    only = None
    if '--slide' in sys.argv:
        only = sys.argv[sys.argv.index('--slide') + 1]
    mode = 'slide'
    if '--mode' in sys.argv:
        mode = sys.argv[sys.argv.index('--mode') + 1]
    if mode not in ('slide', 'sentence'):
        sys.exit('--mode must be slide or sentence')

    with open(plan_path) as fh:
        plan = json.load(fh)
    refs = load_bands(os.path.join(os.path.dirname(plan_path) or '.', 'refs'))
    os.makedirs(outdir, exist_ok=True)
    print('bands:', ', '.join(sorted(refs)), flush=True)

    from f5_tts.api import F5TTS
    f5 = F5TTS()

    for slide in plan['slides']:
        if only and slide['slide'] != only:
            continue
        segs = slide['segments']
        energies = [s['energy'] for s in segs]
        mean_e = sum(energies) / len(energies)
        band = band_of(mean_e)
        ref_wav, ref_text = pick(refs, band)
        # Known-good baseline. Driving these from the curve made renders
        # louder and faster than the take that actually shipped (-25.7 dB
        # mean / -7.9 peak against -28.1 / -11.9), and it sounded worse.
        # INTENSITY=1 re-enables curve-driven level and speed; leave it at 0
        # unless a listening test says otherwise.
        intensity = float(os.environ.get('SM_CLONE_INTENSITY', '0'))
        target_rms = round(0.1 + intensity * (0.075 * mean_e - 0.015), 4)
        seed = int(hashlib.sha1(slide['slide'].encode()).hexdigest()[:7], 16)

        if mode == 'slide':
            # One continuous pass. The model produces its own intonation
            # contour across the whole slide, including the breaths between
            # sentences, exactly as a person reading it aloud would. Nothing
            # is cut and nothing is reassembled.
            text = ' '.join(s['text'] for s in segs)
            speed = round(1.0 + intensity *
                          (sum(s['speed'] for s in segs) / len(segs) - 1.0), 3)
            wav, sr, _ = f5.infer(
                ref_file=ref_wav, ref_text=ref_text, gen_text=text,
                speed=speed, target_rms=target_rms, nfe_step=32,
                cross_fade_duration=0.15, remove_silence=False, seed=seed,
                show_info=lambda *a, **k: None)
            wav = np.asarray(wav, dtype=np.float32)
            print(f"  {slide['slide']} e={mean_e:.2f} {band:<4} speed={speed} "
                  f"rms={target_rms} one pass, {len(segs)} sentences",
                  flush=True)
        else:
            pieces, sr = [], 24000
            for i, seg in enumerate(segs):
                w, sr, _ = f5.infer(
                    ref_file=ref_wav, ref_text=ref_text, gen_text=seg['text'],
                    speed=seg['speed'], target_rms=target_rms, nfe_step=32,
                    cross_fade_duration=0.15, remove_silence=False,
                    seed=seed + i, show_info=lambda *a, **k: None)
                w = np.asarray(w, dtype=np.float32)
                # Level carries the curve; timbre stays put.
                gain = 10 ** (max(-2.5, min(2.5, (seg['energy'] - mean_e) * 6)) / 20)
                pieces.append(fade(w * gain, sr))
                if seg['gap'] > 0:
                    pieces.append(room_tone(ref_wav, sr, seg['gap']))
                print(f"  {slide['slide']}.{i + 1:02d} e={seg['energy']:.2f} "
                      f"{band:<4} speed={seg['speed']} {seg['text'][:44]}",
                      flush=True)
            wav = np.concatenate(pieces)
        out = os.path.join(outdir, f"slide{slide['slide']}.wav")
        sf.write(out, wav, sr)
        print(out, flush=True)


if __name__ == '__main__':
    main()
