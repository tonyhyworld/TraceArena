# TraceArena product film

This directory contains the reproducible HyperFrames composition for the 83-second TraceArena product film.

## Render

Requirements: Node.js 22+, FFmpeg, and Chrome.

```bash
npm run check
HYPERFRAMES_BROWSER_PATH="/path/to/Chrome" npm run render -- \
  --output renders/tracearena-demo.mp4 \
  --quality standard \
  --fps 30
```

The committed `narration.wav` was generated with an offline system voice from [`narration.txt`](narration.txt). Replace it with a human recording while preserving the 82.4-second timing if you want a different voice.

## Visual provenance

The film uses an original, code-native visual system documented in [`DESIGN.md`](DESIGN.md). It borrows the general visual language of a strategic court—ink-dark space, authority gold, cinnabar pressure, architectural frames, and chessboard hierarchy—but does not include characters, story material, images, music, or other assets from any private TraceArena scenario.
