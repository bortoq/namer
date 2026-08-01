"""Tests for Wikipedia episode-list / year / QID extraction (mocked API)."""

import json

import pytest

import namer.wikipedia as wiki


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Keep the disk caches out of the real user cache."""
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))


@pytest.fixture()
def fake_wiki(monkeypatch):
    """Serve canned pages for _search_page / _get_wikitext."""
    pages = {}

    def set_page(title, text=''):
        pages[title] = text

    def fake_search(title, language='en'):
        return title if title in pages else None

    def fake_wikitext(title, language='en'):
        return pages.get(title, '')

    monkeypatch.setattr(wiki, '_search_page', fake_search)
    monkeypatch.setattr(wiki, '_get_wikitext', fake_wikitext)
    return set_page


S1 = """{{Infobox television season}}
== Episodes ==
{{Episode list/sublist
| EpisodeNumber = 1
| Title = Mount Fuji and Curry Noodles
}}
{{Episode list/sublist
| EpisodeNumber = 2
| Title = Welcome to the Outdoor Activities Club!
}}
"""


def test_fetch_episode_titles_multiple_seasons(fake_wiki):
    fake_wiki('List of Show episodes', '{{:Show season 1}}\n{{:Show season 2}}')
    fake_wiki('Show season 1', S1)
    fake_wiki('Show season 2', """{{Episode list/sublist
| EpisodeNumber = 13
| EpisodeNumber2 = 1
| Title = A New Start
}}
""")
    result = wiki.fetch_episode_titles('Show')
    assert result[(1, 1)] == 'Mount Fuji and Curry Noodles'
    assert result[(1, 2)] == 'Welcome to the Outdoor Activities Club!'
    assert result[(2, 1)] == 'A New Start'  # EpisodeNumber2 preferred


def test_special_heading_maps_to_season_0(fake_wiki):
    fake_wiki('List of Show episodes', '{{:Show season 1}}')
    fake_wiki('Show season 1', """== OVA ==
{{Episode list/sublist
| EpisodeNumber = 1
| Title = The Outclub's Room
}}
""")
    result = wiki.fetch_episode_titles('Show')
    assert result[(0, 1)] == "The Outclub's Room"


def test_episode_title_cleaning(fake_wiki):
    """Refs, links, quotes and templates are stripped from titles."""
    fake_wiki('List of Show episodes', '{{:Show season 1}}')
    fake_wiki('Show season 1', """{{Episode list/sublist
| EpisodeNumber = 1
| Title = [[Link|Display Name]] ''italics''<ref>note</ref>
}}
{{Episode list/sublist
| EpisodeNumber = 2
| Title = Plain &amp; Clean
}}
""")
    result = wiki.fetch_episode_titles('Show')
    assert result[(1, 1)] == 'Display Name italics'
    assert result[(1, 2)] == 'Plain & Clean'


def test_no_list_page_returns_empty(fake_wiki):
    assert wiki.fetch_episode_titles('No Such Show') == {}


def test_fetch_show_year_earliest_across_pages(fake_wiki):
    """Season-1 page year wins over the franchise page year."""
    fake_wiki('Show season 1', '| first_aired = {{Start date|2018|01|04}}')
    fake_wiki('Show', '| first_aired = {{Start date|2020|01|10}}')
    assert wiki.fetch_show_year('Show') == 2018


def test_fetch_show_year_none(fake_wiki):
    assert wiki.fetch_show_year('No Such Show') is None


def test_get_entity_qid(fake_wiki, monkeypatch):
    fake_wiki('Yuru Camp', 'page text')
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, lang: 'Q28691353')
    assert wiki.get_entity_qid('Yuru Camp') == 'Q28691353'


def test_get_entity_qid_cached(fake_wiki, monkeypatch):
    calls = []
    fake_wiki('Yuru Camp', 'page text')
    monkeypatch.setattr(wiki, '_get_wikidata_id',
                        lambda page, lang: calls.append(page) or 'Q42')
    assert wiki.get_entity_qid('Yuru Camp') == 'Q42'
    assert wiki.get_entity_qid('Yuru Camp') == 'Q42'
    assert len(calls) == 1  # second call served from cache


# ── Translation (get_translated_title / enrich_title_via_wiki) ────────────────

# Media-type helpers mirroring the resolver's Wikidata P31 sets
FILM = {'Q11424'}
SERIES = {'Q5398426'}
ANIME = {'Q21198342'}
CONCEPT = {'Q1924249'}
DISAMBIG = {'Q4167410'}


def _types_mock(types_by_qid):
    return lambda qid, l=None: types_by_qid.get(qid, frozenset())


def _year_mock(years_by_qid):
    return lambda qid, l=None: years_by_qid.get(qid)


def test_get_translated_title_skips_first_result_without_langlink(monkeypatch):
    """Тьма: the first search hit is a generic page (no media type); the series
    page (2nd hit) carries the interlanguage link, so its title wins."""
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Тьма', 'Тьма (телесериал)'])
    monkeypatch.setattr(wiki, '_get_langlink',
                        lambda page, f, t: 'Dark (TV series)' if 'телесериал' in page else None)
    qids = {'Тьма': 'Q204170', 'Тьма (телесериал)': 'Q28443710'}
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: qids.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q204170': CONCEPT, 'Q28443710': SERIES}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q28443710': 2017}))
    assert wiki.get_translated_title('Тьма', 'en', is_series=True) == 'Dark (TV series)'


def test_get_translated_title_label_fallback_prefers_media_entity(monkeypatch):
    """No langlink anywhere: the concept page is rejected by its non-media
    type, the series page's label is used instead."""
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Тьма', 'Тьма (телесериал)'])
    monkeypatch.setattr(wiki, '_get_langlink', lambda *a: None)
    qids = {'Тьма': 'Q1', 'Тьма (телесериал)': 'Q2'}
    labels = {'Q1': 'darkness', 'Q2': 'Dark'}
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: qids.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: labels.get(qid))
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q1': CONCEPT, 'Q2': SERIES}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q2': 2017}))
    assert wiki.get_translated_title('Тьма', 'en', is_series=True) == 'Dark'


def test_get_translated_title_latin_concept_page_not_translated(monkeypatch):
    """'Dark' → first en.wiki hit 'Darkness' is a concept (not a media work) →
    the already-English title is kept unchanged (no 'darkness')."""
    monkeypatch.setattr(wiki, '_search_pages', lambda t, l: ['Darkness'])
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: 'Q204170')
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: 'darkness')
    monkeypatch.setattr(wiki, '_get_wikidata_types', _types_mock({'Q204170': CONCEPT}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({}))
    assert wiki.get_translated_title('Dark', 'en') == 'Dark'


def test_get_translated_title_latin_redirect_translated(monkeypatch):
    """'Yuru Camp' → en.wiki resolves to 'Laid-Back Camp' (anime type) → translated."""
    monkeypatch.setattr(wiki, '_search_pages', lambda t, l: ['Laid-Back Camp'])
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: 'Q28691353')
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: 'Laid-Back Camp')
    monkeypatch.setattr(wiki, '_get_wikidata_types', _types_mock({'Q28691353': ANIME}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q28691353': 2015}))
    assert wiki.get_translated_title('Yuru Camp', 'en') == 'Laid-Back Camp'


def test_get_translated_title_disambiguation_not_resolved_without_year_match(monkeypatch):
    """B9-001: 'Она' → the only media hit is a 2006 film while the file is from
    2013 → no translation (the original title is kept, like parent commit did)."""
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Она', 'Она — мужчина'])
    monkeypatch.setattr(wiki, '_get_langlink',
                        lambda page, f, t: "She's the Man" if 'мужчина' in page else None)
    monkeypatch.setattr(wiki, '_get_wikidata_id',
                        lambda page, l: {'Она': 'Q20433871',
                                         'Она — мужчина': 'Q72925'}.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q20433871': DISAMBIG, 'Q72925': FILM}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q72925': 2006}))
    assert wiki.get_translated_title('Она', 'en', year=2013) == 'Она'


def test_get_translated_title_disambiguation_resolved_when_year_and_type_match(monkeypatch):
    """B9-001: with the file year matching the film, the homonym is resolved."""
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Она', 'Она — мужчина'])
    monkeypatch.setattr(wiki, '_get_langlink',
                        lambda page, f, t: "She's the Man" if 'мужчина' in page else None)
    monkeypatch.setattr(wiki, '_get_wikidata_id',
                        lambda page, l: {'Она': 'Q20433871',
                                         'Она — мужчина': 'Q72925'}.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q20433871': DISAMBIG, 'Q72925': FILM}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q72925': 2006}))
    assert wiki.get_translated_title('Она', 'en', year=2006) == "She's the Man"


def test_get_translated_title_lowercase_media_label_accepted(monkeypatch):
    """B9-002: a lowercase localized label of a media work is valid —
    'Mother!' → it must yield 'madre!', not the untranslated 'Mother!'."""
    monkeypatch.setattr(wiki, '_search_pages', lambda t, l: ['Mother!'])
    monkeypatch.setattr(wiki, '_get_langlink', lambda *a: None)
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: 'Q25339558')
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: 'madre!')
    monkeypatch.setattr(wiki, '_get_wikidata_types', _types_mock({'Q25339558': FILM}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q25339558': 2017}))
    assert wiki.get_translated_title('Mother!', 'it') == 'madre!'


def test_get_translated_title_lowercase_media_label_accepted_ru_path(monkeypatch):
    """B9-002 (ru path): label fallback keeps lowercase media labels too."""
    monkeypatch.setattr(wiki, '_search_pages', lambda t, l: ['Мама!'])
    monkeypatch.setattr(wiki, '_get_langlink', lambda *a: None)
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: 'Q25339558')
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: 'madre!')
    monkeypatch.setattr(wiki, '_get_wikidata_types', _types_mock({'Q25339558': FILM}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q25339558': 2017}))
    assert wiki.get_translated_title('Мама!', 'it') == 'madre!'


def test_get_translated_title_cache_respects_is_series_context(tmp_path, monkeypatch):
    """81-003: a series translation must not pollute a later movie lookup
    for the same localized title (cache key includes context)."""
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Тьма', 'Тьма (телесериал)'])
    monkeypatch.setattr(wiki, '_get_langlink',
                        lambda page, f, t: 'Dark (TV series)' if 'телесериал' in page else None)
    qids = {'Тьма': 'Q204170', 'Тьма (телесериал)': 'Q28443710'}
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: qids.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q204170': CONCEPT, 'Q28443710': SERIES}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q28443710': 2017}))
    assert wiki.get_translated_title('Тьма', 'en', source_lang='ru',
                                     is_series=True) == 'Dark (TV series)'
    # Same title, movie context → must NOT reuse the series translation.
    assert wiki.get_translated_title('Тьма', 'en', source_lang='ru',
                                     is_series=False) == 'Тьма'


def test_get_translated_title_cache_respects_year_context(tmp_path, monkeypatch):
    """81-003: year is part of the cache key — different year must not reuse."""
    monkeypatch.setattr(wiki, '_search_pages', lambda t, l: ['Она', 'Она — мужчина'])
    monkeypatch.setattr(wiki, '_get_langlink',
                        lambda page, f, t: "She's the Man" if 'мужчина' in page else None)
    monkeypatch.setattr(wiki, '_get_wikidata_id',
                        lambda page, l: {'Она': 'Q20433871',
                                         'Она — мужчина': 'Q72925'}.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q20433871': DISAMBIG, 'Q72925': FILM}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q72925': 2006}))
    # year 2006 resolves; year 2013 must not reuse the 2006 result from cache
    assert wiki.get_translated_title('Она', 'en', year=2006) == "She's the Man"
    assert wiki.get_translated_title('Она', 'en', year=2013) == 'Она'


def test_get_translated_title_latin_concept_first_media_second(monkeypatch):
    """81-005: first en.wiki hit is a concept, the media entity is the second
    hit — with year/is_series context the second hit must win."""
    monkeypatch.setattr(wiki, '_search_pages', lambda t, l: ['Mother', 'Mother!'])
    monkeypatch.setattr(wiki, '_get_langlink', lambda *a: None)
    monkeypatch.setattr(wiki, '_get_wikidata_id',
                        lambda page, l: {'Mother': 'Q171318', 'Mother!': 'Q25339558'}.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label',
                        lambda qid, l: 'madre!' if qid == 'Q25339558' else None)
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q171318': {'Q171318'}, 'Q25339558': FILM}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q25339558': 2017}))
    assert wiki.get_translated_title('Mother!', 'it', is_series=False,
                                     year=2017) == 'madre!'


def test_get_translated_title_source_equals_target(monkeypatch):
    """ru → ru is a no-op (no network calls made)."""
    assert wiki.get_translated_title('Тьма', 'ru') == 'Тьма'


def test_get_translated_title_empty(monkeypatch):
    assert wiki.get_translated_title('') == ''


def test_enrich_title_via_wiki_cleans_tv_series_suffix(monkeypatch):
    """'Dark (TV series)' is cleaned to 'Dark' by enrich_title_via_wiki."""
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Тьма', 'Тьма (телесериал)'])
    monkeypatch.setattr(wiki, '_get_langlink',
                        lambda page, f, t: 'Dark (TV series)' if 'телесериал' in page else None)
    qids = {'Тьма': 'Q204170', 'Тьма (телесериал)': 'Q28443710'}
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: qids.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q204170': CONCEPT, 'Q28443710': SERIES}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q28443710': 2017}))
    meta = {'title': 'Тьма', 'is_series': True}
    assert wiki.enrich_title_via_wiki(meta, 'en') is True
    assert meta['title'] == 'Dark'


def test_get_translated_title_ignores_stale_unversioned_cache(tmp_path, monkeypatch):
    """Entries written by the old resolver (unversioned key) are not reused."""
    cache_dir = tmp_path / 'namer'
    cache_dir.mkdir()
    (cache_dir / 'wikipedia.json').write_text(
        json.dumps({'Тьма:ru:en': 'Tma'}), encoding='utf-8')
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Тьма', 'Тьма (телесериал)'])
    monkeypatch.setattr(wiki, '_get_langlink',
                        lambda page, f, t: 'Dark (TV series)' if 'телесериал' in page else None)
    qids = {'Тьма': 'Q204170', 'Тьма (телесериал)': 'Q28443710'}
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: qids.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_types',
                        _types_mock({'Q204170': CONCEPT, 'Q28443710': SERIES}))
    monkeypatch.setattr(wiki, '_get_wikidata_year', _year_mock({'Q28443710': 2017}))
    assert wiki.get_translated_title('Тьма', 'en', is_series=True) == 'Dark (TV series)'


def test_episode_title_unwraps_lang_template(fake_wiki):
    """B9-003: {{lang|la|Sic Mundus Creatus Est}} is unwrapped to its content
    instead of being emitted as raw template text."""
    fake_wiki('List of Dark episodes', """{{Infobox television season}}
== Episodes ==
{{Episode list/sublist
| EpisodeNumber = 1
| Title = {{lang|la|Sic Mundus Creatus Est}}
}}
""")
    result = wiki.fetch_episode_titles('Dark')
    assert result[(1, 1)] == 'Sic Mundus Creatus Est'


def test_inline_multi_season_headings(fake_wiki):
    """A single page holding '== Season N ==' sections maps blocks to seasons."""
    fake_wiki('List of Show episodes', """== Season 1 (2017) ==
{{Episode list/sublist
| EpisodeNumber = 1
| Title = Secrets
}}
{{Episode list/sublist
| EpisodeNumber = 2
| Title = Lies
}}
== Season 2 (2019) ==
{{Episode list/sublist
| EpisodeNumber = 1
| Title = Beginnings and Endings
}}
== Season 3 (2020) ==
{{Episode list/sublist
| EpisodeNumber = 1
| Title = Deja-vu
}}
""")
    result = wiki.fetch_episode_titles('Show')
    assert result[(1, 1)] == 'Secrets'
    assert result[(1, 2)] == 'Lies'
    assert result[(2, 1)] == 'Beginnings and Endings'
    assert result[(3, 1)] == 'Deja-vu'
    assert (3, 1) in result  # last season must not overwrite (1, 1)
    assert result[(1, 1)] == 'Secrets'
