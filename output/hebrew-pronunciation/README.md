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

- `qa.html`: contractor-facing arrow placement and listening surface
- `site/data/qa.json`: build-generated QA dataset
- `qa-sync-config.json`: shared-save configuration for Google Sheet backup sync
- `scripts/google_sheet_review_sync.gs`: Google Apps Script web app that reads and writes QA arrow progress into the `backup` tab
- [CONTRACTOR_INSTRUCTIONS.md](/Users/samueltaylor/Documents/New%20project/output/hebrew-pronunciation/CONTRACTOR_INSTRUCTIONS.md): full instructions for using the QA reader and logging issues in the Google Sheet

Suggested cycle:

1. Build and deploy a fresh review build.
2. Open `qa.html`.
3. For each line:
   - click once on the page to place the arrow vertically
   - press `Play line` to listen
   - if the line is fine, leave the Google Sheet issue fields blank
   - if the line has a problem, record it in the Google Sheet using `Issue Category` and `Issue Note`
4. Use `Save progress` in the QA page to save arrow positions.
5. Re-import from the Google Sheet so only issue-marked lines are updated.

### Shared Google Sheet backup

The QA page supports shared progress for arrow positions via a small Google Apps Script web app.

How it works:

1. Deploy `scripts/google_sheet_review_sync.gs` as a web app in Google Apps Script.
2. Set the deployed web app URL in `qa-sync-config.json` under `endpoint`.
3. Rebuild the site.
4. The reviewer page will then:
   - load shared progress from the Google Sheet on page open
   - save arrow progress to the `backup` tab
   - use `Save progress` to push the latest arrow state to the sheet

Notes:

- The site still keeps local browser autosave as a fallback.
- If shared sync is not configured, `Save progress` falls back to saving a JSON file.
- The Apps Script will create the `backup` tab and header row automatically if they do not already exist.

## GitHub Pages

The workflow at `.github/workflows/hebrew-reader-pages.yml` restores cached audio, generates any missing verified clips, builds `site/`, and deploys that folder to GitHub Pages.
