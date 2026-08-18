# slidemaker — Project Context

Reusable narration + video production pipeline for HTML slide decks.
Turns a deck + per-slide narration text into a narrated MP4 (and PDF),
with three voice backends: neural TTS (edge-tts), macOS `say`, and
own-voice cloning (F5-TTS on a remote GPU host, Whisper-driven
reference-span selection). Extracted from the llmpager presentation
work, where every piece was proven end to end.

## Version

Current: **0.3.0** (pre-1.0)

Version locations:
- `bin/slidemaker` — `SLIDEMAKER_VERSION`

## Design

One config file per production (`slidemaker.conf`, shell KEY=value,
lives next to the deck; `gmedia.conf` still read). The deck is any self-contained HTML whose slides are
addressable as `deck.html#N` (1-based). Narration is one text file per
slide. Audio resolution order per slide: human recording in VOICE_DIR →
cloned voice set → TTS. Everything idempotent and cached (frames, tts)
so iteration is cheap.

Voice cloning notes (hard-won):
- F5-TTS reference must be ≤ ~12s with an exact transcript; longer refs
  cause fast/garbled pacing. Whisper picks sentence-aligned spans.
- Reference quality dominates: record close-mic in a dead room (car).
  Software dereverb (resemble-enhance) thins the voice — last resort.
- Different reference spans give different clone character — generate
  candidates from across the sample and A/B them.

## Work Plan

### M0 — Extract & generalize (in progress)
- [x] Repo scaffold, GitHub repo
- [x] `bin/slidemaker` CLI: render, pdf, record, check, tts, clone-*, video
- [x] Config template + docs
- [x] Renamed gmedia -> slidemaker, own repo, history preserved
- [ ] llmpager presentation migrated to slidemaker.conf (thin consumer)
- [ ] End-to-end rerun on llmpager deck via slidemaker

Open work is tracked as GitHub issues (`gh issue list`), not here:
- #1 CLONE_STOP_SERVICE assumes it owns the GPU  (blocks hearing the LLM curve)
- #2 emotion calibration rests on three judgements from one slide
- #3 edge-tts path still splices into digital silence
- #4 no tests
- #5 default CLONE_ENGINE to indextts
- #6 migrate the llmpager presentation
- #7 SRT subtitles   #8 backend-used report   #9 local GPU, no ssh

### M1 — Polish
- [ ] Background music / intro-outro cards (optional)

### M2 — Talking head
- [ ] Photo + narration audio → animated presenter (SadTalker /
      EchoMimic-v2 class, on CLONE_HOST GPU; needs Blackwell-capable
      torch — same cu128 lesson as the enhancer)
- [ ] ffmpeg picture-in-picture composite (corner presenter on slides;
      full-screen for title/close)
- [ ] Expectation note: minutes of head video = long GPU renders; use
      for intro/outro first

## Excitement — what was learned

The AI tell is invariance, not voice quality. But every attempt to fix it
by processing has been worse than the flat read:

- Rate + pitch driven up together = speeds up and goes nasal. Loudness is
  the lever; the peak line slows down. Pitch barely moves.
- Switching clone reference between sentences = the tone changes
  mid-paragraph, as if the speaker were swapped.
- Splicing per-sentence renders = uncanny. Contour resets at each join
  and pauses are digital silence between stretches of room tone. People
  do not splice. One continuous pass per slide is the default.
- Curve-driven level and speed measured hotter and faster than the take
  that shipped (-25.7 dB mean / -7.9 peak vs -28.1 / -11.9) and sounded
  worse. Defaults are back to known-good; SM_CLONE_INTENSITY opts in.

### Resolved: the engine was the problem, not the tuning

F5 cannot express an excitement curve at all. Timbre and emotion arrive
through the same input — the reference clip — so "same voice, more
excited" is not expressible, and every attempt to get energy out of it
was really a request to change speaker. That is why the tone moved.

IndexTTS-2 separates them: speaker prompt for identity, an eight-value
emotion vector for delivery. Verified on ai.g8.lo (Blackwell sm_120,
torch cu13, RTF ~0.79, 5.5G checkpoints). Same speaker prompt at two
energies held identity, and the user's verdict was "no weirdness" — the
nasal, tone-swap and uncanny-splice problems all disappeared.

What remains is calibration, and the usable range is far narrower than it
looks:
- happy=0.72 / surprised=0.24 is "head exploded", not an excited
  presenter, and it drags loudness (+7.3 dB) and speed (-14% duration)
  along with it
- full curve energy now asks for about happy=0.30, surprised=0.05, which
  holds level flat at -27.0 dB across the whole energy range
- EMO_GAIN scales the axis so this stays a dial rather than a constant
  someone guessed at

Speaker prompt: 11s cut from memo.wav (the car recording) at -28.4 dB
mean / -13.7 peak, matching the take that shipped. energy.wav is no
longer needed for the excitement path — emotion no longer comes from the
reference at all.

## Emotion flow from a model that reads the script

Keyword rules cannot do this. The heuristic read "But mixture of experts
models have a secret" as a problem because it contains "but", when it is
the pivot into the good news — the exact sentence that should lift.

`slidemaker curve read` sends each slide to a local model (llmpager on
ai.g8.lo:8090, OpenAI-compatible, qwen3-30b-a3b warm) and stores per
sentence energy + valence in `narration/curve.json`. Priority: explicit
[e=..]/[v=..] markers > the model's reading > structural heuristics.

**Working.** The hang was server-side and is fixed; requests now carry
`session` so llmpager prefills the shared system prompt once per deck.
Whole 15-slide deck reads in four requests, ~3 minutes.

The reading is good where it matters: "But mixture of experts models have
a secret" -> +1.0 "pivot" (the heuristic called it a problem because of
"but"), "Trust the tokenizer." -> +1.0 "solution" among tokenizer
problems at -0.3, "Virtual memory paging, applied to a trillion
parameters." -> +1.0 "reveal".

Two corrections were needed on top of it:
- It ranks well but compresses the scale — 70 of 125 sentences at exactly
  0.40, one at 0.80. E_EXPAND rescales deck-wide between the 5th and 95th
  percentiles, preserving its ordering.
- Neutral is not flat. Gating brightness on max(0, valence) zeroed it for
  every neutral sentence, and most of a technical talk is neutral.
  NEUTRAL_LIFT keeps a floor; only negative material fades it.

**Still not heard.** No audio has been rendered from the LLM curve —
blocked on GPU memory, not on code (see below).

## Sharing the GPU

ai.g8.lo is not slidemaker's to own. Besides the systemd `llmpager`
unit there is often a hand-started instance (e.g. `--config=/tmp/serve9.json`
on :8099) holding ~10 GB of the 15.5 GB card. IndexTTS-2 needs ~5.6 GB
and OOMs by a few MiB against that.

`CLONE_STOP_SERVICE` only knows how to stop the systemd unit, so it
cannot help here and will stop a service without freeing anything. Do not
kill processes to make room — ask. A real fix would check free VRAM
before starting and say what is holding it.

## Session Log

- 2026-08-18: LLM emotion flow working (llmpager wedge fixed server-side,
  requests now carry `session`). Added deck-wide range expansion and a
  neutral-lift floor after the first full-deck read. Nothing rendered yet:
  IndexTTS-2 OOMs with ~5.7 GB free.
- 2026-08-13: IndexTTS-2 backend proven end to end (see above). Added
  valence, structural energy, arc rendering, and the LLM annotation path
  (incomplete — request hangs). Paused: ai.g8.lo powered off for the
  weekend, so every clone/annotate path is offline until it returns.
  The curve planner, `curve`, `curve init` and the edge-tts path all work
  with no server.
- 2026-08-12: Renamed to slidemaker, own repo. Built the excitement
  curve (script markers -> per-sentence energy -> loudness/pauses/rate,
  slew limited) and the energy-band clone path. Curve planner verified
  against the Kimi narration; clone renders judged bad by the user and
  defaults reverted to known-good. See "Excitement — what was learned".
- 2026-08-07: Extracted from llmpager: deck→frames→audio→mp4 pipeline,
  edge-tts neural voice, F5-TTS cloning with Whisper span selection,
  mic recording with level checks. First consumer: llmpager deck.
