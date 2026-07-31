"""Tests for Wikipedia episode-list / year / QID extraction (mocked API)."""

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
