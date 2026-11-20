"""Build the synthetic EPUB, tones, and sidecar without private input."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import wave
from zipfile import ZIP_STORED, ZipFile

ROOT = Path(__file__).resolve().parent
TITLE = "A small lantern"
TEXT = "The lantern warmed the window. Outside, the rain tapped gently."
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
<dc:title>{TITLE}</dc:title><dc:language>en</dc:language>
<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
</metadata><manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="sample" href="sample.xhtml" media-type="application/xhtml+xml"/>
</manifest><spine><itemref idref="sample"/></spine></package>""",
    "EPUB/nav.xhtml": f"""<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head><body><nav epub:type="toc"><ol>
<li><a href="sample.xhtml">{TITLE}</a></li></ol></nav></body></html>""",
    "EPUB/sample.xhtml": f"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{TITLE}</title></head><body><p>{TEXT}</p></body></html>""",
}

def fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {"filename": path.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

def main() -> None:
    ebook = ROOT / "example.epub"
    audio = ROOT / "example.m4b"
    word_count = len(TEXT.split())
    timings = [[i, 400 * i + 100, 400 * i + 360] for i in range(word_count) if i != 3]
    duration_ms = 400 * (word_count + 1)

    with ZipFile(ebook, "w", compression=ZIP_STORED) as archive:
        for name, content in ITEMS.items():
            archive.writestr(name, content)

    rate = 16000
    pcm = bytearray(duration_ms * rate // 1000 * 2)
    for i, start, end in timings:
        for sample in range(start * rate // 1000, end * rate // 1000):
            tone = math.sin(2 * math.pi * (330 + i * 25) * sample / rate)
            struct.pack_into("<h", pcm, 2 * sample, int(4500 * tone))
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "tones.wav"
        with wave.open(str(raw), "wb") as track:
            track.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            track.writeframes(pcm)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-c:a", "aac",
                        "-b:a", "48k", "-metadata", f"title={TITLE}", str(audio)], check=True)

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
            "epubWordCount": word_count,
            "audioStartMs": timings[0][1],
            "audioEndMs": timings[-1][2],
            "wordTimings": timings,
        }],
    }
    (ROOT / "example.sync-v2.json").write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
