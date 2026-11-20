# Synthetic example

Load `example.epub`, `example.m4b` and `example.sync-v2.json` together. The EPUB contains original test text. The M4B plays a short tone for each aligned token, with silence at the skipped token. The assets contain no commercial book or narration.

The fixture is supplied to exercise the reader and integrations. Its timings are generated directly rather than by speech recognition. Regenerate it with Python and FFmpeg on PATH using `python generate.py`.
