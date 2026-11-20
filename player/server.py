from __future__ import annotations
import json, re, threading, webbrowser, mimetypes, os, tempfile, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup

from epub_fragments import split_at_fragments, toc_fragments

ROOT=Path(__file__).resolve().parent
state={'epub':None,'audio':None,'sync':None,'chapters':[],'sync_path':None,'audioRevision':None}
temporary_uploads = tempfile.TemporaryDirectory(prefix='read-listen-')
UPLOADS = Path(temporary_uploads.name)

def clean_text(text: str) -> str:
    return text.replace('\u00ad', '').replace('\u200b', '').replace('\u2060', '')


def full_text_blocks(body) -> list[str]:
    """Retain visual breaks without changing Sync Engine 2's word indices."""
    block_names = ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote',
                   'li', 'section', 'pre', 'td', 'th', 'figcaption']
    blocks, tokens = [], []
    previous_block = None
    for part in body.strings:
        words = clean_text(part).split()
        if not words:
            continue
        block = part.find_parent(block_names)
        if tokens and block is not previous_block:
            blocks.append(' '.join(tokens))
            tokens = []
        tokens.extend(words)
        previous_block = block
    if tokens:
        blocks.append(' '.join(tokens))
    return blocks


def epub_sections(path: Path, *, split_toc: bool = False) -> list[dict]:
    """Read EPUB spine documents using the same word coordinates as Engine 2."""
    book = epub.read_epub(str(path), options={'ignore_ncx': True})
    items = {item.get_id(): item for item in book.get_items_of_type(ITEM_DOCUMENT)}
    toc_titles = {}

    def walk(nodes):
        for node in nodes:
            if isinstance(node, (tuple, list)):
                walk(node)
            elif hasattr(node, 'href') and hasattr(node, 'title'):
                href = unquote(node.href.split('#')[0]).lstrip('/')
                toc_titles[href] = node.title

    walk(book.toc)
    fragments = toc_fragments(book.toc) if split_toc else {}
    toc_basenames = {k.rsplit('/', 1)[-1]: v for k, v in toc_titles.items()}
    sections = []
    tags = ['p', 'h1', 'h2', 'h3', 'blockquote', 'li']
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
                sections.append({'itemId': item.get_id(), 'href': section_href, 'title': section_title,
                                 'blocks': section_blocks,
                                 'wordCount': sum(len(block.split()) for block in section_blocks),
                                 'legacyChapter': bool(re.match(r'^\s*(?:[IVXLCDM]+|\d+)\.', section_title))})
            continue
        legacy_chapter = bool(title and heading and (
            re.search(r'\b(?:cap[ií]tulo|chapter)\s*\d+\b', heading_text, re.I)
            or re.match(r'^\s*\d+[.\s-]', title)))
        blocks = []
        if legacy_chapter:
            for tag in soup.find_all(tags):
                if tag.find_parent(tags):
                    continue
                text = ' '.join(clean_text(' '.join(tag.stripped_strings)).split())
                if tag.name == 'p':
                    text = re.sub(r'^([A-ZÁÉÍÓÚÑ]) ([A-ZÁÉÍÓÚÑ]{1,12})(?=\s|[,.!?;:])',
                                  r'\1\2', text)
                if text:
                    blocks.append(text)
            legacy_chapter = sum(len(block.split()) for block in blocks) >= 12
        if not legacy_chapter:
            blocks = full_text_blocks(soup.body or soup)
        if blocks:
            sections.append({'itemId': item.get_id(), 'href': href,
                             'title': title or heading_text or href, 'blocks': blocks,
                             'wordCount': sum(len(block.split()) for block in blocks),
                             'legacyChapter': legacy_chapter})
    if not sections:
        raise RuntimeError('No se encontró texto en el orden de lectura del EPUB.')
    narrative_index = 0
    extra_index = sum(section['legacyChapter'] for section in sections)
    for section in sections:
        if section['legacyChapter']:
            narrative_index += 1
            section['index'] = narrative_index
        else:
            extra_index += 1
            section['index'] = extra_index
    return sections


def reader_sections(sections: list[dict], sync: dict) -> list[dict]:
    # Keep the original index for older JSON files that identify chapters by number.
    if not str(sync.get('schemaVersion', '')).startswith('2.'):
        return [section for section in sections if section['legacyChapter']] or sections
    return sections


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,obj,status=200):
        b=json.dumps(obj,ensure_ascii=False).encode('utf-8');self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def request_is_local(self) -> bool:
        port = self.server.server_address[1]
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        host = self.headers.get('Host', '').lower()
        origin = self.headers.get('Origin')
        return (host in hosts and (origin is None or origin == f'http://{host}')
                and self.headers.get('Sec-Fetch-Site') != 'cross-site')

    def do_GET(self):
        if not self.request_is_local():
            return self.send_error(403)
        path=urlparse(self.path).path
        if path=='/':
            b=(ROOT/'index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
        elif path=='/api/state':
            sync=state['sync'] or {}
            sections = state['chapters']
            if state['epub'] and any('#' in (entry.get('epubHref') or '') for entry in sync.get('chapters', [])):
                sections = epub_sections(state['epub'], split_toc=True)
            self.send_json({'files':{'epub':state['epub'].name if state['epub'] else None,'audio':state['audio'].name if state['audio'] else None,'sync':state['sync_path'].name if state['sync_path'] else None},'sync':sync,'sections':reader_sections(sections, sync),'audioRevision':state['audioRevision']})
        elif path=='/audio':
            p=state['audio']
            if not p or not p.is_file():return self.send_error(404)
            size=p.stat().st_size; rg=self.headers.get('Range','');m=re.match(r'bytes=(\d*)-(\d*)',rg)
            if m:
                start=int(m.group(1) or 0);end=min(size-1,int(m.group(2)) if m.group(2) else size-1)
                status = 416 if start >= size or end < start else 206
            else:
                start, end, status = 0, size - 1, 200
            try:
                self.send_response(status)
                if status == 416:
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.end_headers()
                    return
                self.send_header('Content-Type', 'audio/mp4')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Length', str(end - start + 1))
                if status == 206:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
            except ConnectionError:
                return
            with p.open('rb') as audio:
                audio.seek(start)
                remaining = end - start + 1
                while remaining:
                    data = audio.read(min(256 * 1024, remaining))
                    if not data:
                        break
                    try:
                        self.wfile.write(data)
                    except ConnectionError:
                        # A seek or reload can abandon an HTTP range mid-stream.
                        return
                    remaining -= len(data)
        else:self.send_error(404)
    def do_POST(self):
        if not self.request_is_local():
            return self.send_error(403)
        if self.path.startswith('/api/upload?'):
            from urllib.parse import parse_qs, unquote
            kind=parse_qs(urlparse(self.path).query).get('kind',[''])[0]
            filename=unquote(self.headers.get('X-Filename',''))
            if kind not in ('epub','audio','sync') or not filename or Path(filename).name!=filename:
                return self.send_json({'error':'Tipo o nombre inválido'},400)
            expected={'epub':'.epub','audio':'.m4b','sync':'.json'}[kind]
            if Path(filename).suffix.lower()!=expected:
                return self.send_json({'error':f'Se esperaba un archivo {expected}'},400)
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n<=0 or (kind!='audio' and n>100*1024*1024):
                    raise ValueError('Tamaño de archivo inválido')
                dest=UPLOADS/(uuid.uuid4().hex+'_'+filename)
                with dest.open('wb') as out:
                    remaining=n
                    while remaining:
                        block=self.rfile.read(min(1024*1024,remaining))
                        if not block:raise ValueError('Carga incompleta')
                        out.write(block);remaining-=len(block)
                if kind=='epub':
                    sections=epub_sections(dest)
                    if not sections:raise ValueError('EPUB sin secciones legibles')
                    state['chapters']=sections;state['epub']=dest
                elif kind=='audio':
                    state.update(audio=dest, audioRevision=uuid.uuid4().hex)
                else:
                    sync=json.loads(dest.read_text(encoding='utf-8-sig'))
                    if not isinstance(sync.get('chapters'),list):raise ValueError('JSON sin capítulos')
                    state['sync']=sync;state['sync_path']=dest
                self.send_json({'ok':True,'name':filename})
            except Exception as exc:
                try:
                    if 'dest' in locals():dest.unlink(missing_ok=True)
                except Exception:pass
                self.send_json({'error':str(exc)},400)
            return
        if self.path!='/api/open':return self.send_error(404)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n>32768:raise ValueError('Solicitud demasiado grande')
            data=json.loads(self.rfile.read(n));kind=data.get('kind');path=Path(data.get('path','')).expanduser()
            if kind not in ('epub','audio','sync') or not path.is_file():raise ValueError('Archivo no encontrado')
            if kind=='epub':
                sections=epub_sections(path)
                if not sections:raise ValueError('EPUB sin secciones legibles')
                state['chapters']=sections;state['epub']=path
            elif kind=='audio':
                state.update(audio=path, audioRevision=uuid.uuid4().hex)
            else:
                sync=json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(sync.get('chapters'),list):raise ValueError('JSON sin lista de capítulos')
                state['sync']=sync;state['sync_path']=path
            self.send_json({'ok':True})
        except Exception as exc:self.send_json({'error':str(exc)},400)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=18765);args=ap.parse_args()
    url=f'http://127.0.0.1:{args.port}'
    print('Read & Listen Player:',url,flush=True)
    threading.Timer(.7,lambda:webbrowser.open(url)).start()
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
