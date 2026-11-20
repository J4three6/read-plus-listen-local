"""Monotone alignment of complete EPUB and ASR token sequences."""
from bisect import bisect_left
from difflib import SequenceMatcher


def unique_positions(tokens, width, check=lambda: None):
    positions = {}
    for i in range(len(tokens) - width + 1):
        if i % 4096 == 0:
            check()
        phrase = tuple(tokens[i:i + width])
        positions[phrase] = i if phrase not in positions else -1
    return positions


def monotone_seeds(book, speech, check, width=5):
    spoken = unique_positions(speech, width, check)
    written = unique_positions(book, width, check)
    tails, tail_indices, candidates, parents = [], [], [], []
    for phrase, i in written.items():  # First occurrence order.
        j = spoken.get(phrase, -1)
        if i < 0 or j < 0:
            continue
        pos = bisect_left(tails, j)
        parents.append(tail_indices[pos - 1] if pos else -1)
        candidates.append((i, j))
        if pos == len(tails):
            tails.append(j)
            tail_indices.append(len(candidates) - 1)
        else:
            tails[pos] = j
            tail_indices[pos] = len(candidates) - 1
    chain = []
    index = tail_indices[-1] if tail_indices else -1
    while index >= 0:
        chain.append(candidates[index])
        index = parents[index]
    # Adjacent sliding windows corroborate a phrase; isolated hits can occur
    # by chance in acknowledgements, headers, or unrelated spoken material.
    chain.reverse()
    end_i = end_j = 0
    for n, (i, j) in enumerate(chain):
        if len(chain) > 1 and not any(
            abs(i - k) <= 200 and abs(j - l) <= 300
            for k, l in chain[max(0, n - 1):n] + chain[n + 1:n + 2]
        ):
            continue
        if i >= end_i and j >= end_j:
            yield i, j, width
            end_i, end_j = i + width, j + width


def matching_tokens(book, speech, check=lambda: None):
    """Yield only equal tokens; large unsupported gaps remain unaligned."""
    from itertools import chain

    bi = si = 0
    for i, j, length in chain(monotone_seeds(book, speech, check),
                              [(len(book), len(speech), 0)]):
        check()
        if i > bi and j > si and (i - bi) * (j - si) <= 350_000:
            before = bi > 0 and si > 0
            after = length > 0
            matcher = SequenceMatcher(None, book[bi:i], speech[si:j], autojunk=False)
            for block in matcher.get_matching_blocks():
                tightly_bounded = before and after and max(i - bi, j - si) <= 24
                if block.size >= (1 if tightly_bounded else 4):
                    for k in range(block.size):
                        yield bi + block.a + k, si + block.b + k
        for k in range(length):
            yield i + k, j + k
        bi, si = i + length, j + length


def align_words(book_words, speech_words, normalize, check=lambda: None, constraint=None):
    book, speech = [], []
    book_spans, speech_spans, speech_indices = [], [], []
    for i, word in enumerate(book_words):
        if i % 4096 == 0:
            check()
        start = len(book)
        book.extend(normalize(word['text']).split())
        book_spans.append((start, len(book)))
    for i, word in enumerate(speech_words):
        tokens = word['normalized'].split()
        start = len(speech)
        speech.extend(tokens)
        speech_indices.extend([i] * len(tokens))
        speech_spans.append((start, len(speech)))

    if constraint is None:
        links = dict(matching_tokens(book, speech, check))
    else:
        wi, ai = constraint
        b0, b1 = book_spans[wi]
        s0, s1 = speech_spans[ai]
        links = dict(matching_tokens(book[:b0], speech[:s0], check))
        links.update((b1 + i, s1 + j) for i, j in matching_tokens(book[b1:], speech[s1:], check))

    matches = {}
    for i, (start, end) in enumerate(book_spans):
        if i % 4096 == 0:
            check()
        if constraint is not None and i == constraint[0]:
            matches[i] = (constraint[1], constraint[1])
            continue
        first = links.get(start)
        if end > start and first is not None and all(
            links.get(token) == first + token - start for token in range(start + 1, end)
        ):
            matches[i] = (speech_indices[first], speech_indices[first + end - start - 1])
    return matches
