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
import subprocess
import sys


# [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
EMO_DIMS = 8

# How much of the bright curve a neutral (valence 0) sentence keeps.
# 0.7 keeps neutral narration at about the body level of the render that
# was judged right by ear (happy ~0.11) rather than draining it to ~0.05.
NEUTRAL_LIFT = float(os.environ.get('SM_NEUTRAL_LIFT', '0.7'))


def emotion_vector(e, valence=1.0, gain=None):
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
    # Neutral is not flat. Gating the bright dimensions on max(0, valence)
    # zeroes them for every neutral sentence, and a model reading a
    # technical talk marks most sentences neutral — that alone would drain
    # the deck. Neutral therefore keeps a floor of the bright curve and
    # only genuinely negative material fades it out.
    if valence >= 0.0:
        up = NEUTRAL_LIFT + (1.0 - NEUTRAL_LIFT) * valence
    else:
        up = NEUTRAL_LIFT * (1.0 + valence)      # reaches 0 at valence -1
    down = max(0.0, -valence)
    v = [0.0] * EMO_DIMS
    v[0] = (e - 0.35) * 0.45 * g * up        # happy
    v[6] = (e - 0.85) * 0.30 * g * up        # surprised, only right at the top
    v[2] = (e - 0.35) * 0.28 * g * down      # sad
    v[5] = (e - 0.30) * 0.45 * g * down      # melancholic — the weight
    v[3] = (e - 0.75) * 0.30 * g * down      # afraid, only when stakes are high
    v[7] = (0.50 - e) * 1.00 * g             # calm, either direction
    # angry and disgusted stay at zero. This narrates a technical talk; a
    # presenter who sounds angry about a bottleneck reads as unhinged.
    return [round(min(1.0, max(0.0, x)), 3) for x in v]


def call(fn, **kwargs):
    """Pass only what this build of IndexTTS-2 actually accepts."""
    ok = set(inspect.signature(fn).parameters)
    return fn(**{k: v for k, v in kwargs.items() if k in ok})


def pacing(e, valence=1.0):
    """Tempo and inter-phrase silence for a run at energy `e`.

    IndexTTS-2's infer() has no speed argument, so pacing has to be set two
    other ways. `interval_silence` widens the gaps the model leaves between
    its own phrases — free, artefact-free, and the thing that stops an
    opening from sounding rushed. Tempo is a post pass, kept small: under
    about 8% atempo is transparent, past that it starts to smear.

    Low energy is genuinely slower here. An earlier version routed tempo
    through the same ease curve as rate, which put a calm opening line at
    1.045 — asking the quietest part of the talk to outrun the rest.
    """
    lo, hi = (float(x) for x in
              os.environ.get('SM_TEMPO', '0.92:1.05').split(':'))
    tempo = lo + (hi - lo) * e
    if e > 0.85:                       # land the payoff, don't sprint it
        tempo -= (e - 0.85) * 0.20
    # Weight is slower and leaves more air. Nobody rattles through the part
    # where they explain what went wrong.
    down = max(0.0, -valence)
    tempo -= 0.05 * down
    silence = int(round(320 - 200 * e + 60 * down))
    return round(tempo, 3), silence


def split_runs(segs, max_runs):
    """Group a slide's sentences into at most `max_runs` continuous runs.

    Cuts are mandatory where valence changes sign — averaging a hopeful
    line with a grim one gives neither — and otherwise fall at the largest
    energy steps. No run is shorter than two sentences, so a slide never
    degenerates into per-sentence splicing.
    """
    if not segs:
        return []
    cuts = [i + 1 for i in range(len(segs) - 1)
            if (segs[i].get('valence', 1.0) < 0) !=
               (segs[i + 1].get('valence', 1.0) < 0)]
    jumps = sorted((abs(segs[i + 1]['energy'] - segs[i]['energy']), i + 1)
                   for i in range(len(segs) - 1))
    for _, idx in reversed(jumps):
        if len(cuts) >= max(1, max_runs) - 1:
            break
        if idx in cuts:
            continue
        edges = sorted(cuts + [idx, 0, len(segs)])
        if min(b - a for a, b in zip(edges, edges[1:])) >= 2:
            cuts.append(idx)
    runs = []
    for a, b in zip([0] + sorted(cuts), sorted(cuts) + [len(segs)]):
        part = segs[a:b]
        if part:
            runs.append({
                'q': sum(x['energy'] for x in part) / len(part),
                'v': sum(x.get('valence', 1.0) for x in part) / len(part),
                'segs': part})
    return runs


def retempo(src, dst, tempo):
    """Small pitch-preserving tempo change. Returns the path to use."""
    if abs(tempo - 1.0) < 0.02:
        return src
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src,
                    '-filter:a', f'atempo={tempo:.3f}', dst], check=True)
    return dst


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

    global np, sf
    import numpy as np
    import soundfile as sf
    from indextts.infer_v2 import IndexTTS2
    here = os.path.dirname(os.path.abspath(__file__))
    ckpt = os.environ.get('INDEXTTS_CKPT', os.path.join(here, 'checkpoints'))
    tts = call(IndexTTS2, cfg_path=os.path.join(ckpt, 'config.yaml'),
               model_dir=ckpt, use_fp16=True, use_cuda_kernel=False)

    tmp = os.path.join(outdir, '.piece.wav')
    tmp2 = os.path.join(outdir, '.tempo.wav')
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
            runs = split_runs(segs, int(os.environ.get('SM_EMO_RUNS', '3')))
            pieces, sr = [], None
            for r in runs:
                emo = emotion_vector(r['q'], r['v'])
                tempo, silence = pacing(r['q'], r['v'])
                call(tts.infer, spk_audio_prompt=ref,
                     text=' '.join(x['text'] for x in r['segs']),
                     output_path=tmp, emo_vector=emo, emo_alpha=1.0,
                     interval_silence=silence, verbose=False)
                w, sr = sf.read(retempo(tmp, tmp2, tempo), dtype='float32')
                pieces.append(w if w.ndim == 1 else w.mean(axis=1))
                gap = r['segs'][-1]['gap']
                if gap > 0 and r is not runs[-1]:
                    pieces.append(np.zeros(int(gap * sr), dtype=np.float32))
                print(f"  {slide['slide']} run e={r['q']:.2f} v={r['v']:+.2f} emo={emo} "
                      f"tempo={tempo} sil={silence}ms "
                      f"{len(r['segs'])} sentences", flush=True)
            sf.write(out, np.concatenate(pieces), sr)
            print(f"  {slide['slide']} {len(runs)} runs, {len(segs)} sentences",
                  flush=True)
        elif mode == 'slide':
            e = sum(s['energy'] for s in segs) / len(segs)
            vv = sum(s.get('valence', 1.0) for s in segs) / len(segs)
            emo = emotion_vector(e, vv)
            tempo, silence = pacing(e, vv)
            call(tts.infer, spk_audio_prompt=ref,
                 text=' '.join(s['text'] for s in segs),
                 output_path=tmp, emo_vector=emo, emo_alpha=1.0,
                 interval_silence=silence, verbose=False)
            os.replace(retempo(tmp, tmp2, tempo), out)
            print(f"  {slide['slide']} e={e:.2f} emo={emo} tempo={tempo} "
                  f"sil={silence}ms one pass, {len(segs)} sentences", flush=True)
        else:
            pieces, sr = [], None
            for i, seg in enumerate(segs):
                emo = emotion_vector(seg['energy'], seg.get('valence', 1.0))
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
    for f in (tmp, tmp2):
        if os.path.exists(f):
            os.remove(f)


if __name__ == '__main__':
    main()
