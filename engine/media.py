from __future__ import annotations
import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from epub_fragments import split_at_fragments, toc_fragments


def configure_cuda_dlls() -> None:
    """Expose pip-installed NVIDIA CUDA 12/cuDNN 9 DLLs to CTranslate2 on Windows.

    Keep add_dll_directory handles alive for the duration of the process.
    """
    import os
    import sys

    if sys.platform != 'win32':
        return

    import ctypes

    site_packages = Path(sys.prefix) / 'Lib' / 'site-packages'
    folders = [site_packages / 'nvidia' / 'cublas' / 'bin',
               site_packages / 'nvidia' / 'cudnn' / 'bin',
               site_packages / 'ctranslate2']
    existing = [folder for folder in folders if folder.is_dir()]
    if not existing:
        return

    # Keep the handles alive; closing them removes the DLL search directories.
    global _cuda_dll_handles
    if not _cuda_dll_handles:
        _cuda_dll_handles = [os.add_dll_directory(str(folder)) for folder in existing]

    # Explicitly load dependencies in order, as CTranslate2 may use the
    # Windows native loader rather than Python's extension-module loader.
    for dll_name in ('cublasLt64_12.dll', 'cublas64_12.dll', 'cudnn64_9.dll'):
        dll_path = next((folder / dll_name for folder in existing
                         if (folder / dll_name).is_file()), None)
        if dll_path is not None:
            try:
                ctypes.WinDLL(str(dll_path))
            except OSError as exc:
                raise RuntimeError(
                    f'No se pudo cargar {dll_name} desde {dll_path}. '
                    'Comprueba que las dependencias NVIDIA sean compatibles. '
                    f'Detalle: {exc}') from exc


_cuda_dll_handles = []


def normalize(s: str) -> str:
    s = unicodedata.normalize('NFKD', s.casefold())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.replace('\u00ad', '').replace('\u200b', '').replace('\u2060', '')
    return re.sub(r'[^\w]+', ' ', s, flags=re.UNICODE).strip()


def fingerprint(path: Path) -> dict:
    # Full file SHA-256 avoids false matches when replacing books.
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return {'filename': path.name, 'size': path.stat().st_size, 'sha256': h.hexdigest()}


def _no_console() -> dict:
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}


def ffprobe(path: Path) -> dict:
    exe = shutil.which('ffprobe')
    if not exe:
        raise RuntimeError('No se encontró ffprobe. Instala FFmpeg y agrégalo al PATH.')
    result = subprocess.run([exe, '-v', 'error', '-show_chapters', '-show_format',
                             '-of', 'json', str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, **_no_console())
    if result.returncode:
        raise RuntimeError('ffprobe: ' + result.stderr.strip()[:700])
    return json.loads(result.stdout)


def fix_mojibake(value: str) -> str:
    """Repair metadata already misdecoded as cp1252/latin1, without touching valid text."""
    if not isinstance(value, str) or not any(x in value for x in ('Ã', 'Â', 'â€')):
        return value
    for codec in ('cp1252', 'latin-1'):
        try:
            candidate = value.encode(codec).decode('utf-8')
            if candidate.count('Ã') + candidate.count('Â') < value.count('Ã') + value.count('Â'):
                return candidate
        except (UnicodeError, ValueError):
            pass
    return value


def audio_chapters(path: Path, metadata: dict | None = None) -> list[dict]:
    metadata = ffprobe(path) if metadata is None else metadata
    total = float(metadata.get('format', {}).get('duration', 0))
    if total <= 0:
        raise RuntimeError('No fue posible determinar la duración del audiolibro.')
    chapters = []
    for i, c in enumerate(metadata.get('chapters', [])):
        start, end = float(c['start_time']), float(c['end_time'])
        if end > start:
            chapters.append({'index': i + 1, 'title': fix_mojibake(c.get('tags', {}).get('title', f'Pista {i+1}')),
                             'start': start, 'end': end})
    return chapters or [{'index': 1, 'title': 'Audiolibro completo', 'start': 0., 'end': total}]


def epub_chapters(path: Path) -> list[dict]:
    """Read the EPUB spine, retaining the tokenization Studio uses for narrative sections."""
    try:
        from ebooklib import epub, ITEM_DOCUMENT
        from bs4 import BeautifulSoup, Comment, NavigableString
    except ImportError as exc:
        raise RuntimeError('Faltan ebooklib/bs4 en el entorno virtual.') from exc
    book = epub.read_epub(str(path), options={'ignore_ncx': True})
    items = {item.get_id(): item for item in book.get_items_of_type(ITEM_DOCUMENT)}
    from urllib.parse import unquote
    toc_titles = {}
    def walk(nodes):
        for node in nodes:
            if isinstance(node, (tuple, list)):
                walk(node)
            elif hasattr(node, 'href') and hasattr(node, 'title'):
                href = unquote(node.href.split('#')[0]).lstrip('/')
                toc_titles[href] = node.title
    walk(book.toc)
    fragments = toc_fragments(book.toc)
    # Match TOC titles by basename when
    # publishers store TOC paths relative to their navigation document.
    toc_basenames = {k.rsplit('/', 1)[-1]: v for k, v in toc_titles.items()}
    output = []
    for entry in book.spine:
        item = items.get(entry[0])
        if item is None:
            continue
        href = item.get_name()
        title = toc_titles.get(href) or toc_basenames.get(href.rsplit('/', 1)[-1])
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        for bad in soup(['script', 'style', 'nav', 'head']):
            bad.decompose()
        heading = soup.find(['h1', 'h2', 'h3'])
        heading_text = heading.get_text(' ', strip=True).replace('\u00ad', '') if heading else ''
        split = split_at_fragments(soup.body or soup, href, fragments.get(href, {}),
                                   heading_text or href)
        if split:
            for section_href, section_title, section_blocks in split:
                words = [{'text': word, 'block': i} for i, block in enumerate(section_blocks)
                         for word in block.split()]
                output.append({'spineIndex': len(output) + 1,
                               'studioNarrative': bool(re.match(r'^\s*(?:[IVXLCDM]+|\d+)\.', section_title)),
                               'itemId': item.get_id(), 'href': section_href, 'title': section_title,
                               'words': words, 'alignmentWords': [
                                   {**word, 'index': i} for i, word in enumerate(words)]})
            continue
        narrative = bool(title and heading and (
            re.search(r'\b(?:cap[ií]tulo|chapter)\s*\d+\b', heading_text, re.I)
            or re.match(r'^\s*\d+[.\s-]', title)))
        blocks = []
        display_blocks = {}
        for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'blockquote', 'li']):
            if tag.find_parent(['p', 'h1', 'h2', 'h3', 'blockquote', 'li']):
                continue
            text = ' '.join(tag.stripped_strings).replace('\u00ad', '').replace('\u200b', '').replace('\u2060', '')
            text = re.sub(r'\s+', ' ', text).strip()
            # Dropcap styles may split the first word: "H ABÍAN" -> "HABÍAN".
            if tag.name == 'p':
                text = re.sub(r'^([A-ZÁÉÍÓÚÑ]) ([A-ZÁÉÍÓÚÑ]{1,12})(?=\s|[,.!?;:])', r'\1\2', text)
            if text:
                display_blocks[id(tag)] = text.split()
                blocks.append(text)
        words = [{'text': word, 'block': i} for i, block in enumerate(blocks) for word in block.split()]
        narrative = narrative and len(words) >= 12
        if not narrative:
            body = soup.body or soup
            text = ' '.join(body.stripped_strings).replace('\u00ad', '').replace('\u200b', '').replace('\u2060', '')
            blocks = [' '.join(text.split())] if text.strip() else []
            words = [{'text': word, 'block': 0} for word in text.split()]
        if narrative:
            # Preserve Studio's word indices while including text outside its
            # rendered paragraph/heading blocks in the global comparison.
            alignment_words = []
            display_index = 0
            for node in (soup.body or soup).descendants:
                displayed = display_blocks.get(id(node))
                if displayed is not None:
                    for token in displayed:
                        alignment_words.append({'text': token, 'index': display_index})
                        display_index += 1
                elif isinstance(node, NavigableString) and not isinstance(node, Comment):
                    if any(id(parent) in display_blocks for parent in node.parents):
                        continue
                    text = str(node).replace('\u00ad', '').replace('\u200b', '').replace('\u2060', '')
                    alignment_words.extend({'text': token, 'index': None} for token in text.split())
        else:
            alignment_words = [{**word, 'index': i} for i, word in enumerate(words)]
        if words:
            output.append({'spineIndex': len(output) + 1, 'studioNarrative': narrative, 'itemId': item.get_id(),
                           'href': href, 'title': title or heading_text or href,
                           'words': words, 'alignmentWords': alignment_words})
    if not output:
        raise RuntimeError('No se encontró texto en el orden de lectura del EPUB.')
    # Keep the visible chapter numbers Studio already assigns to TOC chapters.
    narrative_index, extra_index = 0, sum(chapter['studioNarrative'] for chapter in output)
    for chapter in output:
        if chapter.pop('studioNarrative'):
            narrative_index += 1
            chapter['index'] = narrative_index
        else:
            extra_index += 1
            chapter['index'] = extra_index
    return output


def audio_clip(path: Path, start: float, duration: float, destination: Path) -> None:
    exe = shutil.which('ffmpeg')
    if not exe:
        raise RuntimeError('No se encontró ffmpeg. Instala FFmpeg y agrégalo al PATH.')
    result = subprocess.run([exe, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                             '-ss', f'{start:.3f}', '-i', str(path), '-t', f'{duration:.3f}',
                             '-vn', '-ac', '1', '-ar', '16000', '-f', 'wav', str(destination)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, **_no_console())
    if result.returncode:
        raise RuntimeError('ffmpeg: ' + result.stderr.strip()[:700])


def _transcribe_compatible(model, clip: Path, language: str | None):
    """Work around PyAV releases that reject metadata_errors in av.open.

    Some faster-whisper versions pass this optional argument to PyAV.
    The fallback only removes that keyword if the precise compatibility
    error occurs, preserving all other errors for diagnosis.
    """
    import av
    original_open = av.open

    def compatible_open(*args, **kwargs):
        try:
            return original_open(*args, **kwargs)
        except TypeError as exc:
            if 'metadata_errors' not in str(exc) or 'metadata_errors' not in kwargs:
                raise
            kwargs = dict(kwargs)
            kwargs.pop('metadata_errors')
            return original_open(*args, **kwargs)

    av.open = compatible_open
    try:
        segments, info = model.transcribe(
            str(clip), language=language or None, word_timestamps=True,
            vad_filter=True, beam_size=3
        )
        # Whisper transcription is lazy: decoding may occur during iteration.
        return list(segments), info
    finally:
        av.open = original_open


def recognize(model, clip: Path, language: str | None) -> list[dict]:
    segments, _ = _transcribe_compatible(model, clip, language)
    words = []
    for segment in segments:
        for w in (segment.words or []):
            token = normalize(w.word)
            if token:
                words.append({'text': w.word.strip(), 'normalized': token,
                              'start': float(w.start), 'end': float(w.end)})
    return words
