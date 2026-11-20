"""Full-audiobook EPUB synchronization with absolute word timestamps."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import ceil
import os
from pathlib import Path
import tempfile

from alignment import align_words
from media import (
    audio_chapters, audio_clip, configure_cuda_dlls, epub_chapters, ffprobe,
    fingerprint, normalize, recognize,
)

CHUNK_SECONDS = 60
CHUNK_CONTEXT = 3


class SyncCancelled(Exception):
    """The user stopped the run."""


def output_path(epub_path):
    path = Path(epub_path)
    return path.with_suffix('.sync-v2.json')


def transcribe_full(model, audio, duration, language, scratch, check, on_chunk):
    """Each minute owns its words; extra context protects both cut edges."""
    transcript = []
    clip = scratch / 'chunk.wav'

    def decode(start, end, context):
        check()
        left, right = max(0, start - context), min(duration, end + context)
        audio_clip(audio, left, right - left, clip)
        check()
        words = []
        for word in recognize(model, clip, language):
            first = max(0, left + word['start'])
            last = min(duration, left + word['end'])
            if first < last and start <= (first + last) / 2 < end:
                words.append({**word, 'start': first, 'end': last})
        return words

    for seconds in range(0, ceil(duration), CHUNK_SECONDS):
        end = min(duration, seconds + CHUNK_SECONDS)
        words = decode(seconds, end, CHUNK_CONTEXT)
        # Music and introductions can cause Whisper to skip a spoken passage.
        # Retry long gaps in smaller windows without replacing words already found.
        cursor = seconds
        recovered = []
        for first, last in [(w['start'], w['end']) for w in words] + [(end, end)]:
            if first - cursor >= 8:
                gap_start = cursor
                while gap_start < first:
                    gap_end = min(first, gap_start + 8)
                    recovered.extend(decode(gap_start, gap_end, 2))
                    gap_start = gap_end
            cursor = max(cursor, last)
        for word in sorted(words + recovered, key=lambda item: item['start']):
            start, stop = word['start'], word['end']
            if transcript and start < transcript[-1]['start']:
                start = transcript[-1]['start']
                if stop <= start:
                    continue
            if (transcript and word['normalized'] == transcript[-1]['normalized']
                    and min(stop, transcript[-1]['end']) - start >= .5 * (stop - start)):
                continue
            transcript.append({**word, 'start': start, 'end': stop})
        on_chunk(end, len(transcript))
    return transcript


def studio_anchors(chapter, timings, manual, cap=120):
    """Expose a bounded set of exact word starts to existing Studio versions."""
    if not timings:
        return []
    step = max(1, ceil(len(timings) / (cap - 2)))
    selected = {row[0]: row for row in timings[::step]}
    selected[timings[-1][0]] = timings[-1]
    if manual:
        selected[manual['wordIndex']] = next(row for row in timings if row[0] == manual['wordIndex'])
    anchors = []
    for index, start, _ in sorted(selected.values()):
        confirmed = manual is not None and index == manual['wordIndex']
        text = chapter['words'][index]['text']
        anchors.append({'wordStart': index, 'wordEnd': index + 1,
                        'fraction': (index + .5) / len(chapter['words']), 'text': text,
                        'match': {'startMs': start, 'endMs': start, 'confidence': 1.0,
                                  'recognizedText': manual['audioWord'] if confirmed else text,
                                  'source': 'user_verified' if confirmed else 'full_alignment'},
                        'status': 'matched'})
    return anchors


def export_chapters(chapters, transcript, matches, audio_parts, calibration, check):
    entries = []
    offset = 0
    for chapter in chapters:
        check()
        words = chapter['alignmentWords']
        timings = []
        matched = 0
        first, last = None, None
        for i, word in enumerate(words):
            link = matches.get(offset + i)
            if link is None:
                continue
            matched += 1
            start = round(transcript[link[0]]['start'] * 1000)
            end = max(start + 1, round(transcript[link[1]]['end'] * 1000))
            first = start if first is None else min(first, start)
            last = end if last is None else max(last, end)
            if word['index'] is not None:
                timings.append([word['index'], start, end])
        offset += len(words)
        entry = {'epubChapter': chapter['index'], 'epubHref': chapter['href'],
                 'epubItemId': chapter['itemId'], 'epubTitle': chapter['title'],
                 'epubSpineIndex': chapter['spineIndex'],
                 'epubWordCount': len(chapter['words']), 'wordTimings': timings,
                 'alignmentWordCount': len(words), 'alignmentMatchedWordCount': matched,
                 'status': 'word_aligned' if timings else 'unverified', 'anchors': []}
        if first is not None:
            entry.update(audioStartMs=first, audioEndMs=last)
            part = next((p for p in audio_parts if p['start'] <= first / 1000 < p['end']), None)
            if part is not None:
                entry.update(audioChapter=part['index'], audioTitle=part['title'])
        manual = None
        if calibration and chapter is calibration[0]:
            _, wi, word = calibration
            start = round(word['start'] * 1000)
            manual = {'wordIndex': wi, 'audioTimeMs': start, 'narrationStartMs': start,
                      'epubWord': chapter['words'][wi]['text'], 'audioWord': word['text'],
                      'source': 'user_verified'}
            entry.update(manualCalibration=manual, narrationStartMs=start)
        entry['anchors'] = studio_anchors(chapter, timings, manual)
        entries.append(entry)

    # Adjacent sections can straddle a single ASR token. Avoid an ambiguous
    # active section in applications that use the chapter's half-open bounds.
    aligned = [entry for entry in entries if entry['wordTimings']]
    for entry, following in zip(aligned, aligned[1:]):
        if entry['audioStartMs'] < following['audioStartMs'] < entry['audioEndMs']:
            entry['audioEndMs'] = following['audioStartMs']
    return entries


def write_result(destination, result):
    """Publish a complete snapshot without overwriting an existing export."""
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.tmp', mode='w',
                                     encoding='utf-8', delete=False) as output:
        staged = Path(output.name)
        try:
            json.dump(result, output, ensure_ascii=False, separators=(',', ':'))
            output.write('\n')
            output.close()
            # Windows rename fails if the target already exists.
            if os.name == 'nt':
                staged.rename(destination)
            else:
                os.link(staged, destination)
        finally:
            output.close()
            staged.unlink(missing_ok=True)


def generate(epub_path, audio_path, *, device, progress, cancel_event=None):
    """Align the full book and report language-neutral progress events."""
    epub, audio = Path(epub_path), Path(audio_path)
    destination = output_path(epub)
    if not epub.is_file() or not audio.is_file():
        raise FileNotFoundError(epub if not epub.is_file() else audio)
    if destination.exists():
        raise FileExistsError(destination)

    def check():
        if cancel_event is not None and cancel_event.is_set():
            raise SyncCancelled()

    try:
        check()
        progress('prepare', 0, 0)
        chapters = epub_chapters(epub)
        metadata = ffprobe(audio)
        parts = audio_chapters(audio, metadata)
        duration = float(metadata['format']['duration'])
        chunks = ceil(duration / CHUNK_SECONDS)
        tasks = chunks + 2
        progress('model', 0, tasks)
        if device.kind == 'cuda':
            configure_cuda_dlls()
        from faster_whisper import WhisperModel
        model = WhisperModel('base', device=device.kind, device_index=device.index,
                             compute_type=device.compute_type)
        check()
        progress('audio', 0, tasks)
        with tempfile.TemporaryDirectory(prefix='readlisten_v3_') as temp:
            spoken = transcribe_full(
                model, audio, duration, '', Path(temp), check,
                lambda end, count: progress('audio', ceil(end / CHUNK_SECONDS), tasks,
                                            round(end), round(duration), count))
        check()
        progress('align', chunks, tasks)
        book = [word for section in chapters for word in section['alignmentWords']]
        matches = align_words(book, spoken, normalize, check)
        entries = export_chapters(chapters, spoken, matches, parts, None, check)
        progress('save', chunks + 1, tasks)
        result = {'schemaVersion': '2.0-word-alignment', 'createdUtc': datetime.now(timezone.utc).isoformat(),
                  'epub': fingerprint(epub),
                  'audio': {**fingerprint(audio), 'path': str(audio.absolute())},
                  'configuration': {'model': 'base', 'device': device.kind, 'deviceIndex': device.index,
                                    'computeType': device.compute_type, 'language': 'auto',
                                    'alignmentMode': 'full_book'},
                  'status': 'full_audio_processed' if matches else 'no_alignment',
                  'wordTimingFormat': ['wordIndex', 'startMs', 'endMs'],
                  'statistics': {'epubWords': len(book), 'matchedEpubWords': len(matches),
                                 'recognizedAudioWords': len(spoken), 'processedAudioMs': round(duration * 1000)},
                  'chapters': entries}
        check()
        write_result(destination, result)
        progress('done', tasks, tasks, len(matches), len(book))
        return destination
    except SyncCancelled:
        return None
