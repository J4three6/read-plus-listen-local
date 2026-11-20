# Read+Listen local sidecar format

## File discovery and version

For `Book.epub`, look beside it for `Book.sync-v2.json`. Some installations also check `Book.json`. Use the content to identify the format. This document describes `schemaVersion: "2.0-word-alignment"`. An arbitrary file with a `.json` extension can contain a different format.

| Field | Meaning |
| --- | --- |
| `epub`, `audio` | Source descriptors. The reference engine supplies `filename`, `size` in bytes and a lowercase SHA-256 digest. Compare fingerprints when available to catch a mismatch between editions. |
| `audio.path` | Optional producer-local hint. It can be omitted or removed before sharing. Do not use it to fetch or open arbitrary files on another user's device. |
| `wordTimingFormat` | `["wordIndex", "startMs", "endMs"]` |
| `chapters` | Sections in EPUB reading order. Audio chapters and EPUB sections can differ. |
| `createdUtc`, `configuration`, `statistics`, `status` | Producer metadata. Useful for diagnostics. |

Each section has:

| Field | Meaning |
| --- | --- |
| `epubHref` | EPUB manifest href relative to the package document, optionally followed by an XHTML fragment. Decode URL escapes for matching. |
| `epubItemId` | EPUB manifest item ID. Sections within the same XHTML can share this ID. Use the fragment to distinguish them. |
| `epubSpineIndex` | In the reference engine, a one-based output section index. It counts split sections and is not necessarily the raw OPF spine position. |
| `epubChapter`, `epubTitle` | Display and legacy identifiers. Prefer the href and item ID for lookup. |
| `epubWordCount` | Number of tokens in the section's reference coordinate system. |
| `wordTimings` | Rows `[wordIndex, startMs, endMs]`. Indices are zero-based and section-local. Times are absolute milliseconds from the beginning of the entire audio file. |
| `audioStartMs`, `audioEndMs` | Optional section playback bounds. They can differ slightly from the first and last visible token timing. |
| `anchors`, `manualCalibration` | Optional alignment samples and a calibration point. A v2 consumer can use the full `wordTimings` array directly. Older sidecars may only have anchors. |

Unmatched tokens are omitted. An unmatched section can have an empty `wordTimings` array. Validate indices and times, tolerate overlapping word intervals, and do not assume that consecutive rows are consecutive words. For playback, select the most recent word start at or before the player position and check its end before drawing the word highlight. For a tap, seek to the matching row's start time. A strict client can leave a token without a timing unselectable. The sample file includes an unaligned token.

## Word coordinates

Word indices refer to tokens extracted from the EPUB's spine rather than a character offset in the whole book. The reference extractor walks the spine in reading order, excludes `script`, `style`, `nav` and `head`, removes U+00AD, U+200B and U+2060, and splits on whitespace. Punctuation remains attached to its token. Separate inline text nodes are separated for counting purposes.

- For documents with multiple valid TOC fragments, split at those fragment targets in document order. If a target is inside a paragraph or heading, that containing block starts the section. Text before the first fragment can form its own section.
- Unsplit sections normally count all body text. For certain narrative chapters, the reference implementation instead counts top-level `p`, `h1`, `h2`, `h3`, `blockquote` and `li` blocks, omits nested duplicates, and rejoins some split uppercase drop caps. The narrative selection and tokenization are implemented in [the reference extractor](../engine/media.py). Compare the extracted count with `epubWordCount` before applying indices.
- A sentence is a presentation choice calculated by the reader. The sidecar does not store sentence timings.

See [the synthetic sample](../examples/example.sync-v2.json) for the minimal timings and [the player](../player/) for a consumer. New sidecar producers should emit the exact same token coordinates or identify their own incompatible format with a different version identifier.
