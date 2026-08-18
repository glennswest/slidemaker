# slidemaker

Turn an HTML slide deck plus per-slide narration text into a narrated
video (and PDF) — with your choice of voice: neural TTS, macOS `say`,
your own recordings, or an AI clone of your voice running on your own
GPU. No cloud services; nothing leaves your machines.

Extracted from the llmpager presentation pipeline, where every stage was
proven end to end.

## Quick start

```bash
export PATH="$PATH:/path/to/slidemaker/bin"
cd my-talk/            # contains deck.html + narration/slide01.txt ...
slidemaker init        # writes slidemaker.conf — edit SLIDES etc.
slidemaker tts         # neural TTS narration (edge-tts)
slidemaker video       # frames + audio -> video.mp4
slidemaker pdf         # deck -> PDF
slidemaker srt         # subtitles from the narration
```

The deck is any self-contained HTML whose slides render one at a time
via `deck.html#N` (a dozen lines of hash-routing JS — see the llmpager
deck for a reference implementation).

## The excitement curve

Narration read at one energy for forty seconds is the thing that makes
listeners say "that's AI" — the tell is invariance, not voice quality.
A curve gives each sentence an energy from 0 to 1, written in the script:

```
[e=0.45] Hi, I'm Glen West. Two days ago I showed you L.L.M. Pager
running a thirty billion parameter model on a sixteen gigabyte card.
[beat=0.7]
[e=0.6>0.95] Today the headline is bigger. A lot bigger.
[e=1.0] This is Kimi K two point six. One trillion parameters.
```

`[e=N]` sets energy, `[e=A>B]` ramps it across the sentences that follow,
`[beat]` / `[beat=0.8]` holds a silence. Unmarked scripts fall back to
`narration/curve.tsv` (`slidemaker curve init` seeds one) and then to an
automatic talk arc: hook, settle, build to the payoff about three
quarters through, land warm.

`slidemaker curve` shows the resolved plan before you spend a minute of
GPU time; `slidemaker prosody` measures what was built, so a flat result
is visible instead of being left to the ear.

Two rules the curve encodes, both learned by getting them wrong:

- **Excitement is not "faster and higher."** Driving rate and pitch up
  together is exactly what makes synthetic narration speed up and turn
  nasal. Loudness is the lever; the peak line *slows down* so it lands;
  pitch barely moves.
- **The pause does the work.** The breath before a jump in energy, and
  the beat after a peak, carry more than any parameter. Silence has no
  timbre, so it is the one channel that can move freely — every other
  parameter is slew-rate limited, because a jump between sentences
  sounds like the speaker was swapped.

### Letting a model read the script

Hand-marking every slide is work, and the structural heuristics can only
count words — they read "But mixture of experts models have a secret" as
a problem because it contains "but", when it is the pivot into the good
news. A local model can tell the difference:

```bash
slidemaker curve read      # writes narration/curve.json
slidemaker curve           # inspect what it decided, before spending GPU time
```

It returns an energy and a valence per sentence with a one-word reason,
and it gets the hard cases right: that pivot comes back as `+1.0
"pivot"`, and `"Trust the tokenizer."` lifts to `+1.0 "solution"` out of
a run of tokenizer problems at `-0.3`.

Point `LLM_URL` at any OpenAI-compatible endpoint (`LLM_MODEL` to pick
the model). Slides are batched `LLM_BATCH` at a time so the model sees
how consecutive slides relate, and every request carries the same
`LLM_SESSION` so a server that supports it prefills the shared system
prompt once per deck rather than per slide.

Two corrections are applied to what comes back, both from watching a real
deck: the model **ranks** sentences well but compresses the **scale** (70
of 125 sentences at exactly 0.40), so `E_EXPAND` stretches its readings
across the deck while preserving every relative judgement; and neutral is
not flat — a technical talk is mostly neutral sentences, so they keep a
floor of the bright curve rather than being drained to nothing.

Priority is always: explicit markers in the script > the model's reading
> the structural heuristics. Marking a sentence by hand overrides
everything.

### What the curve cannot do

With a voice clone, a slide is rendered as **one continuous pass**.
People do not splice, and reassembling per-sentence renders sounds worse
than a flat read — the intonation contour restarts at every join. So
inside a slide the curve chooses only the reference, speed and loudness;
it cannot shape sentence by sentence. Per-sentence energy is available
on the neural-TTS path, and behind `--mode sentence` for cloning, but
that mode is not recommended.

If you want real per-sentence performance in your own voice, the honest
answer is still to perform it: record the slide yourself and drop it in
`voice/slideNN.m4a`, which overrides synthesis.

## Your own voice

Two engines, and the choice matters more than any tuning:

- **IndexTTS-2** (default) keeps identity and delivery separate — a
  speaker prompt fixes who, an emotion vector fixes how — so the
  excitement curve is a real input.
- **F5-TTS** takes both from the same reference clip. "Same voice, more
  excited" is therefore not expressible: asking for more energy means
  handing it a different reference, which changes who it sounds like.
  That is architectural, not a tuning problem. Use it when you have a
  reference set you like, but expect the curve to do little beyond
  choosing a band.

Best-quality path, learned the hard way:

1. **Record ~3 minutes** of natural reading — phone Voice Memos in a
   parked car beats any software cleanup. `slidemaker check FILE` verifies
   levels (target: peaks -6 to -15 dB; a max under -25 dB means the mic
   didn't really capture).
2. `slidemaker clone ship FILE` — uploads to your GPU host (`CLONE_HOST`).
3. `slidemaker clone spans` — Whisper lists candidate ~10s reference spans.
4. `slidemaker clone test N` — hear a test slide cloned from span N; A/B a
   few, spans differ in character.
5. `slidemaker clone all N && slidemaker clone fetch setN` — synthesize every
   slide, download into `voice-setN/`.
6. `slidemaker video voice-setN` — build with your cloned voice.

Real human recordings always win: any `voice/slideNN.m4a` you record
yourself overrides synthesis for that slide.

### Cloning gotchas (encoded in the tool, documented for humans)

- F5-TTS references must be **≤ 12 seconds with an exact transcript**;
  longer references produce fast, garbled speech.
- Room echo in the reference is cloned into every word. Software
  dereverb (resemble-enhance) works but thins the voice — a dead
  recording space is the real fix.
- The reference span *is* the personality: generate candidates from
  different parts of your sample and listen before committing.

## Requirements

- macOS host: ffmpeg, Google Chrome, python3; `pip install edge-tts`
  for neural TTS
- Cloning (optional): a Linux GPU host over ssh with an F5-TTS venv
  (`slidemaker clone setup` bootstraps it; NVIDIA driver + CUDA-capable
  torch required)

## Roadmap

Talking-head generation (photo + audio → animated presenter,
SadTalker/EchoMimic class, composited into a corner of the slides),
SRT subtitles from narration, intro/outro cards. See CLAUDE.md.

## License

Apache-2.0
