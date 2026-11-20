"""Regenerate the Alice in Wonderland excerpt EPUB and timing sidecar."""
from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
import subprocess
from zipfile import ZIP_STORED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
TITLE = "Down the Rabbit-Hole"
TEXT = 'Down the Rabbit-Hole. Alice was beginning to get very tired of sitting by her sister on the bank, and of having nothing to do: once or twice she had peeped into the book her sister was reading, but it had no pictures or conversations in it, “and what is the use of a book,” thought Alice “without pictures or conversations?”'
ITEMS = {
    "mimetype": "application/epub+zip",
    "META-INF/container.xml": """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
    "EPUB/content.opf": f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="id">urn:uuid:95a615db-81fa-4344-aecb-b0acdc68ef12</dc:identifier>
<dc:title>Alice's Adventures in Wonderland (excerpt)</dc:title><dc:creator>Lewis Carroll</dc:creator><dc:language>en</dc:language>
<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
</metadata><manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="sample" href="sample.xhtml" media-type="application/xhtml+xml"/>
</manifest><spine><itemref idref="sample"/></spine></package>""",
    "EPUB/nav.xhtml": f"""<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head><body><nav epub:type="toc"><ol>
<li><a href="sample.xhtml">{TITLE}</a></li></ol></nav></body></html>""",
    "EPUB/sample.xhtml": f"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{TITLE}</title></head><body><h1>{TITLE}.</h1><p>{TEXT[len(TITLE) + 2:]}</p></body></html>""",
}

def fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {"filename": path.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

TIMINGS = [
    [0, 420, 700],
    [1, 700, 880],
    [2, 880, 2700],
    [3, 2700, 3140],
    [4, 3140, 3380],
    [5, 3380, 3760],
    [6, 3760, 3980],
    [7, 3980, 4160],
    [8, 4160, 4520],
    [9, 4520, 4940],
    [10, 4940, 5120],
    [11, 5120, 5340],
    [12, 5340, 5540],
    [13, 5540, 5780],
    [14, 5780, 6040],
    [15, 6040, 6240],
    [16, 6240, 6400],
    [17, 6400, 6760],
    [18, 6760, 7060],
    [19, 7060, 7240],
    [20, 7240, 7520],
    [21, 7520, 7800],
    [22, 7800, 8080],
    [23, 8080, 8540],
    [24, 8900, 9120],
    [25, 9120, 9340],
    [26, 9340, 9700],
    [27, 9700, 9900],
    [28, 9900, 10160],
    [29, 10160, 10560],
    [30, 10560, 10780],
    [31, 10780, 11040],
    [32, 11040, 11220],
    [33, 11220, 11440],
    [34, 11440, 11760],
    [35, 11760, 12020],
    [36, 12020, 12400],
    [37, 12660, 13260],
    [38, 13260, 13460],
    [39, 13460, 13620],
    [40, 13620, 13860],
    [41, 13860, 14400],
    [42, 14400, 14840],
    [43, 14840, 15400],
    [44, 15400, 15620],
    [45, 15620, 15840],
    [46, 16300, 16680],
    [47, 16680, 16980],
    [48, 16980, 17280],
    [49, 17280, 17520],
    [50, 17520, 17680],
    [51, 17680, 17900],
    [52, 17900, 17980],
    [53, 17980, 18420],
    [54, 18680, 18880],
    [55, 18880, 19300],
    [56, 19700, 20020],
    [57, 20020, 20640],
    [58, 20640, 21340],
    [59, 21340, 22000],
]

ORIGINAL_AUDIO_SHA256 = 'a2b40840f354920f6e46a91b9dfac11ec0190d3a77191779dfc4dd91009b6151'

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-audio", type=Path, help="Original M4B for this exact recording")
    args = parser.parse_args()
    ebook = ROOT / "example.epub"
    audio = ROOT / "example.m4b"
    if args.source_audio:
        signature = fingerprint(args.source_audio)
        if signature["sha256"] != ORIGINAL_AUDIO_SHA256:
            parser.error("The supplied recording does not match the one used for these timings.")
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-ss", "22", "-i", str(args.source_audio),
            "-t", "22", "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-c:a", "aac",
            "-b:a", "64k", "-metadata", "title=Down the Rabbit-Hole", "-metadata",
            "artist=Lewis Carroll", "-movflags", "+faststart", str(audio),
        ], check=True)
    with ZipFile(ebook, "w", compression=ZIP_STORED) as archive:
        for name, content in ITEMS.items():
            archive.writestr(ZipInfo(name), content)
    sidecar = {
        "schemaVersion": "2.0-word-alignment",
        "epub": fingerprint(ebook),
        "audio": fingerprint(audio),
        "status": "full_audio_processed",
        "wordTimingFormat": ["wordIndex", "startMs", "endMs"],
        "chapters": [{
            "epubChapter": 1,
            "epubHref": "sample.xhtml",
            "epubItemId": "sample",
            "epubTitle": TITLE,
            "epubSpineIndex": 1,
            "epubWordCount": len(TEXT.split()),
            "audioStartMs": TIMINGS[0][1],
            "audioEndMs": TIMINGS[-1][2],
            "wordTimings": TIMINGS,
        }],
    }
    (ROOT / "example.sync-v2.json").write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
