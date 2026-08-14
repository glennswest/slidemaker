# Changelog

## [Unreleased]

## [v0.3.0] — 2026-08-14

### 2026-08-12
- **BREAKING:** Renamed `gmedia` to `slidemaker` and moved to its own
  repo. `slidemaker.conf` is the config name; `gmedia.conf` is still
  read so existing productions keep working
- **feat:** Excitement curve — per-sentence energy from `[e=N]`,
  `[e=A>B]` and `[beat]` markers in the script, `narration/curve.tsv`,
  or an automatic talk arc. Drives loudness, pause length and (gently)
  rate; `slidemaker curve` shows the plan, `slidemaker prosody` measures
  the result
- **feat:** Pause rules that carry the expression — an anticipation
  breath before a jump in energy, a landing pause after a peak
- **feat:** Slew-rate limiter on every acoustic parameter, so a curve
  can request anything but the renderer never emits a discontinuity that
  sounds like the speaker was swapped
- **feat:** `CLONE_ENGINE=indextts` — IndexTTS-2 backend where the curve
  drives an emotion vector with the speaker prompt held fixed, the first
  configuration where energy changes without identity changing. `EMO_GAIN`
  scales the axis; `clone ref` cuts a speaker prompt (no transcript needed)
- **feat:** Valence — energy is "how much", valence is "which way", so a
  problem section gets weight (sad/melancholic/afraid, and slower with more
  air) rather than enthusiasm turned down. `[v=-0.8]`, `[problem]`,
  `[grave]`, `[serious]`, `[bright]`; runs never straddle a change of sign
- **feat:** Structural energy — sentence length, contrast against the
  previous sentence, position in the slide and terminal punctuation, so an
  unmarked script still builds. A short line after a long one is the
  emphasis the writer already intended
- **feat:** Arc rendering — a slide is cut at most twice, at its largest
  energy steps, so the build survives without splicing every sentence
- **feat:** `curve read` — a local LLM reads the narration and writes the
  emotional flow to `curve.json` (INCOMPLETE: the request hangs, see
  CLAUDE.md)
- **feat:** `EMO_GAIN`, `EMO_RUNS`, `SM_TEMPO` calibration dials
- **feat:** Energy-band voice cloning — `clone spans SRC`, `clone band`,
  `clone bands`, `clone curve`; the GPU-side renderer loads F5 once for
  the whole deck instead of once per sentence
- **fix:** Excitement mapping no longer drives rate and pitch up
  together, which made narration speed up and go nasal
- **fix:** One continuous pass per slide when cloning; per-sentence
  splicing sounded worse than a flat read and is now opt-in only
- **fix:** Curve markers were read aloud by the `EXCITEMENT=off` and
  `say` paths
- **fix:** `CLONE_VENV=~/...` was expanded by the local shell, so the
  GPU host was handed this machine's home directory
- **fix:** `clone bands` / `clone setup` used config before loading it

### 2026-08-07
- **feat:** Initial extraction from llmpager: `gmedia` CLI — render/pdf
  (headless Chrome), record + level check, TTS (edge-tts neural / macOS
  say), F5-TTS voice cloning against a remote GPU host (ship, Whisper
  span candidates, per-span test, full-set synthesis, fetch), ffmpeg
  video assembly with per-slide audio priority (human recording >
  cloned set > TTS)
- **docs:** README with the voice-quality playbook (car-recording rule,
  12-second reference rule, span A/B); CLAUDE.md work plan
