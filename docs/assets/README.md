# README artwork

`pipeline-flow.gif` is the animated overview embedded in the root README.
`pipeline-overview.png` provides the same design without motion. Both contain
only generic module names, architecture and output-contract information.

The animation illustrates stage progression; it is not a recording or a
performance/accuracy claim. It contains no company rows or evaluation results.
The architecture and optional-label diagrams remain editable Mermaid blocks in
the root README.

To regenerate the artwork on macOS with Swift and ffmpeg installed, run from the
repository root:

```bash
mkdir -p /private/tmp/spend-pipeline-frames
SWIFT_MODULECACHE_PATH=/private/tmp/spend-pipeline-swift-cache \
CLANG_MODULE_CACHE_PATH=/private/tmp/spend-pipeline-clang-cache \
swift docs/assets/render_pipeline.swift \
  /private/tmp/spend-pipeline-frames docs/assets/pipeline-overview.png

ffmpeg -hide_banner -loglevel error -framerate 12 \
  -i /private/tmp/spend-pipeline-frames/frame-%03d.png \
  -vf 'fps=8,format=rgb24,scale=1120:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:reserve_transparent=1[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle' \
  -gifflags +offsetting+transdiff -loop 0 -y docs/assets/pipeline-flow.gif
```

The result is an eight-second, 64-frame loop at 1120 × 700 pixels; the static
overview retains 1280 × 800 resolution. Viewing the
README requires no Swift, ffmpeg or additional pipeline dependencies.
