from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import urlopen
import re


BASE_URL = "https://xmrit.com/articles/explaining-xmr-scaling-constants/"
ROOT = Path(__file__).resolve().parent
SOURCE_HTML = ROOT / "source.html"
IMAGES_DIR = ROOT / "images"
LOCAL_MD = ROOT / "bear-post-local-images.md"
REMOTE_MD = ROOT / "bear-post-remote-images.md"
README = ROOT / "README.md"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def clean_text(text):
    return (
        text.replace("\u200b", "")
        .replace("\xa0", " ")
        .strip()
    )


def normalize_text(text):
    text = text.replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text)


def slugify(value):
    value = clean_text(value).lower()
    value = value.replace("σ", "sigma").replace("̅", "")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "image"


class ArticleExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []
        self.capture = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "article" and "pgcontent" in attrs_dict.get("class", ""):
            self.capture = True
            self.depth = 1
            self.parts.append(self.get_starttag_text())
            return
        if self.capture:
            self.parts.append(self.get_starttag_text())
            if tag not in VOID_TAGS:
                self.depth += 1

    def handle_endtag(self, tag):
        if self.capture:
            self.parts.append(f"</{tag}>")
            self.depth -= 1
            if self.depth == 0:
                self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_entityref(self, name):
        if self.capture:
            self.parts.append(f"&{name};")

    def handle_charref(self, name):
        if self.capture:
            self.parts.append(f"&#{name};")


class MarkdownConverter(HTMLParser):
    def __init__(self, image_mode):
        super().__init__(convert_charrefs=True)
        self.image_mode = image_mode
        self.out = []
        self.stack = []
        self.list_stack = []
        self.link_stack = []
        self.image_records = []
        self.image_index = 0

    def ensure_blank(self):
        text = "".join(self.out).rstrip()
        if text:
            self.out[:] = [text, "\n\n"]

    def append(self, text):
        self.out.append(text)

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in {"p", "h2", "h3", "h4", "ol", "ul"}:
            self.ensure_blank()
        if tag == "h2":
            self.append("## ")
        elif tag == "h3":
            self.append("### ")
        elif tag == "h4":
            self.append("#### ")
        elif tag == "strong":
            self.append("**")
        elif tag == "em":
            self.append("*")
        elif tag == "a":
            self.link_stack.append({"href": attrs_dict.get("href", ""), "text_start": len(self.out)})
            self.append("[")
        elif tag == "img":
            src = attrs_dict.get("src", "")
            title = clean_text(attrs_dict.get("title", "Image"))
            if src:
                self.image_index += 1
                remote_url = urljoin(BASE_URL, src)
                extension = Path(unquote(urlparse(src).path)).suffix or ".png"
                filename = f"{self.image_index:02d}-{slugify(title)}{extension}"
                local_path = f"images/{filename}"
                target = remote_url if self.image_mode == "remote" else local_path
                self.append(f"![{title}]({target})")
                self.image_records.append(
                    {
                        "src": src,
                        "remote_url": remote_url,
                        "filename": filename,
                        "title": title,
                    }
                )
        elif tag == "li":
            self.ensure_blank()
            if self.list_stack and self.list_stack[-1]["type"] == "ol":
                self.list_stack[-1]["index"] += 1
                self.append(f"{self.list_stack[-1]['index']}. ")
            else:
                self.append("- ")
        if tag in {"ol", "ul"}:
            self.list_stack.append({"type": tag, "index": 0})
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "strong":
            self.append("**")
        elif tag == "em":
            self.append("*")
        elif tag == "a" and self.link_stack:
            link = self.link_stack.pop()
            self.append(f"]({link['href']})")
        elif tag in {"p", "h2", "h3", "h4", "li", "ol", "ul"}:
            self.ensure_blank()
        if tag in {"ol", "ul"} and self.list_stack:
            self.list_stack.pop()
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        data = normalize_text(data)
        if not data:
            return
        self.append(data)

    def markdown(self):
        text = "".join(self.out)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = text.replace("process limits)- [Link", "process limits) - [Link")
        text = text.replace("the[ Metrics", "the [Metrics")
        text = text.replace("process limits)-[Link", "process limits) - [Link")
        text = text.replace(")- [", ") - [")
        text = text.replace("),[", "), [")
        text = text.replace(" and[", " and [")
        text = text.replace(" In[", " In [")
        text = text.replace(" at[", " at [")
        text = text.replace(" on[", " on [")
        text = text.replace(" from[", " from [")
        text = text.replace(" the[", " the [")
        text = text.replace("2.660×", "2.660 ×")
        text = text.replace("URL=", "URL =")
        return text.strip() + "\n"


def extract_article_html():
    extractor = ArticleExtractor()
    extractor.feed(SOURCE_HTML.read_text(encoding="utf-8"))
    return "".join(extractor.parts)


def convert(image_mode):
    converter = MarkdownConverter(image_mode)
    converter.feed(extract_article_html())
    title = "# Explaining Where XmR Chart Scaling Constants Come From\n\n"
    return title + converter.markdown(), converter.image_records


def download_images(records):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    seen = set()
    for record in records:
        if record["filename"] in seen:
            continue
        seen.add(record["filename"])
        destination = IMAGES_DIR / record["filename"]
        if destination.exists() and destination.stat().st_size > 0:
            continue
        with urlopen(record["remote_url"]) as response:
            destination.write_bytes(response.read())


def download_preview_image():
    destination = IMAGES_DIR / "00-social-preview-sample-xmr.png"
    if destination.exists() and destination.stat().st_size > 0:
        return
    with urlopen("https://xmrit.com/sample_xmr.png") as response:
        destination.write_bytes(response.read())


def main():
    local_markdown, records = convert("local")
    remote_markdown, _ = convert("remote")
    LOCAL_MD.write_text(local_markdown, encoding="utf-8")
    REMOTE_MD.write_text(remote_markdown, encoding="utf-8")
    download_images(records)
    download_preview_image()
    README.write_text(
        """# Bear upload bundle

This folder contains a Bear-ready version of the XmR scaling constants article.

- `bear-post-remote-images.md`: easiest to paste into Bear; images point at the existing `xmrit.com` URLs.
- `bear-post-local-images.md`: same post, but image links point at the local `images/` folder.
- `images/`: downloaded copies of all article images, plus `00-social-preview-sample-xmr.png` for a social/cover image if Bear asks for one.

Suggested Bear workflow:

1. Paste `bear-post-remote-images.md` into Bear for a quick publish.
2. If you want Bear-hosted images instead, upload each file in `images/`, copy the Bear image URL it gives you, and replace the matching `images/...` link in `bear-post-local-images.md`.
3. Use `00-social-preview-sample-xmr.png` as the cover/social image, if your Bear settings expose that field.
""",
        encoding="utf-8",
    )
    print(f"Wrote {LOCAL_MD}")
    print(f"Wrote {REMOTE_MD}")
    print(f"Downloaded {len(records)} article images plus social preview into {IMAGES_DIR}")


if __name__ == "__main__":
    main()
