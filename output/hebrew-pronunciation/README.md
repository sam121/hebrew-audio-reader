# Hebrew Pronunciation Reader

This folder contains the source and build pipeline for a static GitHub Pages site that pairs scanned PDF pages with a verified Hebrew transcript and pre-generated audio.

## Source files

- `transcript.json`: hand-curated source text and grouping metadata
- `index.html`: browser app source
- `pages/`: rendered PDF page images
- `scripts/build_site.py`: builds `site/`, generates missing audio, and writes manifests

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

## GitHub Pages

The workflow at `.github/workflows/hebrew-reader-pages.yml` restores cached audio, generates any missing verified clips, builds `site/`, and deploys that folder to GitHub Pages.
