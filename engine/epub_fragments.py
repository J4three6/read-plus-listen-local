"""Resolve TOC destinations that share an XHTML document."""
from collections import defaultdict
from urllib.parse import unquote, urldefrag


def toc_fragments(nodes):
    fragments = defaultdict(dict)

    def walk(entries):
        for entry in entries:
            if isinstance(entry, (tuple, list)):
                walk(entry)
            elif getattr(entry, 'href', None) and getattr(entry, 'title', None):
                path, fragment = map(unquote, urldefrag(entry.href))
                if fragment:
                    fragments[path.lstrip('/')].setdefault(fragment, entry.title)

    walk(nodes)
    return fragments


def split_at_fragments(body, href, destinations, fallback_title):
    """Return (stable href, title, text blocks) in document order."""
    if len(destinations) < 2:
        return []
    markers = {}
    for fragment, title in destinations.items():
        target = body.find(id=fragment) or body.find('a', attrs={'name': fragment})
        if target is None:
            continue
        # A publisher may put an empty anchor inside the chapter heading.
        block = target.find_parent(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        boundary = target if block is None else block
        markers.setdefault(id(boundary), (f'{href}#{fragment}', title))
    if len(markers) < 2:
        return []

    text_nodes = {id(node) for node in body.strings}
    block_names = ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                   'blockquote', 'li', 'section', 'pre', 'td', 'th', 'figcaption']
    result, blocks, words = [], [], []
    section = (href, fallback_title)
    previous_block = None
    for node in body.descendants:
        marker = markers.get(id(node))
        if marker is not None:
            if words:
                blocks.append(' '.join(words))
            if blocks:
                result.append((*section, blocks))
            section = marker
            blocks, words, previous_block = [], [], None
        if id(node) not in text_nodes:
            continue
        tokens = str(node).replace('\u00ad', '').replace('\u200b', '').replace('\u2060', '').split()
        if not tokens:
            continue
        block = node.find_parent(block_names)
        if words and block is not previous_block:
            blocks.append(' '.join(words))
            words = []
        words.extend(tokens)
        previous_block = block
    if words:
        blocks.append(' '.join(words))
    if blocks:
        result.append((*section, blocks))
    return result
