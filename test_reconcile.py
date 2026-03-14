"""
Tests for the reconciliation service.
Command: pytest test_reconcile.py -v
"""

import json
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
import pytest

from reconcile_service import (
    clean_text,
    sm_score,
    lev_dist,
    lev_score,
    jaro,
    jaro_winkler,
    guess_fields,
    load_csv,
    start_server,
    ALGOS,
)

TEST_CSV = "whc-sites-2025.csv"
TEST_PORT = 9876


def boot_server(port=TEST_PORT, algo='sequencematcher', preprocess=True):
    import socketserver
    from reconcile_service import Handler, load_csv, clean_text

    rows, cols = load_csv(TEST_CSV, 'unique_number', 'name_en')
    nc = 'name_en'
    if preprocess:
        norm_names = [clean_text(r.get(nc, '')) for r in rows]
    else:
        norm_names = [r.get(nc, '').lower().strip() for r in rows]

    Handler.rows = rows
    Handler.cols = cols
    Handler.dataset = TEST_CSV
    Handler.id_col = 'unique_number'
    Handler.name_col = nc
    Handler.algo_name = algo
    Handler.score_fn = ALGOS[algo]
    Handler.preprocess = preprocess
    Handler.filters = []
    Handler.norm_names = norm_names
    Handler.norm_filters = []
    Handler.log_message = lambda self, fmt, *args: None

    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    return srv


def get_json(url):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode('utf-8')), resp


class TestCleanText:
    def test_lowercases(self):
        assert clean_text("HELLO") == "hello"

    def test_strips_accents(self):
        assert clean_text("Galápagos") == "galapagos"

    def test_removes_punctuation(self):
        assert clean_text("K'gari (Fraser Island)") == "k gari fraser island"

    def test_collapses_spaces(self):
        assert clean_text("  too   many  spaces  ") == "too many spaces"

    def test_colon_gone(self):
        out = clean_text("Rio de Janeiro: Carioca Landscapes")
        assert ":" not in out
        assert "rio de janeiro" in out

    def test_em_dash(self):
        out = clean_text("Memphis – the Pyramid Fields")
        assert "memphis" in out
        assert "pyramid" in out

    def test_empty(self):
        assert clean_text("") == ""


class TestSmScore:
    def test_identical(self):
        assert sm_score("abc", "abc") == 1.0

    def test_no_overlap(self):
        assert sm_score("abc", "xyz") == 0.0

    def test_partial(self):
        s = sm_score("galapagos islands", "galapagos")
        assert 0.3 < s < 1.0


class TestLevenshtein:
    def test_same(self):
        assert lev_dist("abc", "abc") == 0
        assert lev_score("abc", "abc") == 1.0

    def test_one_edit(self):
        assert lev_dist("abc", "ab") == 1
        assert lev_dist("abc", "axc") == 1

    def test_empty(self):
        assert lev_dist("", "") == 0
        assert lev_dist("abc", "") == 3
        assert lev_score("", "") == 1.0

    def test_range(self):
        s = lev_score("galapagos", "galapegos")
        assert 0.0 <= s <= 1.0
        assert s > 0.8


class TestJaroWinkler:
    def test_identical(self):
        assert jaro("abc", "abc") == 1.0
        assert jaro_winkler("abc", "abc") == 1.0

    def test_no_match(self):
        assert jaro("abc", "xyz") == 0.0
        assert jaro_winkler("abc", "xyz") == 0.0

    def test_empty(self):
        assert jaro("", "") == 1.0
        assert jaro_winkler("", "") == 1.0

    def test_prefix_bonus(self):
        # jaro_winkler should score >= jaro when there's a shared prefix
        j = jaro("galapagos", "galapegos")
        jw = jaro_winkler("galapagos", "galapegos")
        assert jw >= j

    def test_in_range(self):
        s = jaro_winkler("great barrier reef", "great barier reef")
        assert 0.0 <= s <= 1.0
        assert s > 0.9


class TestCsvHandling:
    def test_guess_basic(self):
        id_c, name_c = guess_fields(['id', 'name_en', 'category'])
        assert id_c == 'id'
        assert name_c == 'name_en'

    def test_guess_no_same_field(self):
        id_c, name_c = guess_fields(['unique_id', 'title', 'description'])
        assert id_c != name_c

    def test_guess_fallback(self):
        # falls back to first two columns if nothing matches
        id_c, name_c = guess_fields(['col_a', 'col_b'])
        assert id_c == 'col_a'
        assert name_c == 'col_b'

    def test_loads_records(self):
        rows, cols = load_csv(TEST_CSV, 'unique_number', 'name_en')
        assert len(rows) > 0
        assert 'unique_number' in cols
        assert 'name_en' in cols

    def test_rows_have_required_keys(self):
        rows, _ = load_csv(TEST_CSV, 'unique_number', 'name_en')
        for r in rows:
            assert 'unique_number' in r
            assert 'name_en' in r

    def test_bad_field_raises(self):
        with pytest.raises(ValueError):
            load_csv(TEST_CSV, 'nonexistent_col', 'name_en')


class TestW3CCompliance:
    @pytest.fixture(autouse=True, scope='class')
    def server(self):
        srv = boot_server()
        yield
        srv.shutdown()

    def test_manifest_is_json(self):
        _, resp = get_json(f"http://localhost:{TEST_PORT}/")
        assert resp.headers.get('Content-Type').startswith('application/json')

    def test_manifest_has_name(self):
        data, _ = get_json(f"http://localhost:{TEST_PORT}/")
        assert 'name' in data and isinstance(data['name'], str)

    def test_manifest_identifier_space(self):
        data, _ = get_json(f"http://localhost:{TEST_PORT}/")
        assert 'identifierSpace' in data

    def test_manifest_schema_space(self):
        data, _ = get_json(f"http://localhost:{TEST_PORT}/")
        assert 'schemaSpace' in data

    def test_manifest_default_types(self):
        data, _ = get_json(f"http://localhost:{TEST_PORT}/")
        dt = data.get('defaultTypes', [])
        assert isinstance(dt, list) and len(dt) > 0
        assert 'id' in dt[0] and 'name' in dt[0]

    def test_manifest_view_url(self):
        data, _ = get_json(f"http://localhost:{TEST_PORT}/")
        assert '{{id}}' in data['view']['url']

    def test_cors_on_manifest(self):
        _, resp = get_json(f"http://localhost:{TEST_PORT}/")
        assert resp.headers.get('Access-Control-Allow-Origin') == '*'

    def test_query_returns_result(self):
        q = urllib.parse.quote("Galapagos Islands")
        data, _ = get_json(f"http://localhost:{TEST_PORT}/reconcile?query={q}")
        assert 'result' in data and isinstance(data['result'], list)

    def test_candidate_fields(self):
        q = urllib.parse.quote("Galapagos Islands")
        data, _ = get_json(f"http://localhost:{TEST_PORT}/reconcile?query={q}")
        for c in data['result']:
            assert 'id' in c
            assert 'name' in c
            assert isinstance(c['score'], (int, float))
            assert isinstance(c['match'], bool)
            assert isinstance(c['type'], list)

    def test_scores_sorted(self):
        q = urllib.parse.quote("Galapagos Islands")
        data, _ = get_json(f"http://localhost:{TEST_PORT}/reconcile?query={q}")
        scores = [c['score'] for c in data['result']]
        assert scores == sorted(scores, reverse=True)

    def test_batch_query(self):
        batch = {"q0": {"query": "Galapagos Islands"},
                 "q1": {"query": "Great Barrier Reef"}}
        enc = urllib.parse.quote(json.dumps(batch))
        data, _ = get_json(
            f"http://localhost:{TEST_PORT}/reconcile?queries={enc}")
        assert 'result' in data['q0'] and 'result' in data['q1']

    def test_cors_on_reconcile(self):
        q = urllib.parse.quote("test")
        _, resp = get_json(f"http://localhost:{TEST_PORT}/reconcile?query={q}")
        assert resp.headers.get('Access-Control-Allow-Origin') == '*'

    def test_limit_param(self):
        qobj = urllib.parse.quote(json.dumps({"query": "Islands", "limit": 2}))
        data, _ = get_json(
            f"http://localhost:{TEST_PORT}/reconcile?query={qobj}")
        assert len(data['result']) <= 2

    def test_missing_query_errors(self):
        try:
            data, _ = get_json(f"http://localhost:{TEST_PORT}/reconcile")
            assert data.get('code') == 'error'
        except urllib.error.HTTPError:
            pass


class TestMatchQuality:
    @pytest.fixture(autouse=True, scope='class')
    def server(self):
        srv = boot_server()
        yield
        srv.shutdown()

    def test_galapagos_top_score(self):
        q = urllib.parse.quote("Galapagos Islands")
        data, _ = get_json(f"http://localhost:{TEST_PORT}/reconcile?query={q}")
        top = data['result'][0]
        assert top['score'] > 0.8
        assert 'gal' in top['name'].lower()

    def test_accent_insensitive(self):
        q = urllib.parse.quote("Galapagos Islands")
        data, _ = get_json(f"http://localhost:{TEST_PORT}/reconcile?query={q}")
        names = [c['name'].lower() for c in data['result']]
        assert any('gal' in n for n in names)

    def test_great_barrier_reef(self):
        q = urllib.parse.quote("Great Barrier Reef")
        data, _ = get_json(f"http://localhost:{TEST_PORT}/reconcile?query={q}")
        top = data['result'][0]
        assert 'great barrier reef' in top['name'].lower()
        assert top['score'] > 0.9


# not a test, just useful for manual checking
def algo_compare(query, csv_path=TEST_CSV):
    rows, _ = load_csv(csv_path, 'unique_number', 'name_en')
    qt = clean_text(query)
    print(f"\nQuery: '{query}' -> '{qt}'")
    print("-" * 70)
    for name, fn in ALGOS.items():
        hits = []
        for r in rows:
            s = fn(qt, clean_text(r.get('name_en', '')))
            if s > 0:
                hits.append((s, r['name_en'], r['unique_number']))
        hits.sort(reverse=True)
        print(f"\n  {name}:")
        for s, n, rid in hits[:3]:
            print(f"    {s:.3f}  [{rid}] {n}")