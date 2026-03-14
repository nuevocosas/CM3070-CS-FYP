import csv
import io
import json
import argparse
import os
import re
import unicodedata
import http.server
import socketserver
from socketserver import ThreadingMixIn
import urllib.parse
from difflib import SequenceMatcher


# -------------------------------------------------------
# Text preprocessing
# -------------------------------------------------------

def clean_text(s):
    # strip accents via NFD decomposition
    nfkd = unicodedata.normalize('NFD', s)
    out = ''.join(c for c in nfkd if unicodedata.category(c) != 'Mn')
    out = out.lower()
    # keep only letters, digits, spaces
    out = re.sub(r'[^a-z0-9\s]', ' ', out)
    out = re.sub(r'\s+', ' ', out).strip()
    return out


# -------------------------------------------------------
# Similarity algorithms
# -------------------------------------------------------

def sm_score(a, b):
    return SequenceMatcher(None, a, b).ratio()


def lev_dist(a, b):
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
        return len(a)

    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        curr = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i-1] == b[j-1] else 1
            curr[j] = min(curr[j-1] + 1, prev[j] + 1, prev[j-1] + cost)
        prev = curr
    return prev[len(b)]


def lev_score(a, b):
    if not a and not b:
        return 1.0
    dist = lev_dist(a, b)
    return 1.0 - dist / max(len(a), len(b))


def jaro(a, b):
    la, lb = len(a), len(b)
    if la == 0 and lb == 0:
        return 1.0
    if la == 0 or lb == 0:
        return 0.0

    win = max(la, lb) // 2 - 1
    if win < 0:
        win = 0

    a_hit = [False] * la
    b_hit = [False] * lb
    matches = 0

    for i in range(la):
        lo = max(0, i - win)
        hi = min(i + win + 1, lb)
        for j in range(lo, hi):
            if b_hit[j] or a[i] != b[j]:
                continue
            a_hit[i] = True
            b_hit[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    trans = 0
    k = 0
    for i in range(la):
        if not a_hit[i]:
            continue
        while not b_hit[k]:
            k += 1
        if a[i] != b[k]:
            trans += 1
        k += 1

    return (matches/la + matches/lb + (matches - trans/2)/matches) / 3.0


def jaro_winkler(a, b, p=0.1):
    j = jaro(a, b)
    prefix = 0
    for i in range(min(len(a), len(b), 4)):
        if a[i] == b[i]:
            prefix += 1
        else:
            break
    return j + prefix * p * (1.0 - j)


ALGOS = {
    'sequencematcher': sm_score,
    'levenshtein': lev_score,
    'jarowinkler': jaro_winkler,
}


# -------------------------------------------------------
# CSV loading
# -------------------------------------------------------

def guess_fields(cols):
    id_hints = ['id', 'unique', 'identifier', 'key']
    name_hints = ['name', 'title', 'label', 'description']

    id_col = next((f for f in cols if any(
        k in f for k in id_hints)), cols[0] if cols else 'id')

    name_col = None
    for f in cols:
        if f != id_col and any(k in f for k in name_hints):
            name_col = f
            break
    if name_col is None:
        name_col = next((f for f in cols if f != id_col), id_col)

    return id_col, name_col


def load_csv(path, id_col, name_col):
    with open(path, newline='', encoding='utf-8-sig') as fh:
        lines = fh.readlines()

    # skip blank lines at the top
    while lines and not lines[0].strip():
        lines.pop(0)

    reader = csv.DictReader(io.StringIO(''.join(lines)))
    rows = []
    for row in reader:
        clean = {k.lower().strip(): v.strip()
                 for k, v in row.items() if k is not None}
        if clean:
            rows.append(clean)

    cols = [f for f in (reader.fieldnames or []) if f is not None]
    lower_cols = [c.lower().strip() for c in cols]

    if id_col.lower() not in lower_cols or name_col.lower() not in lower_cols:
        raise ValueError(
            f"CSV must contain '{id_col}' and '{name_col}' columns")

    return rows, lower_cols


# -------------------------------------------------------
# HTTP handler
# -------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    # these get set by start_server() before we bind
    rows = []
    cols = []
    dataset = ""
    id_col = "id"
    name_col = "name_en"
    algo_name = "sequencematcher"
    score_fn = sm_score
    filters = []          # list of {field, label, weight}
    norm_names = []       # pre-cleaned name strings
    norm_filters = []     # pre-cleaned values per filter column
    preprocess = True

    def _json(self, obj, status=200):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        path = p.path.rstrip('/')
        qs = urllib.parse.parse_qs(p.query)

        routes = {
            '': lambda: self._reconcile(qs) if ('query' in qs or 'queries' in qs) else self._manifest(),
            '/': lambda: self._reconcile(qs) if ('query' in qs or 'queries' in qs) else self._manifest(),
            '/reconcile': lambda: self._reconcile(qs) if ('query' in qs or 'queries' in qs) else self._json({"code": "error", "message": "Missing 'query' or 'queries' parameter"}, 400),
            '/detail': lambda: self._detail(qs),
            '/config':    self._config_get,
            '/ui': lambda: self._page('ui.html'),
            '/config-ui': lambda: self._page('config.html'),
            '/css/styles.css': lambda: self._static('css/styles.css', 'text/css'),
            '/css/uiStyles.css': lambda: self._static('css/uiStyles.css', 'text/css'),
            '/css/configStyles.css': lambda: self._static('css/configStyles.css', 'text/css'),
            '/js/ui.js': lambda: self._static('js/ui.js', 'application/javascript'),
            '/js/config.js': lambda: self._static('js/config.js', 'application/javascript'),
        }

        fn = routes.get(path)
        if fn:
            fn()
        else:
            self.send_error(404, f"Not found: {path}")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip('/')
        if path == '/config':
            self._config_post()
        elif path in ('', '/', '/reconcile'):
            # OpenRefine sends reconcile queries as POST with form data
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            qs = urllib.parse.parse_qs(body)
            if 'query' in qs or 'queries' in qs:
                self._reconcile(qs)
            else:
                self._json({"code": "error", "message": "Missing 'query' or 'queries' parameter"}, 400)
        else:
            self.send_error(404, f"Not found: {path}")

    def _manifest(self):
        data = {
            "name": f"Reconciliation service for {self.dataset}",
            "identifierSpace": "https://whc.unesco.org/id/",
            "schemaSpace": "https://whc.unesco.org/schema/",
            "view": {"url": "https://whc.unesco.org/en/list/{{id}}"},
            "defaultTypes": [{"id": "WorldHeritageSite", "name": "World Heritage Site"}],
        }
        if self.filters:
            data["properties"] = [
                {"id": f["field"], "name": f["label"]
                    or f["field"], "weight": f["weight"]}
                for f in self.filters
            ]
        self._json(data)

    def _reconcile(self, qs):
        if 'queries' in qs:
            try:
                batch = json.loads(qs['queries'][0])
            except Exception as e:
                self._json(
                    {"code": "error", "message": f"Bad JSON in queries: {e}"}, 400)
                return
            self._json({k: self._run_query(q) for k, q in batch.items()})

        elif 'query' in qs:
            raw = qs['query'][0]
            try:
                q = json.loads(raw) if raw.strip().startswith(
                    '{') else {"query": raw}
            except Exception as e:
                self._json(
                    {"code": "error", "message": f"Bad JSON in query: {e}"}, 400)
                return
            self._json(self._run_query(q))

        else:
            self._json(
                {"code": "error", "message": "Need 'query' or 'queries' param"}, 400)

    def _run_query(self, q):
        term = q.get('query', '')
        limit = int(q.get('limit', 3))

        # which filters does this query actually supply values for?
        active = []
        for i, f in enumerate(self.filters):
            val = q.get(f["field"], '').lower().strip()
            if val:
                active.append((i, val, f["weight"]))

        name_w = 1.0 - sum(w for _, _, w in active) if active else 1.0

        norm_term = clean_text(
            term) if self.preprocess else term.lower().strip()

        hits = []
        for idx, row in enumerate(self.rows):
            stored = self.norm_names[idx]
            nscore = Handler.score_fn(norm_term, stored)
            if nscore <= 0:
                continue

            if active:
                total = name_w * nscore
                for fi, qval, w in active:
                    total += w * (1.0 if qval ==
                                  self.norm_filters[fi][idx] else 0.0)
            else:
                total = nscore

            hits.append((total, row))

        hits.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, row in hits[:limit]:
            fv = row.get(self.filters[0]["field"], '') if self.filters else ''
            results.append({
                "id":           row.get(self.id_col, ''),
                "name":         row.get(self.name_col, ''),
                "score":        round(score, 3),
                "match":        score > 0.9,
                "filter_value": fv,
                "type":         [{"id": row.get('category', 'entity'),
                                  "name": row.get('category', 'Entity')}],
            })
        return {"result": results}

    def _detail(self, qs):
        if 'id' not in qs:
            self._json({"code": "error", "message": "Missing 'id' param"}, 400)
            return
        rid = qs['id'][0].strip()
        for row in self.rows:
            if row.get(self.id_col, '') == rid:
                self._json({"result": dict(row)})
                return
        self._json(
            {"code": "error", "message": f"No record with id '{rid}'"}, 404)

    def _config_get(self):
        total_w = sum(f["weight"] for f in self.filters)
        self._json({
            "dataset":       self.dataset,
            "id_field":      self.id_col,
            "name_field":    self.name_col,
            "algorithm":     self.algo_name,
            "all_fields":    self.cols,
            "filter_fields": self.filters,
            "name_weight":   round(1.0 - total_w, 4),
        })

    def _config_post(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            data = json.loads(body)
        except Exception as e:
            self._json({"code": "error", "message": f"Bad request: {e}"}, 400)
            return

        new_filters = []
        for entry in data.get("filter_fields", []):
            field = str(entry.get("field", "")).lower().strip()
            label = str(entry.get("label", field)).strip()
            weight = float(entry.get("weight", 0.2))

            if field not in self.cols:
                self._json(
                    {"code": "error", "message": f"Unknown field '{field}'"}, 400)
                return
            if not 0 <= weight <= 1:
                self._json(
                    {"code": "error", "message": f"Weight for '{field}' must be 0-1"}, 400)
                return

            new_filters.append(
                {"field": field, "label": label, "weight": weight})

        total = sum(f["weight"] for f in new_filters)
        if total >= 1.0:
            self._json({"code": "error",
                        "message": f"Filter weights sum to {total:.2f}, must be < 1.0"}, 400)
            return

        # rebuild normalised cache for new filter set
        new_norm = [[r.get(f["field"], '').lower().strip() for r in self.rows]
                    for f in new_filters]

        Handler.filters = new_filters
        Handler.norm_filters = new_norm

        self._json({"ok": True, "filter_fields": new_filters,
                    "name_weight": round(1.0 - total, 4)})

    def _page(self, filename):
        fpath = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), filename)
        if not os.path.exists(fpath):
            self.send_error(404, f"{filename} not found")
            return
        with open(fpath, 'r', encoding='utf-8') as fh:
            body = fh.read().encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, filename, ctype):
        fpath = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), filename)
        if not os.path.exists(fpath):
            self.send_error(404, f"{filename} not found")
            return
        with open(fpath, 'r', encoding='utf-8') as fh:
            body = fh.read().encode('utf-8')
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(
            f"{self.client_address[0]} [{self.log_date_time_string()}] {fmt % args}")


# -------------------------------------------------------
# Server startup helpers
# -------------------------------------------------------

def pick_filter_col(cols, skip):
    skip_set = [c.lower() for c in skip]
    good_words = ['state', 'country', 'nation',
                  'region', 'category', 'territory']

    # prefer English-labelled columns first
    for c in cols:
        if c in skip_set:
            continue
        if any(w in c for w in good_words) and c.endswith('en'):
            return c

    for c in cols:
        if c in skip_set:
            continue
        if any(w in c for w in good_words):
            return c

    return None


def start_server(csv_path, port, id_col, name_col,
                 algo='sequencematcher', preprocess=True, filters=None):

    rows, cols = load_csv(csv_path, id_col, name_col)

    if filters is None:
        detected = pick_filter_col(cols, skip=[id_col, name_col])
        if detected:
            filters = [{"field": detected, "label": detected, "weight": 0.2}]
            print(f"Auto-detected filter field: {detected}")
        else:
            filters = []
            print("No filter field detected — configure one via /config-ui")

    nc = name_col.lower()
    if preprocess:
        norm_names = [clean_text(r.get(nc, '')) for r in rows]
    else:
        norm_names = [r.get(nc, '').lower().strip() for r in rows]

    norm_filters = [[r.get(f["field"], '').lower().strip() for r in rows]
                    for f in filters]

    Handler.rows = rows
    Handler.cols = cols
    Handler.dataset = csv_path
    Handler.id_col = id_col.lower()
    Handler.name_col = nc
    Handler.algo_name = algo
    Handler.score_fn = staticmethod(ALGOS[algo])
    Handler.preprocess = preprocess
    Handler.filters = filters
    Handler.norm_names = norm_names
    Handler.norm_filters = norm_filters

    class TCPServer(ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with TCPServer(("", port), Handler) as srv:
        total_fw = sum(f["weight"] for f in filters)
        print(f"Running on http://localhost:{port}")
        print(f"  dataset    : {csv_path} ({len(rows)} records)")
        print(f"  id / name  : {id_col} / {name_col}")
        print(f"  algorithm  : {algo}")
        print(f"  preprocess : {preprocess}")
        print(f"  name weight: {round(1.0 - total_fw, 4)}")
        for f in filters:
            print(
                f"  filter     : {f['field']} (label={f['label']}, weight={f['weight']})")
        if not filters:
            print("  filters    : none")
        print(f"  ui         : http://localhost:{port}/ui")
        print(f"  config     : http://localhost:{port}/config-ui")
        print()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


# -------------------------------------------------------
# CLI
# -------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Reconciliation service for CSV datasets")
    ap.add_argument('--data', default='whc-sites-2025.csv')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--id-field', default=None)
    ap.add_argument('--name-field', default=None)
    ap.add_argument('--algorithm', default='sequencematcher',
                    choices=list(ALGOS.keys()))
    ap.add_argument('--no-preprocess', action='store_true')
    ap.add_argument('--filter-field', default=None, action='append', dest='filter_fields',
                    metavar='FIELD:WEIGHT',
                    help="e.g. --filter-field states_name_en:0.2 (repeatable)")
    args = ap.parse_args()

    id_col = args.id_field
    name_col = args.name_field

    if id_col is None or name_col is None:
        with open(args.data, newline='', encoding='utf-8-sig') as fh:
            lines = fh.readlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            raise ValueError("CSV looks empty")
        header = next(csv.reader(io.StringIO(lines[0])))
        lower_header = [h.lower().strip() for h in header]
        det_id, det_name = guess_fields(lower_header)
        if id_col is None:
            id_col = det_id
        if name_col is None:
            name_col = det_name
        print(f"Auto-detected: id={id_col}, name={name_col}")

    filters = None
    if args.filter_fields:
        filters = []
        for item in args.filter_fields:
            if ':' in item:
                col, w = item.rsplit(':', 1)
                try:
                    w = float(w)
                except ValueError:
                    w = 0.2
            else:
                col, w = item, 0.2
            col = col.lower().strip()
            filters.append({"field": col, "label": col, "weight": w})

    start_server(
        csv_path=args.data,
        port=args.port,
        id_col=id_col,
        name_col=name_col,
        algo=args.algorithm,
        preprocess=not args.no_preprocess,
        filters=filters,
    )


if __name__ == '__main__':
    main()