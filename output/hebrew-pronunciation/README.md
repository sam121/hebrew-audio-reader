# Hebrew Pronunciation Reader

This folder contains the source and build pipeline for a static GitHub Pages site that pairs scanned PDF pages with a verified Hebrew transcript and pre-generated audio.

## Source files

- `transcript.json`: hand-curated source text and grouping metadata
- `index.html`: browser app source
- `pages/`: rendered PDF page images
- `scripts/build_site.py`: builds `site/`, generates missing audio, and writes manifests

## Transcript conventions

- Keep `displayText` exactly as printed in the scan.
- Use `spokenText` for the text that should actually be sent to ElevenLabs.
- Use `hebrewPlaybackMode: "sequence"` for numbered drill rows that should play word by word.
- Use `hebrewPlaybackMode: "continuous"` or omit the field for normal prose, blessings, and other flowing text.
- `sequenceGapMs` controls the pause between word clips for sequence playback. The current default is `220`.
- Bump the page-level `audioRevision` any time you need fresh audio for a page, even if the visible text did not change.

### Pronunciation override workflow

Use this when ElevenLabs mispronounces a word but the visible Hebrew on the page is correct.

1. Leave `displayText` unchanged.
2. Change `spokenText` to a helper form that produces the intended sound.
3. Bump that page's `audioRevision`.
4. Rebuild and deploy so the corrected clips are regenerated.

Example patterns:

- Divine name:
  - `displayText: "יְיָ"`
  - `spokenText: "אֲדֹנָי"`
- Initial shuruk read as a consonantal vav:
  - `displayText: "וּרָבּוּר"`
  - first try `spokenText: "אוּרָבּוּר"`
  - if ElevenLabs still inserts a v-sound, try a more explicit helper such as `spokenText: "אוּ רָבּוּר"`
- Vet read as a bet:
  - keep the printed Hebrew unchanged in `displayText`
  - if the visible letter is a non-dagesh `ב` and ElevenLabs keeps saying `b`, use a helper `spokenText` that swaps only the sounded consonant, for example:
  - `displayText: "בָבָר"`
  - first try `spokenText: "וָוָר"`
  - if that over-corrects the word, use a more explicit helper such as `spokenText: "וָ בָר"` or another phonetic stepping stone that preserves the intended vowels

For contractor guidance and later QA, treat bet/vet as an explicit check:

- `בּ` should stay a bet / `b` sound.
- plain `ב` without dagesh should be reviewed as a vet / `v` sound unless the page notes say otherwise.
- If the scan is ambiguous, add a note instead of guessing.

### Dot-sensitive Hebrew QA

Do not treat every visible dot the same way. For audio QA, explicitly review words where a dot changes the consonant or syllable behavior:

- `בּ` vs `ב`
- `פּ` vs `פ`
- `כּ` vs `כ`
- `שׁ` vs `שׂ`
- final-heh forms where a dot may indicate a sounded ending in context
- any letter-vowel combination where ElevenLabs seems to collapse the printed distinction

Recommended workflow:

1. Keep `displayText` exactly as printed.
2. If the dotted form changes pronunciation and ElevenLabs misses it, add or adjust `spokenText`.
3. Bump the page `audioRevision`.
4. Rebuild the page and listen to the affected clips directly.

Do not add a blanket automatic rewrite for all dotted letters. Some dots are dagesh, some are shin/sin markers, and some are part of a vowel pattern, so they need explicit review rather than one global substitution rule.

The rule is general: preserve the printed Hebrew for the reader, and use `spokenText` only to steer pronunciation.

## Environment variables

- `ELEVENLABS_API_KEY`
- `ELEVENLABS_HEBREW_VOICE_ID`
- `ELEVENLABS_ENGLISH_VOICE_ID`
- `ELEVENLABS_HEBREW_MODEL` defaults to `eleven_v3`
- `ELEVENLABS_ENGLISH_MODEL` defaults to `eleven_flash_v2_5`
- `ELEVENLABS_OUTPUT_FORMAT` defaults to `mp3_44100_128`

For GitHub Pages deployments, add the first three values as repository secrets with the same names.

## Local preview

1. Build the site:

```zsh
python3 '/Users/samueltaylor/Documents/New project/output/hebrew-pronunciation/scripts/build_site.py' --allow-missing-audio
```

2. Serve the generated site:

```zsh
'/Users/samueltaylor/Documents/New project/output/hebrew-pronunciation/serve.command'
```

If verified items are missing audio and you want production-ready output, rerun the build without `--allow-missing-audio` after setting the ElevenLabs environment variables.

## QA workflow

- `qa.html`: reviewer-facing QA surface for mixed lines, dot-sensitive Hebrew, drill-arrow checks, and structured issue capture
- `site/data/qa.json`: build-generated QA dataset with risk tags, playback metadata, and critical-pass queues
- `scripts/apply_qa_review.py`: applies exported region overrides back to `transcript.json` and emits the remaining issue notes for manual follow-up

Suggested cycle:

1. Build and deploy a fresh review build.
2. Open `qa.html` and work through mixed lines, dot-sensitive lines, and drill lines.
3. Export the review bundle JSON from the QA page.
4. Apply region overrides with `apply_qa_review.py`.
5. Handle the remaining issue notes in one batch, then bump `audioRevision` for changed pages and rebuild.

## GitHub Pages

The workflow at `.github/workflows/hebrew-reader-pages.yml` restores cached audio, generates any missing verified clips, builds `site/`, and deploys that folder to GitHub Pages.
