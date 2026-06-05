# Bear upload bundle

This folder contains a Bear-ready version of the XmR scaling constants article.

- `bear-post-remote-images.md`: easiest to paste into Bear; images point at the existing `xmrit.com` URLs.
- `bear-post-local-images.md`: same post, but image links point at the local `images/` folder.
- `images/`: downloaded copies of all article images, plus `00-social-preview-sample-xmr.png` for a social/cover image if Bear asks for one.

Suggested Bear workflow:

1. Paste `bear-post-remote-images.md` into Bear for a quick publish.
2. If you want Bear-hosted images instead, upload each file in `images/`, copy the Bear image URL it gives you, and replace the matching `images/...` link in `bear-post-local-images.md`.
3. Use `00-social-preview-sample-xmr.png` as the cover/social image, if your Bear settings expose that field.
