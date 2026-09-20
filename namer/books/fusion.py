"""Fuse provider opinions -> canonical BookRecord. Pure, never raises."""
from __future__ import annotations

import re
import unicodedata


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


def fuse_opinions(opinions: list):
    """Winner-take-all with agreement gate. None on miss/conflict. Never raises."""
    try:
        ops = [o for o in (opinions or []) if o is not None and o.record is not None]
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
