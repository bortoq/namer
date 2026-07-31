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

def test_get_translated_title_skips_first_result_without_langlink(monkeypatch):
    """Тьма: the first search hit is a generic page (no langlink); the series
    page (2nd hit) carries the interlanguage link, so its title wins."""
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Тьма', 'Тьма (телесериал)'])
    monkeypatch.setattr(wiki, '_get_langlink',
                        lambda page, f, t: 'Dark (TV series)' if 'телесериал' in page else None)
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    assert wiki.get_translated_title('Тьма', 'en') == 'Dark (TV series)'


def test_get_translated_title_label_fallback_skips_lowercase_concept(monkeypatch):
    """No langlink anywhere: a lowercase concept label ('darkness') is rejected
    in favour of a later result's real title."""
    monkeypatch.setattr(wiki, '_search_pages',
                        lambda t, l: ['Тьма', 'Тьма (телесериал)'])
    monkeypatch.setattr(wiki, '_get_langlink', lambda *a: None)
    qids = {'Тьма': 'Q1', 'Тьма (телесериал)': 'Q2'}
    labels = {'Q1': 'darkness', 'Q2': 'Dark'}
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: qids.get(page))
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: labels.get(qid))
    assert wiki.get_translated_title('Тьма', 'en') == 'Dark'


def test_get_translated_title_latin_concept_page_not_translated(monkeypatch):
    """'Dark' → first en.wiki hit 'Darkness' has a lowercase concept label →
    the already-English title is kept unchanged (no 'darkness')."""
    monkeypatch.setattr(wiki, '_search_page', lambda t, l: 'Darkness')
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: 'Q204170')
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: 'darkness')
    assert wiki.get_translated_title('Dark', 'en') == 'Dark'


def test_get_translated_title_latin_redirect_translated(monkeypatch):
    """'Yuru Camp' → en.wiki resolves to 'Laid-Back Camp' (title-case) → translated."""
    monkeypatch.setattr(wiki, '_search_page', lambda t, l: 'Laid-Back Camp')
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: 'Q28278726')
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: 'Laid-Back Camp')
    assert wiki.get_translated_title('Yuru Camp', 'en') == 'Laid-Back Camp'


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
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    meta = {'title': 'Тьма'}
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
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, l: None)
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, l: None)
    assert wiki.get_translated_title('Тьма', 'en') == 'Dark (TV series)'


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
