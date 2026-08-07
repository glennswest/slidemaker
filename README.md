# gmedia

Turn an HTML slide deck plus per-slide narration text into a narrated
video (and PDF) — with your choice of voice: neural TTS, macOS `say`,
your own recordings, or an AI clone of your voice running on your own
GPU. No cloud services; nothing leaves your machines.

Extracted from the llmpager presentation pipeline, where every stage was
proven end to end.

## Quick start

```bash
export PATH="$PATH:/path/to/gmedia/bin"
cd my-talk/            # contains deck.html + narration/slide01.txt ...
gmedia init            # writes gmedia.conf — edit SLIDES etc.
gmedia tts             # neural TTS narration (edge-tts)
gmedia video           # frames + audio -> video.mp4
gmedia pdf             # deck -> PDF
```

The deck is any self-contained HTML whose slides render one at a time
via `deck.html#N` (a dozen lines of hash-routing JS — see the llmpager
deck for a reference implementation).

## Your own voice

Best-quality path, learned the hard way:

1. **Record ~3 minutes** of natural reading — phone Voice Memos in a
   parked car beats any software cleanup. `gmedia check FILE` verifies
   levels (target: peaks -6 to -15 dB; a max under -25 dB means the mic
   didn't really capture).
2. `gmedia clone ship FILE` — uploads to your GPU host (`CLONE_HOST`).
3. `gmedia clone spans` — Whisper lists candidate ~10s reference spans.
4. `gmedia clone test N` — hear a test slide cloned from span N; A/B a
   few, spans differ in character.
5. `gmedia clone all N && gmedia clone fetch setN` — synthesize every
   slide, download into `voice-setN/`.
6. `gmedia video voice-setN` — build with your cloned voice.

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
  (`gmedia clone setup` bootstraps it; NVIDIA driver + CUDA-capable
  torch required)

## Roadmap

Talking-head generation (photo + audio → animated presenter,
SadTalker/EchoMimic class, composited into a corner of the slides),
SRT subtitles from narration, intro/outro cards. See CLAUDE.md.

## License

Apache-2.0
