"""Keyword search (BM25) over the in-memory chunks, the second half of hybrid retrieval (retrieval.py).

Dense vectors find passages similar in meaning but can miss exact terms (names, "rate-rent", "bucket shop");
BM25 ranks passages by the query words they contain, weighted by how rare the words are. The index is built
from db.chunks on first use and rebuilt whenever the chunks change (ingestion swaps in a new dict).
"""

import math
import re
from collections import Counter

from app.core import state as db
from app.core.schemas import Chunk

K1, B = 1.5, 0.75  # the usual BM25 parameters: term frequency saturation and length normalisation

# Very common English words carry no meaning for the ranking.
STOPWORDS = frozenset(
    "a an and are as at be by does do for from has have how in is it its of on or that the this to was what when "
    "where which who why with according about book books say says said".split())


def tokens(text: str) -> list[str]:
    """Lower-case words of 2+ letters or digits, without stopwords."""
    return [w for w in re.findall(r"[a-z0-9]{2,}", text.lower()) if w not in STOPWORDS]


class _Index:
    """BM25 statistics of one chunk dict: term counts per chunk, document frequencies, average length."""

    def __init__(self, chunks: dict[str, Chunk]):
        self.chunks = chunks
        self.terms = {cid: Counter(tokens(c.text)) for cid, c in chunks.items()}
        self.lengths = {cid: sum(t.values()) for cid, t in self.terms.items()}
        self.avg_length = sum(self.lengths.values()) / max(1, len(self.lengths))
        self.df = Counter(term for t in self.terms.values() for term in t)

    def scores(self, query: str, chunk_ids) -> dict[str, float]:
        n = len(self.terms)
        idf = {t: math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5)) for t in set(tokens(query)) if self.df[t]}
        result = {}
        for cid in chunk_ids:
            tf, length = self.terms[cid], self.lengths[cid]
            score = sum(idf[t] * tf[t] * (K1 + 1) / (tf[t] + K1 * (1 - B + B * length / self.avg_length))
                        for t in idf if tf[t])
            if score > 0:
                result[cid] = score
        return result


_index: _Index | None = None


def search(project_id: str, query: str, n: int, source_ids: list[str] | None = None,
           where: dict | None = None) -> list[str]:
    """Ids of the n chunks with the highest BM25 score for the query, best first, within the project and filters
    (the same source_ids and Chroma-style where conditions as vectorstore.search)."""
    global _index
    if _index is None or _index.chunks is not db.chunks:
        _index = _Index(db.chunks)
    candidates = [cid for cid, c in _index.chunks.items()
                  if db.sources.get(c.source_id) and db.sources[c.source_id].project_id == project_id
                  and (not source_ids or c.source_id in source_ids) and matches(c, where)]
    scores = _index.scores(query, candidates)
    return sorted(scores, key=scores.get, reverse=True)[:n]


def matches(chunk: Chunk, where: dict | None) -> bool:
    """True if the chunk meets Chroma-style metadata conditions on chapter and page ($in, $gte, $lte, $and)."""
    if not where:
        return True
    if "$and" in where:
        return all(matches(chunk, c) for c in where["$and"])
    (field, condition), = where.items()
    value = getattr(chunk.location, field)
    if value is None:
        return False
    op, target = next(iter(condition.items()))
    return {"$in": lambda: value in target, "$gte": lambda: value >= target, "$lte": lambda: value <= target,
            "$eq": lambda: value == target}[op]()
