#!/usr/bin/env python3
"""IndexTTS-2 renderer — the excitement curve as an actual model input.

F5-TTS bundles timbre and emotion into one thing: the reference clip. There
is no way to say "same voice, more excited" — asking for more energy means
handing it a different reference, which changes who it sounds like. That is
a property of the model, not a tuning problem.

IndexTTS-2 separates them. The speaker prompt fixes *who*; an eight-value
emotion vector fixes *how*:

    [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]

So the curve becomes a literal argument. One speaker prompt for the whole
deck — your voice never moves — and energy drives the emotion vector.

Granularity is still per slide by default, one continuous pass, because
splicing sentences remains the wrong primitive no matter how good the
model is: the intonation contour restarts at every join. The difference
here is that per-slide energy no longer costs you your identity.

Usage: slidemaker-clone-indextts.py PLAN.json OUTDIR [--slide NN]
                                    [--mode slide|arc|sentence] [--ref WAV]
"""

import inspect
import json
import os
import sys

import numpy as np
import soundfile as sf

# [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
EMO_DIMS = 8


def emotion_vector(e, gain=None):
    """Map one energy value onto the excitement axis of the emotion space.

    Excitement is mostly 'happy' with a touch of 'surprised' at the very
    top; the low end is not sadness, it is calm. Everything else stays at
    zero — this is a narration engine, not an acting engine, and reaching
    for the other dimensions is how you get a delivery that sounds unhinged.

    The usable range is far narrower than it looks. A vector of happy=0.72
    with surprised=0.24 is not "an excited presenter", it is too much, and
    it drags loudness and speed along with it. Full energy here asks for
    roughly happy=0.30 — a lift, not a performance. EMO_GAIN scales the
    whole axis so this is a dial you can turn rather than a constant I have
    guessed at.
    """
    g = float(os.environ.get('SM_EMO_GAIN', '1.0')) if gain is None else gain
    v = [0.0] * EMO_DIMS
    v[0] = (e - 0.35) * 0.45 * g          # happy
    v[6] = (e - 0.85) * 0.30 * g          # surprised, only right at the top
    v[7] = (0.50 - e) * 1.00 * g          # calm
    return [round(min(1.0, max(0.0, x)), 3) for x in v]


def call(fn, **kwargs):
    """Pass only what this build of IndexTTS-2 actually accepts."""
    ok = set(inspect.signature(fn).parameters)
    return fn(**{k: v for k, v in kwargs.items() if k in ok})


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    plan_path, outdir = sys.argv[1], sys.argv[2]

    def opt(flag, default=None):
        return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default

    only = opt('--slide')
    mode = opt('--mode', 'slide')
    ref = opt('--ref', os.path.join(os.path.dirname(plan_path) or '.',
                                    'refs', 'calm.wav'))
    if mode not in ('slide', 'arc', 'sentence'):
        sys.exit('--mode must be slide, arc or sentence')
    if not os.path.exists(ref):
        sys.exit(f"speaker prompt not found: {ref}")

    with open(plan_path) as fh:
        plan = json.load(fh)
    os.makedirs(outdir, exist_ok=True)
    print(f"speaker prompt: {ref}", flush=True)

    from indextts.infer_v2 import IndexTTS2
    here = os.path.dirname(os.path.abspath(__file__))
    ckpt = os.environ.get('INDEXTTS_CKPT', os.path.join(here, 'checkpoints'))
    tts = call(IndexTTS2, cfg_path=os.path.join(ckpt, 'config.yaml'),
               model_dir=ckpt, use_fp16=True, use_cuda_kernel=False)

    tmp = os.path.join(outdir, '.piece.wav')
    for slide in plan['slides']:
        if only and slide['slide'] != only:
            continue
        segs = slide['segments']
        out = os.path.join(outdir, f"slide{slide['slide']}.wav")

        if mode == 'arc':
            # One vector for a whole slide throws the build away; one per
            # sentence is splicing. So: group consecutive sentences whose
            # energy quantises the same, render each run as one continuous
            # pass, and join only where the energy actually steps — which is
            # where a speaker would draw breath anyway. A slide usually comes
            # out as two or three runs, not eight fragments.
            # Quantising energy into bands fragments a slide into six or
            # seven pieces, which is splicing wearing a hat. Instead: cut at
            # most SM_EMO_RUNS-1 times, at the biggest energy steps in the
            # slide, keeping every run at least two sentences long. Each run
            # then speaks at its own mean energy.
            max_runs = int(os.environ.get('SM_EMO_RUNS', '3'))
            jumps = sorted(
                (abs(segs[i + 1]['energy'] - segs[i]['energy']), i + 1)
                for i in range(len(segs) - 1))
            cuts = []
            for _, idx in reversed(jumps):
                if len(cuts) >= max_runs - 1:
                    break
                edges = sorted(cuts + [idx, 0, len(segs)])
                if min(b - a for a, b in zip(edges, edges[1:])) >= 2:
                    cuts.append(idx)
            runs = []
            for a, b in zip([0] + sorted(cuts), sorted(cuts) + [len(segs)]):
                part = segs[a:b]
                runs.append({'q': sum(s['energy'] for s in part) / len(part),
                             'segs': part})
            pieces, sr = [], None
            for r in runs:
                emo = emotion_vector(r['q'])
                call(tts.infer, spk_audio_prompt=ref,
                     text=' '.join(x['text'] for x in r['segs']),
                     output_path=tmp, emo_vector=emo, emo_alpha=1.0,
                     verbose=False)
                w, sr = sf.read(tmp, dtype='float32')
                pieces.append(w if w.ndim == 1 else w.mean(axis=1))
                gap = r['segs'][-1]['gap']
                if gap > 0 and r is not runs[-1]:
                    pieces.append(np.zeros(int(gap * sr), dtype=np.float32))
                print(f"  {slide['slide']} run e={r['q']:.2f} emo={emo} "
                      f"{len(r['segs'])} sentences", flush=True)
            sf.write(out, np.concatenate(pieces), sr)
            print(f"  {slide['slide']} {len(runs)} runs, {len(segs)} sentences",
                  flush=True)
        elif mode == 'slide':
            e = sum(s['energy'] for s in segs) / len(segs)
            emo = emotion_vector(e)
            call(tts.infer, spk_audio_prompt=ref,
                 text=' '.join(s['text'] for s in segs),
                 output_path=out, emo_vector=emo, emo_alpha=1.0, verbose=False)
            print(f"  {slide['slide']} e={e:.2f} emo={emo} "
                  f"one pass, {len(segs)} sentences", flush=True)
        else:
            pieces, sr = [], None
            for i, seg in enumerate(segs):
                emo = emotion_vector(seg['energy'])
                call(tts.infer, spk_audio_prompt=ref, text=seg['text'],
                     output_path=tmp, emo_vector=emo, emo_alpha=1.0,
                     verbose=False)
                w, sr = sf.read(tmp, dtype='float32')
                pieces.append(w if w.ndim == 1 else w.mean(axis=1))
                if seg['gap'] > 0:
                    pieces.append(np.zeros(int(seg['gap'] * sr), dtype=np.float32))
                print(f"  {slide['slide']}.{i + 1:02d} e={seg['energy']:.2f} "
                      f"emo={emo} {seg['text'][:40]}", flush=True)
            sf.write(out, np.concatenate(pieces), sr)
        print(out, flush=True)
    if os.path.exists(tmp):
        os.remove(tmp)


if __name__ == '__main__':
    main()
