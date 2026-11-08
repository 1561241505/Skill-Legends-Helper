"""Small, dependency-free BM25 index over guide sections.

Chinese text is tokenized into character bigrams, which works well for game
jargon such as 大招流 / 易伤 / 护盾 without needing a dictionary.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .guides import Guide

TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+")


def tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    for run in TOKEN_RE.findall((text or "").lower()):
        if "\u4e00" <= run[0] <= "\u9fff":
            if len(run) == 1:
                tokens.append(run)
            else:
                tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        else:
            tokens.append(run)
    return tokens


@dataclass
class Chunk:
    guide_hero: str
    title: str
    section: str
    text: str
    source: str
    tokens: List[str]


def _split_long(text: str, limit: int = 560) -> List[str]:
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    current: List[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if size + len(para) > limit and current:
            parts.append("\n\n".join(current))
            current = [para]
            size = len(para)
        else:
            current.append(para)
            size += len(para)
    if current:
        parts.append("\n\n".join(current))
    return parts


class GuideIndex:
    def __init__(self, guides: Dict[str, Guide]) -> None:
        self.guides = guides
        self.chunks: List[Chunk] = []
        self.df: Dict[str, int] = {}
        self.avgdl = 1.0
        self._build()

    def _build(self) -> None:
        for guide in self.guides.values():
            for section, text in guide.sections:
                for part in _split_long(text):
                    tokens = tokenize(section + "\n" + part)
                    # the hero name and title are strong field signals
                    tokens += tokenize(guide.hero) * 2
                    tokens += tokenize(guide.title)
                    if not tokens:
                        continue
                    self.chunks.append(
                        Chunk(
                            guide_hero=guide.hero,
                            title=guide.title,
                            section=section,
                            text=part.strip(),
                            source=guide.source,
                            tokens=tokens,
                        )
                    )
        for chunk in self.chunks:
            for term in set(chunk.tokens):
                self.df[term] = self.df.get(term, 0) + 1
        self.avgdl = sum(len(c.tokens) for c in self.chunks) / float(max(1, len(self.chunks)))

    @property
    def n(self) -> int:
        return len(self.chunks)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, hero: Optional[str] = None, top_k: int = 4) -> List[Dict[str, Any]]:
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []
        qset = list(dict.fromkeys(terms))
        scored: List[Tuple[float, Chunk]] = []
        k1, b = 1.5, 0.75
        for chunk in self.chunks:
            if hero and chunk.guide_hero != hero:
                continue
            freq: Dict[str, int] = {}
            for token in chunk.tokens:
                freq[token] = freq.get(token, 0) + 1
            score = 0.0
            for term in qset:
                tf = freq.get(term, 0)
                if not tf:
                    continue
                denom = tf + k1 * (1 - b + b * len(chunk.tokens) / (self.avgdl or 1.0))
                score += self._idf(term) * (tf * (k1 + 1)) / denom
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, chunk in scored[:top_k]:
            results.append(
                {
                    "hero": chunk.guide_hero,
                    "title": chunk.title,
                    "section": chunk.section,
                    "text": chunk.text,
                    "source": chunk.source,
                    "score": round(float(score), 3),
                }
            )
        return results

    def search_any(self, query: str, hero: Optional[str] = None, top_k: int = 4) -> List[Dict[str, Any]]:
        results = self.search(query, hero=hero, top_k=top_k)
        if results or not hero:
            return results
        return self.search(query, hero=None, top_k=top_k)
