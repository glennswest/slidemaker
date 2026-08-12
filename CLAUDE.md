# slidemaker — Project Context

Reusable narration + video production pipeline for HTML slide decks.
Turns a deck + per-slide narration text into a narrated MP4 (and PDF),
with three voice backends: neural TTS (edge-tts), macOS `say`, and
own-voice cloning (F5-TTS on a remote GPU host, Whisper-driven
reference-span selection). Extracted from the llmpager presentation
work, where every piece was proven end to end.

## Version

Current: **0.2.0** (pre-1.0)

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

Where that leaves it: inside one continuous pass there is no per-sentence
lever at all. The curve chooses reference, speed and loudness per slide.
Real per-sentence performance needs either a TTS with genuine style
control, or the presenter actually performing the take. **Untested
hypothesis:** a properly recorded energetic reference (same mic, same
room, same session as the calm one) may be enough — energy.wav has not
been verified as a good recording, and every clone from it has sounded
poor.

## Session Log

- 2026-08-12: Renamed to slidemaker, own repo. Built the excitement
  curve (script markers -> per-sentence energy -> loudness/pauses/rate,
  slew limited) and the energy-band clone path. Curve planner verified
  against the Kimi narration; clone renders judged bad by the user and
  defaults reverted to known-good. See "Excitement — what was learned".
- 2026-08-07: Extracted from llmpager: deck→frames→audio→mp4 pipeline,
  edge-tts neural voice, F5-TTS cloning with Whisper span selection,
  mic recording with level checks. First consumer: llmpager deck.
