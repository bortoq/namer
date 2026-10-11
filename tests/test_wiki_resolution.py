"""Film identity, unchanged confirmations, request pacing and retry regressions."""

import io
import json
import urllib.error

import pytest

from namer import wikipedia as wiki


@pytest.fixture
def catalog(monkeypatch):
    records = {}
    queries = []
    monkeypatch.setattr(wiki, '_search_pages', lambda query, language:
                        queries.append((query, language)) or list(records))
    monkeypatch.setattr(wiki, '_get_wikidata_id', lambda page, language: page)
    monkeypatch.setattr(wiki, '_get_wikidata_types', lambda qid: records[qid][0])
    monkeypatch.setattr(wiki, '_get_wikidata_year', lambda qid: records[qid][1])
    monkeypatch.setattr(wiki, '_get_langlink', lambda page, source, target: None)
    monkeypatch.setattr(wiki, '_get_wikidata_label', lambda qid, language: None)
    monkeypatch.setattr(wiki, '_get_wikidata_parents', lambda qid: [])
    monkeypatch.setattr(wiki, '_get_wikidata_aliases', lambda qid, language: [])
    monkeypatch.setattr(wiki, '_get_wikidata_release_years', lambda qid: [])
    return records, queries


def test_movie_context_skips_series_and_concepts(catalog):
    records, queries = catalog
    records.update({'Scream': ({'Q1924249'}, None),
                    'Scream (TV series)': ({'Q5398426'}, 2015),
                    'Scream (1996 film)': ({'Q11424'}, 1996)})
    result = wiki.resolve_wiki_title('Scream', 'en', False, 1996)
    assert result['title'] == 'Scream'
    assert result['page'] == 'Scream (1996 film)'
    assert result['year'] == 1996
    assert queries[0] == ('Scream 1996 film', 'en')


def test_unchanged_title_is_confirmed(catalog):
    records, queries = catalog
    records['Baskin (film)'] = ({'Q11424'}, 2015)
    meta = {'title': 'Baskin', 'year': 2015, 'is_series': False}
    assert wiki.enrich_title_via_wiki(meta)
    assert meta['title'] == 'Baskin'
    assert meta['_wiki_resolution']['qid'] == 'Baskin (film)'


def test_remake_selected_by_year(catalog):
    records, queries = catalog
    records.update({'Funny Games (1997 film)': ({'Q11424'}, 1997),
                    'Funny Games (2007 film)': ({'Q11424'}, 2007)})
    assert wiki.resolve_wiki_title('Funny Games', 'en', False, 1997)['year'] == 1997
    assert wiki.resolve_wiki_title('Funny Games', 'en', False, 2007)['year'] == 2007


def test_wrong_year_and_type_never_confirm(catalog):
    records, queries = catalog
    records.update({'Martin (TV series)': ({'Q5398426'}, 1992),
                    'Martin (film)': ({'Q11424'}, 2010)})
    assert wiki.resolve_wiki_title('Martin', 'en', False, 1977) is None


def test_same_year_unrelated_film_is_rejected(catalog):
    records, queries = catalog
    records['Totally Different (film)'] = ({'Q11424'}, 2015)
    assert wiki.resolve_wiki_title('Baskin', 'en', False, 2015) is None


def test_ambiguous_same_year_entities_are_rejected(catalog):
    records, queries = catalog
    records.update({'The Host (film)': ({'Q11424'}, 2006),
                    'The Host (2006 film)': ({'Q11424'}, 2006)})
    assert wiki.resolve_wiki_title('The Host', 'en', False, 2006) is None


def test_positive_resolution_cache_keeps_context(catalog):
    records, queries = catalog
    records['Scream (film)'] = ({'Q11424'}, 1996)
    assert wiki.resolve_wiki_title('Scream', 'en', False, 1996)
    count = len(queries)
    assert wiki.resolve_wiki_title('Scream', 'en', False, 1996)
    assert len(queries) == count
    assert wiki.resolve_wiki_title('Scream', 'en', True, 1996) is None


def test_negative_resolution_not_cached(catalog):
    records, queries = catalog
    assert wiki.resolve_wiki_title('Baskin', 'en', False, 2015) is None
    records['Baskin (film)'] = ({'Q11424'}, 2015)
    assert wiki.resolve_wiki_title('Baskin', 'en', False, 2015)


def test_old_series_year_cache_does_not_affect_movie(catalog, tmp_path):
    records, queries = catalog
    cache = tmp_path / 'cache' / 'namer'
    cache.mkdir(parents=True)
    (cache / 'wikipedia_episodes.json').write_text(json.dumps({'year:scream:en': 2015}))
    records['Scream (1996 film)'] = ({'Q11424'}, 1996)
    assert wiki.resolve_wiki_title('Scream', 'en', False, 1996)['year'] == 1996


@pytest.mark.parametrize('page', [
    'Under the Skin (2013 film)', 'Under the Skin (film)',
    'Under the Skin (film, 2013)',
])
def test_disambiguation_year_before_film(page):
    assert wiki._strip_disambiguation(page) == 'Under the Skin'


@pytest.fixture
def http(monkeypatch):
    monkeypatch.setattr(wiki, '_HTTP_CACHE', {})
    monkeypatch.setattr(wiki, '_HTTP_INFLIGHT', {})
    monkeypatch.setattr(wiki, '_HTTP_NEXT', {})
    monkeypatch.setattr(wiki, '_HTTP_INTERVAL', 0)
    wiki._HTTP_STATE.errors = []
    return 'https://en.wikipedia.org/w/api.php?test=1'


def test_http_429_retry_and_success_cache(http, monkeypatch):
    calls = []

    def fetch(request, **kwargs):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(http, 429, 'Too Many Requests',
                                         {'Retry-After': '0'}, None)
        return io.BytesIO(b'{"query": {}}')

    monkeypatch.setattr(wiki.urllib.request, 'urlopen', fetch)
    assert wiki._request_json(http) == {'query': {}}
    assert wiki._request_json(http) == {'query': {}}
    assert len(calls) == 2
    assert wiki._request_errors() == []


def test_failed_http_request_is_not_cached(http, monkeypatch):
    calls = []

    def fetch(request, **kwargs):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise OSError('network unavailable')
        return io.BytesIO(b'{"query": {}}')

    monkeypatch.setattr(wiki.urllib.request, 'urlopen', fetch)
    assert wiki._request_json(http) is None
    assert 'network unavailable' in wiki._request_errors()[0]
    assert wiki._request_json(http) == {'query': {}}
    assert len(calls) == 2


def test_request_pacing_shared_between_urls(http, monkeypatch):
    clock = [0.0]
    waits = []
    monkeypatch.setattr(wiki, '_HTTP_INTERVAL', 1)
    monkeypatch.setattr(wiki.time, 'monotonic', lambda: clock[0])

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(wiki.time, 'sleep', sleep)
    monkeypatch.setattr(wiki.urllib.request, 'urlopen',
                        lambda *args, **kwargs: io.BytesIO(b'{"query": {}}'))
    wiki._request_json(http)
    wiki._request_json(http + '&other=1')
    assert sum(waits) == 1


def test_core_uses_confirmed_unchanged_title_without_x(catalog):
    from namer.core import generate_new_name
    records, queries = catalog
    records['Baskin (film)'] = ({'Q11424'}, 2015)
    name, meta = generate_new_name('Baskin.2015.1080p.mkv')
    assert name == 'Baskin (2015).mkv'
    assert meta['_skip'] is False
    assert len(queries) == 1


def test_core_keeps_explicit_title_after_confirmation(catalog):
    from namer.core import generate_new_name
    records, queries = catalog
    records['Dracula (1958 film)'] = ({'Q11424'}, 1958)
    name, meta = generate_new_name('Movie.1958.mkv', known_title='Horror of Dracula')
    assert name == 'Horror of Dracula (1958).mkv'
    assert meta['_title_source'] == 'known'


def test_core_reads_release_year_from_directory(catalog):
    from namer.core import generate_new_name
    records, queries = catalog
    records['The Bride of Frankenstein'] = ({'Q11424'}, 1935)
    name, meta = generate_new_name(
        '/media/movies/The Bride of Frankenstein 1935 1080p/'
        'The Bride of Frankenstein.mp4')
    assert name == 'The Bride of Frankenstein (1935).mp4'
    assert queries[0] == ('The Bride of Frankenstein 1935 film', 'en')


def test_core_skips_direct_encoder_path_without_lookup(catalog):
    from namer.core import generate_new_name
    records, queries = catalog
    original = '.tmp.ab-av1-encoding.Black Swan (2010)_tmp_encode.mkv'
    name, meta = generate_new_name(original)
    assert name == original
    assert meta['_skip'] is True
    assert queries == []


def test_wikidata_id_follows_redirect(monkeypatch):
    calls = []

    def api(language, params):
        calls.append(params.copy())
        if not params.get('redirects'):
            return {'query': {'pages': {'1': {'redirect': '', 'title': 'Alias'}}}}
        return {'query': {'pages': {'2': {'pageprops': {'wikibase_item': 'Q42'}}}}}

    monkeypatch.setattr(wiki, '_wiki_api', api)
    assert wiki._get_wikidata_id('Alias', 'en') == 'Q42'
    assert len(calls) == 2
    assert calls[1]['redirects'] == 1


def test_exact_year_alias_beats_adjacent_year_title(catalog):
    records, queries = catalog
    records.update({'The Hills Have Eyes (2006 film)': ({'Q11424'}, 2006),
                    'The Hills Have Eyes 2 (2007 film)': ({'Q11424'}, 2007)})
    result = wiki.resolve_wiki_title('The Hills Have Eyes', 'en', False, 2007)
    assert result['title'] == 'The Hills Have Eyes 2'
    assert result['year'] == 2007


def test_dracula_alias_never_selects_return_of_dracula(catalog):
    records, queries = catalog
    records.update({'The Return of Dracula (1958 film)': ({'Q11424'}, 1958),
                    'Dracula (1958 film)': ({'Q11424'}, 1958)})
    result = wiki.resolve_wiki_title('Horror of Dracula', 'en', False, 1958)
    assert result['page'] == 'Dracula (1958 film)'


def test_weak_common_word_cannot_confirm_title(catalog):
    records, queries = catalog
    records['The Return of Dracula (1958 film)'] = ({'Q11424'}, 1958)
    assert wiki.resolve_wiki_title('Horror of Dracula', 'en', False, 1958) is None


def test_exact_title_preferred_among_same_year_partial_matches(catalog):
    records, queries = catalog
    records.update({'His House': ({'Q11424'}, 2020),
                    'The Night House (2020 film)': ({'Q11424'}, 2020)})
    assert wiki.resolve_wiki_title('His House', 'en', False, 2020)['title'] == 'His House'


def test_movie_subtype_is_confirmed(catalog, monkeypatch):
    records, queries = catalog
    records['Earwig and the Witch'] = ({'Q506240'}, 2020)
    monkeypatch.setattr(wiki, '_get_wikidata_parents', lambda qid: ['Q11424'])
    assert wiki.resolve_wiki_title('Earwig and the Witch', 'en', False, 2020)


def test_any_documented_release_year_can_confirm(catalog, monkeypatch):
    records, queries = catalog
    records['Plan 9 from Outer Space'] = ({'Q11424'}, 1957)
    monkeypatch.setattr(wiki, '_get_wikidata_release_years', lambda qid: [1957, 1959])
    assert wiki.resolve_wiki_title('Plan 9 from Outer Space', 'en', False, 1959)['year'] == 1959


def test_verified_alternate_title(catalog, monkeypatch):
    records, queries = catalog
    records['High Tension'] = ({'Q11424'}, 2003)
    monkeypatch.setattr(wiki, '_get_wikidata_aliases', lambda qid, language: ['Haute Tension'])
    assert wiki.resolve_wiki_title('Haute Tension', 'en', False, 2003)['title'] == 'High Tension'


def test_language_qualified_disambiguation():
    assert wiki._strip_disambiguation('Dracula (1931 English-language film)') == 'Dracula'


def test_old_exact_title_does_not_hide_new_year_alias(catalog):
    records, queries = catalog
    records.update({'The Mummy (1999 film)': ({'Q11424'}, 1999),
                    "Lee Cronin's The Mummy": ({'Q11424'}, 2026)})
    result = wiki.resolve_wiki_title('The Mummy', 'en', False, 2026)
    assert result['title'] == "Lee Cronin's The Mummy"
