"""Conservative one-to-one pairing by filename."""
from difflib import SequenceMatcher
from pathlib import Path
import re

from media import normalize


def title_tokens(path):
    stem = Path(path).stem
    stem = re.sub(r'^\s*(?:(?:\((?:19|20)\d{2}\)|(?:19|20)\d{2}\s+-)\s*|\d{1,3}\s*[-_.–—]\s*)+', '', stem)
    return tuple(normalize(stem).split())


def similarity(left, right):
    if not left or not right:
        return 0
    if left == right:
        return 1
    short, long = sorted((left, right), key=len)
    if len(short) >= 2 and long[:len(short)] == short:
        # A contained title with a different volume number may be another book.
        suffix = long[len(short):]
        if not any(word.isdigit() for word in suffix):
            return .94
    if {word for word in left if word.isdigit()} != {word for word in right if word.isdigit()}:
        return 0
    short_text, long_text = ' '.join(left), ' '.join(right)
    if min(len(short_text), len(long_text)) < 12:
        return 0
    return min(.92, SequenceMatcher(None, short_text, long_text, autojunk=False).ratio())


def pairs_for(epubs, audios):
    if len(epubs) == len(audios) == 1:
        return [(epubs[0], audios[0])], [], []
    left = [title_tokens(path) for path in epubs]
    right = [title_tokens(path) for path in audios]
    scores = [[similarity(a, b) for b in right] for a in left]

    def unique_best(row):
        ranked = sorted(enumerate(row), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] < .88:
            return None
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < .035:
            return None
        return ranked[0][0]

    reverse = [unique_best([row[j] for row in scores]) for j in range(len(audios))]
    paired = {}
    for i, row in enumerate(scores):
        j = unique_best(row)
        if j is not None and reverse[j] == i:
            paired[i] = j
    used = set(paired.values())
    return ([(epubs[i], audios[j]) for i, j in paired.items()],
            [path for i, path in enumerate(epubs) if i not in paired],
            [path for j, path in enumerate(audios) if j not in used])
