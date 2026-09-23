"""Fuse provider opinions -> canonical BookRecord. Pure, never raises."""
from __future__ import annotations

import re
import unicodedata

from namer.books.models import BookQuery


def _norm_title(t: str) -> str:
    try:
        t = unicodedata.normalize('NFKD', t or '').lower()
        t = re.sub(r'[^a-zа-яё0-9]+', ' ', t)
        return re.sub(r'\s+', ' ', t).strip()
    except Exception:
        return ''


def _norm_author(a: str) -> str:
    try:
        a = unicodedata.normalize('NFKD', a or '').lower()
        a = re.sub(r'[^a-zа-яё0-9]+', ' ', a)
        return re.sub(r'\s+', ' ', a).strip()
    except Exception:
        return ''


def candidate_score(query: BookQuery, record) -> float:
    """Score a catalogue record against local hints, in [0, 1]."""
    try:
        if not isinstance(query, BookQuery) or record is None:
            return 0.0
        isbn_q = re.sub(r'[^0-9Xx]', '', query.isbn_hint or '')
        isbn_r = re.sub(r'[^0-9Xx]', '', record.isbn13 or '')
        if isbn_q and isbn_r and isbn_q == isbn_r:
            return 1.0
        title_q = _norm_title(query.title_hint)
        title_r = _norm_title(record.title)
        if not title_q or not title_r:
            return 0.0
        q_words, r_words = set(title_q.split()), set(title_r.split())
        overlap = len(q_words & r_words) / max(1, len(q_words | r_words))
        containment = 1.0 if title_q in title_r or title_r in title_q else 0.0
        score = max(overlap, containment * 0.9)
        if query.authors_hint and record.authors:
            q_auth = {_norm_author(a) for a in query.authors_hint if a}
            r_auth = {_norm_author(a) for a in record.authors if a}
            if q_auth & r_auth:
                score += 0.25
        if query.year_hint and record.year:
            score += 0.08 if query.year_hint == record.year else -0.08
        return max(0.0, min(0.99, score))
    except Exception:
        return 0.0


def rank_opinions(query: BookQuery, opinions: list) -> list:
    """Return provider opinions ranked by agreement with local hints."""
    ranked = []
    for opinion in opinions or []:
        try:
            score = candidate_score(query, opinion.record)
            if score >= 0.45 or (query.has_isbn() and score >= 0.9):
                ranked.append((score, opinion))
        except Exception:
            continue
    ranked.sort(key=lambda item: (item[0], float(item[1].confidence or 0.0)), reverse=True)
    return [opinion for _score, opinion in ranked]


def fuse_opinions(opinions: list, query: BookQuery = None):
    """Winner-take-all with agreement gate. None on miss/conflict. Never raises."""
    try:
        ops = [o for o in (opinions or []) if o is not None and o.record is not None]
        if query is not None and not query.is_empty():
            ranked = rank_opinions(query, ops)
            # A concrete local hint is a safety gate: a catalogue answer that
            # cannot substantively match it must not rename the media file.
            if not ranked:
                return None
            ops = ranked
        if not ops:
            return None
        # 1) ISBN agreement (strongest): any shared normalized ISBN-13
        by_isbn: dict = {}
        for o in ops:
            try:
                isbn = (o.record.isbn13 or '').strip()
                if isbn:
                    by_isbn.setdefault(isbn, []).append(o)
            except Exception:
                continue
        for isbn, group in by_isbn.items():
            if len(group) >= 2:
                best = max(group, key=lambda o: float(o.confidence or 0.0))
                rec = best.record
                return _with_conf(rec, min(0.99, float(best.confidence or 0.9) + 0.05))
            single = group[0]
            if float(single.confidence or 0.0) >= 0.9:
                return single.record
        # 2) title+author agreement
        buckets: dict = {}
        for o in ops:
            try:
                key = (_norm_title(o.record.title),
                       _norm_author(o.record.authors[0] if o.record.authors else ''))
                if not key[0]:
                    continue
                buckets.setdefault(key, []).append(o)
            except Exception:
                continue
        best_group: list = []
        for _key, group in buckets.items():
            if len(group) > len(best_group):
                best_group = group
        if len(best_group) >= 2:
            best = max(best_group, key=lambda o: float(o.confidence or 0.0))
            return _with_conf(best.record, min(0.95, float(best.confidence or 0.8) + 0.03))
        # 3) single strong opinion
        strong = [o for o in ops if float(o.confidence or 0.0) >= 0.85]
        if len(strong) == 1:
            only = strong[0]
            # single title-only without author/ISBN is a guess -> refuse
            try:
                if (not only.record.authors and not only.record.isbn13
                        and float(only.confidence or 0.0) < 0.9):
                    return None
            except Exception:
                return None
            return only.record
        return None
    except Exception:
        return None


def _with_conf(record, conf: float):
    try:
        from namer.books.models import BookRecord
        return BookRecord(
            title=record.title, authors=record.authors, series=record.series,
            series_index=record.series_index, year=record.year,
            language=record.language, isbn13=record.isbn13,
            publisher=record.publisher, provider=record.provider,
            provider_id=record.provider_id, confidence=float(conf))
    except Exception:
        return record
