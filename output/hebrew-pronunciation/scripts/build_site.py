#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCE_TRANSCRIPT = ROOT / "transcript.json"
SOURCE_INDEX = ROOT / "index.html"
SOURCE_PAGES = ROOT / "pages"
SITE_ROOT = ROOT / "site"
SITE_DATA = SITE_ROOT / "data"
SITE_AUDIO = SITE_ROOT / "assets" / "audio"

DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


class BuildError(Exception):
    pass


def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def stable_hash(payload: Dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def copy_static_assets() -> None:
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_INDEX, SITE_ROOT / "index.html")

    if SOURCE_PAGES.exists():
        destination = SITE_ROOT / "pages"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(SOURCE_PAGES, destination)


def elevenlabs_request(
    *,
    api_key: str,
    voice_id: str,
    text: str,
    model_id: str,
    output_format: str,
    language_code: Optional[str],
) -> bytes:
    query = urlencode({"output_format": output_format})
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?{query}"
    payload = {
        "text": text,
        "model_id": model_id,
    }

    if language_code:
        payload["language_code"] = language_code

    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            return response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BuildError(f"ElevenLabs returned {exc.code} for text '{text}': {body}") from exc
    except URLError as exc:
        raise BuildError(f"ElevenLabs request failed for text '{text}': {exc}") from exc


def ensure_audio(
    *,
    category: str,
    language: str,
    item_id: str,
    text: Optional[str],
    model_id: str,
    voice_id: Optional[str],
    api_key: Optional[str],
    output_format: str,
    allow_missing_audio: bool,
    manifest_entries: List[Dict],
    missing_items: List[Dict],
) -> Optional[str]:
    if not text:
        return None

    hash_input = {
        "category": category,
        "language": language,
        "model_id": model_id,
        "output_format": output_format,
        "text": text,
        "voice_id": voice_id,
    }
    filename = stable_hash(hash_input) + ".mp3"
    relative_path = f"assets/audio/{language}/{category}/{filename}"
    output_path = SITE_ROOT / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        manifest_entries.append(
            {
                "id": item_id,
                "language": language,
                "category": category,
                "status": "reused",
                "path": relative_path,
                "text": text,
                "model_id": model_id,
            }
        )
        return relative_path

    if not api_key or not voice_id:
        missing_items.append(
            {
                "id": item_id,
                "language": language,
                "category": category,
                "reason": "missing_credentials",
                "text": text,
            }
        )
        if allow_missing_audio:
            return None
        raise BuildError(
            f"Audio for {item_id} is missing and cannot be generated without "
            f"{'ELEVENLABS_API_KEY' if not api_key else ('ELEVENLABS_HEBREW_VOICE_ID' if language == 'he' else 'ELEVENLABS_ENGLISH_VOICE_ID')}."
        )

    audio_bytes = elevenlabs_request(
        api_key=api_key,
        voice_id=voice_id,
        text=text,
        model_id=model_id,
        output_format=output_format,
        language_code=language,
    )
    output_path.write_bytes(audio_bytes)
    manifest_entries.append(
        {
            "id": item_id,
            "language": language,
            "category": category,
            "status": "generated",
            "path": relative_path,
            "text": text,
            "model_id": model_id,
        }
    )
    return relative_path


def clone_word(word: Dict) -> Dict:
    clone = dict(word)
    clone["audio"] = {
        "he": {
            "word": None
        }
    }
    return clone


def clone_line(line: Dict) -> Dict:
    clone = dict(line)
    clone["audio"] = {
        "en": {
            "line": None
        }
    }
    return clone


def ordered_words(page: Dict) -> List[Dict]:
    return sorted(page.get("words", []), key=lambda item: item["order"])


def ordered_lines(page: Dict) -> List[Dict]:
    return sorted(page.get("lines", []), key=lambda item: item["order"])


def build_site_data(source: Dict, *, allow_missing_audio: bool) -> Tuple[Dict, Dict]:
    api_key = os.getenv("ELEVENLABS_API_KEY")
    hebrew_voice_id = os.getenv("ELEVENLABS_HEBREW_VOICE_ID")
    english_voice_id = os.getenv("ELEVENLABS_ENGLISH_VOICE_ID")
    hebrew_model = os.getenv("ELEVENLABS_HEBREW_MODEL", "eleven_v3")
    english_model = os.getenv("ELEVENLABS_ENGLISH_MODEL", "eleven_flash_v2_5")
    output_format = os.getenv("ELEVENLABS_OUTPUT_FORMAT", DEFAULT_OUTPUT_FORMAT)

    manifest_entries: List[Dict] = []
    missing_items: List[Dict] = []

    site_payload = {
        "version": source.get("version"),
        "generatedAt": os.getenv("HEBREW_READER_BUILD_TIMESTAMP", ""),
        "audioConfig": {
            "hebrewModel": hebrew_model,
            "englishModel": english_model,
            "outputFormat": output_format,
        },
        "pages": [],
    }

    for page in source.get("pages", []):
        page_out = {
            "id": page["id"],
            "page": page["page"],
            "title": page["title"],
            "status": page["status"],
            "image": page["image"],
            "englishText": page.get("englishText"),
            "notes": page.get("notes", []),
            "audio": {
                "en": {
                    "page": None
                }
            },
            "lines": [],
            "words": [],
        }

        words_by_id: Dict[str, Dict] = {}

        for word in ordered_words(page):
            word_out = clone_word(word)
            if word.get("status") == "verified":
                word_out["audio"]["he"]["word"] = ensure_audio(
                    category="words",
                    language="he",
                    item_id=word["id"],
                    text=word.get("spokenText"),
                    model_id=hebrew_model,
                    voice_id=hebrew_voice_id,
                    api_key=api_key,
                    output_format=output_format,
                    allow_missing_audio=allow_missing_audio,
                    manifest_entries=manifest_entries,
                    missing_items=missing_items,
                )
            page_out["words"].append(word_out)
            words_by_id[word_out["id"]] = word_out

        for line in ordered_lines(page):
            line_out = clone_line(line)
            if line.get("status") == "verified" and line.get("englishText"):
                line_out["audio"]["en"]["line"] = ensure_audio(
                    category="lines",
                    language="en",
                    item_id=line["id"],
                    text=line.get("englishText"),
                    model_id=english_model,
                    voice_id=english_voice_id,
                    api_key=api_key,
                    output_format=output_format,
                    allow_missing_audio=allow_missing_audio,
                    manifest_entries=manifest_entries,
                    missing_items=missing_items,
                )

            missing_word_ids = [word_id for word_id in line.get("wordIds", []) if word_id not in words_by_id]
            if missing_word_ids:
                raise BuildError(f"Line {line['id']} references unknown word ids: {', '.join(missing_word_ids)}")

            line_sequence = [
                words_by_id[word_id]["audio"]["he"]["word"]
                for word_id in line.get("wordIds", [])
                if words_by_id[word_id]["audio"]["he"]["word"]
            ]
            line_out["hebrewAudioSequence"] = (
                line_sequence if len(line_sequence) == len(line.get("wordIds", [])) else []
            )
            page_out["lines"].append(line_out)

        if page.get("status") == "verified" and page.get("englishText"):
            page_out["audio"]["en"]["page"] = ensure_audio(
                category="pages",
                language="en",
                item_id=page["id"],
                text=page.get("englishText"),
                model_id=english_model,
                voice_id=english_voice_id,
                api_key=api_key,
                output_format=output_format,
                allow_missing_audio=allow_missing_audio,
                manifest_entries=manifest_entries,
                missing_items=missing_items,
            )

        expected_page_word_ids = [
            word_id
            for line in page_out["lines"]
            for word_id in line.get("wordIds", [])
        ]
        page_sequence = [
            words_by_id[word_id]["audio"]["he"]["word"]
            for word_id in expected_page_word_ids
            if words_by_id[word_id]["audio"]["he"]["word"]
        ]
        page_out["hebrewAudioSequence"] = (
            page_sequence if len(page_sequence) == len(expected_page_word_ids) else []
        )
        site_payload["pages"].append(page_out)

    manifest = {
        "version": source.get("version"),
        "generatedAssets": manifest_entries,
        "missingAssets": missing_items,
        "summary": {
            "generated": sum(1 for item in manifest_entries if item["status"] == "generated"),
            "reused": sum(1 for item in manifest_entries if item["status"] == "reused"),
            "missing": len(missing_items),
        },
    }
    return site_payload, manifest


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the static Hebrew pronunciation site.")
    parser.add_argument(
        "--allow-missing-audio",
        action="store_true",
        help="Build the site even if verified items do not have audio yet.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    copy_static_assets()

    source = load_json(SOURCE_TRANSCRIPT)
    site_payload, manifest = build_site_data(source, allow_missing_audio=args.allow_missing_audio)

    write_json(SITE_DATA / "reader.json", site_payload)
    write_json(SITE_DATA / "audio-manifest.json", manifest)

    print(f"Built site data for {len(site_payload['pages'])} page(s).")
    print(
        "Audio summary: "
        f"{manifest['summary']['generated']} generated, "
        f"{manifest['summary']['reused']} reused, "
        f"{manifest['summary']['missing']} missing."
    )
    if manifest["missingAssets"]:
        print("Missing audio assets:")
        for item in manifest["missingAssets"]:
            print(f"  - {item['id']} ({item['language']}/{item['category']})")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except BuildError as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
