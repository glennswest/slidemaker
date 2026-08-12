#!/usr/bin/env python3
"""Voice-clone renderer — runs on the GPU host, driven by the excitement plan.

Reads plan.json (produced by `slidemaker-prosody json`) and renders every
sentence in your own cloned voice at the energy the script asks for.

Excitement here does not come from DSP. Pitch-shifting or speeding up a
clone is what makes it nasal and breathless. It comes from the reference:
refs/calm, refs/mid and refs/hot are spans of your own voice at three
energy levels, and each sentence is cloned from the band it needs. Speed
and target loudness are nudged within a band; the character comes from you.

The model is loaded once and reused for the whole deck — the CLI reloads it
per invocation, which is minutes of wasted GPU time over a deck.

Usage: slidemaker-clone-curve.py PLAN.json OUTDIR [--slide NN]
"""

import hashlib
import json
import os
import sys

import numpy as np
import soundfile as sf

BANDS = ('calm', 'mid', 'hot')
FALLBACK = ('mid', 'hot', 'calm')   # if a band was never recorded


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


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    plan_path, outdir = sys.argv[1], sys.argv[2]
    only = None
    if '--slide' in sys.argv:
        only = sys.argv[sys.argv.index('--slide') + 1]

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
        pieces, sr = [], 24000
        for i, seg in enumerate(slide['segments']):
            ref_wav, ref_text = pick(refs, seg['band'])
            e = seg['energy']
            # target_rms is F5's output loudness normalisation: this is the
            # excitement lever that does not distort the voice.
            target_rms = round(0.085 + 0.075 * e, 4)
            seed = int(hashlib.sha1(seg['text'].encode()).hexdigest()[:7], 16)
            wav, sr, _ = f5.infer(
                ref_file=ref_wav, ref_text=ref_text, gen_text=seg['text'],
                speed=seg['speed'], target_rms=target_rms, nfe_step=32,
                cross_fade_duration=0.15, remove_silence=False, seed=seed,
                show_info=lambda *a, **k: None)
            wav = fade(np.asarray(wav, dtype=np.float32), sr)
            pieces.append(wav)
            if seg['gap'] > 0:
                pieces.append(np.zeros(int(seg['gap'] * sr), dtype=np.float32))
            print(f"  {slide['slide']}.{i + 1:02d} e={e:.2f} {seg['band']:<4} "
                  f"speed={seg['speed']} rms={target_rms} {seg['text'][:48]}",
                  flush=True)
        out = os.path.join(outdir, f"slide{slide['slide']}.wav")
        sf.write(out, np.concatenate(pieces), sr)
        print(out, flush=True)


if __name__ == '__main__':
    main()
