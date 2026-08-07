# gmedia — Project Context

Reusable narration + video production pipeline for HTML slide decks.
Turns a deck + per-slide narration text into a narrated MP4 (and PDF),
with three voice backends: neural TTS (edge-tts), macOS `say`, and
own-voice cloning (F5-TTS on a remote GPU host, Whisper-driven
reference-span selection). Extracted from the llmpager presentation
work, where every piece was proven end to end.

## Version

Current: **0.1.0** (pre-1.0)

Version locations:
- `bin/gmedia` — `GMEDIA_VERSION`

## Design

One config file per production (`gmedia.conf`, shell KEY=value, lives
next to the deck). The deck is any self-contained HTML whose slides are
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
- [x] `bin/gmedia` CLI: render, pdf, record, check, tts, clone-*, video
- [x] Config template + docs
- [ ] llmpager presentation migrated to gmedia.conf (thin consumer)
- [ ] End-to-end rerun on llmpager deck via gmedia

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

## Session Log

- 2026-08-07: Extracted from llmpager: deck→frames→audio→mp4 pipeline,
  edge-tts neural voice, F5-TTS cloning with Whisper span selection,
  mic recording with level checks. First consumer: llmpager deck.
