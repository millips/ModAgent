# Cat Night Voyage theme asset provenance

All assets in this directory were generated specifically for ModAgent on
2026-07-21 with OpenAI's image generation tool. They are not copied from a
third-party game, brand, artist, or asset pack.

- `background/wallpaper-v01.png`: original Cat Night Voyage wallpaper.
- `ornaments/wide-sleeping-cat.png`: wide-content ornament, chroma keyed from
  `ornaments/sources/wide-sleeping-cat-chroma.png`.
- `ornaments/medium-reading-cat.png`: medium-card ornament, chroma keyed from
  `ornaments/sources/medium-reading-cat-chroma.png`.
- `ornaments/short-paw-trail.png`: short active-control ornament, chroma keyed
  from `ornaments/sources/short-paw-trail-chroma.png`.
- `ornaments/sleeping-crescent-cat-v2.png`: compact empty-state ornament,
  chroma keyed from `ornaments/sources/sleeping-crescent-cat-chroma-v2.png`.
- `ornaments/peeking-moon-cat-v2.png`: low horizontal modal/report-header
  ornament, chroma keyed from
  `ornaments/sources/peeking-moon-cat-chroma-v2.png`.
- `ornaments/reaching-star-cat-v2.png`: narrow vertical sidebar ornament,
  chroma keyed from
  `ornaments/sources/reaching-star-cat-chroma-v2.png`.

The six ornaments are separate compositions for separate size classes. The
application must preserve their aspect ratio and must not use them as stretched
panel backgrounds or nine-slice frames.

## Commercial audio pack

The 25 files in `audio/` were supplied by the project owner from the commercial
source set whose original filenames contain `商用猫主题` or `商猫`. The original
filenames are retained in the owner's commercial-license archive; these runtime
copies use stable event-oriented names and are SHA-256 locked by
`electron/scripts/verify-commercial-audio.js`.

- `startup-1.mp3` through `startup-4.mp3` retain the explicit 1 → 2 → 3 → 4
  order from the source notes. The application waits for each segment to finish
  and immediately starts the next one; the phrase must not be overlaid.
- `error.mp3` follows its source note and is stopped after the first 0.5 seconds.
- The press, hover, download, installation, scan, notice, removal, cancellation,
  rollback, toggle, warning and batch-complete files map directly to the event
  named in their original filename.
- The cat hover layer ships at 8% base gain because pointer movement can trigger
  it frequently. Users can independently adjust hover, ordinary press and large
  dial press volume from Feedback Calibration settings.
- The three `easter-*` files have a combined 5% trigger probability only when
  the user manually presses the large feedback dial. Automated events, ordinary
  button presses and reply completion never trigger the easter sounds.
