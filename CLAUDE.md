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

### M1 — Polish
- [ ] Per-slide voice mixing report (which backend each slide used)
- [ ] Background music / intro-outro cards (optional)
- [ ] Subtitle (SRT) generation from narration files
- [ ] Local F5-TTS support (no ssh host)

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

**Unfinished — this is where work stopped.** The annotation request hangs.
Isolated probes all pass: 800-word prompts, system role, max_tokens=3000,
temperature 0.2, each fine on their own and answering in ~1s. The full
annotate payload does not return within 10 minutes. Cause not yet found.
Next step is to post the exact payload (saved shape in cmd_annotate) with
curl and watch journalctl on the host, rather than through the tool.

Also unverified: whether qwen3-30b-a3b gives a *good* reading. Nothing has
been listened to from this path yet.

## Session Log

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
