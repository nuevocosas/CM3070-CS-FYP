"""
evaluate.py - Evaluation script for my Reconciliation Service
CM3010 Final Year Project

Tests all 3 algorithms (SequenceMatcher, Levenshtein, Jaro-Winkler) against:
  - 30 hand-picked test queries with known correct UNESCO IDs
  - WDPA dataset for cross-source reconciliation

Metrics used: Precision@1, Recall@3, MRR (Mean Reciprocal Rank)

Run: python evaluate.py
"""

import csv
import io
import os
from reconcile_service import clean_text, load_csv, ALGOS

# file paths
UNESCO_CSV = "whc-sites-2025.csv"
WDPA_CSV = "WDPA_Mar2026_Public_csv_truncated.csv"

# My 30 test queries - manually picked from the UNESCO list
# each one is (search_query, correct_id, what_kind_of_test)
# I tried to cover different kinds of realistic user input
TEST_QUERIES = [
    # exact matches - should be easy for any algorithm
    ("Galápagos Islands", "4", "exact"),
    ("Great Barrier Reef", "172", "exact"),
    ("Historic Centre of Vienna", "1206", "exact"),
    ("Angkor", "791", "exact"),
    ("Taj Mahal", "282", "exact"),
    ("Petra", "370", "exact"),
    ("Historic Centres of Berat and Gjirokastra", "1590", "exact"),
    ("Yellowstone National Park", "31", "exact"),
    ("Kasbah of Algiers", "667", "exact"),

    # no accents - user might not type special characters
    ("Galapagos Islands", "4", "no_accent"),
    ("Huascaran National Park", "379", "no_accent"),
    ("Historic Monuments Zone of Queretaro", "936", "no_accent"),
    ("Sun Temple, Konarak", "274", "no_accent"),

    # typos - common spelling mistakes
    ("Great Barier Reef", "172", "typo"),
    ("Machu Pichu", "305", "typo"),
    ("Timbuktoo", "131", "typo"),
    ("Gjirokaster Historic Centres", "1590", "typo"),

    # partial names - user only types part of the full name
    ("Fujisan sacred place", "1883", "partial"),
    ("Memphis Pyramid Fields", "92", "partial"),
    ("Pre-Hispanic City", "477", "partial"),
    ("Stonehenge", "1633", "partial"),
    ("Borobudur", "700", "partial"),

    # synonym/reworded - user uses different words for same place
    ("Galapagos archipelago", "4", "synonym"),
    ("Mount Fuji", "1883", "synonym"),
    ("Pyramids of Giza", "92", "synonym"),
    ("Fraser Island", "748", "synonym"),
    ("Athens Acropolis", "467", "synonym"),

    # missing punctuation - colons, commas, dashes removed
    ("Rio de Janeiro Carioca Landscapes between the Mountain and the Sea",
     "1843", "missing_punct"),
    ("Fujisan sacred place and source of artistic inspiration",
     "1883", "missing_punct"),
    ("Memphis and its Necropolis the Pyramid Fields from Giza to Dahshur",
     "92", "missing_punct"),
]


def run_tests(queries, records, algo_fn, use_preprocess=True, top_k=3):
    """
    Run a list of test queries and check how many got the right answer.
    Returns P@1, R@3, MRR and a list of which ones failed.
    """
    correct_at_1 = 0
    correct_in_top3 = 0
    mrr_total = 0.0
    n = len(queries)
    failed = []

    # pick which version of the name to compare against
    key = '_norm' if use_preprocess else '_raw'

    for query, expected_id, var_type in queries:
        # preprocess the query the same way we preprocess the stored names
        if use_preprocess:
            q = clean_text(query)
        else:
            q = query.lower().strip()

        # score every record and sort highest first
        scored = []
        for r in records:
            score = algo_fn(q, r[key])
            scored.append((score, r['unique_number']))
        scored.sort(key=lambda x: x[0], reverse=True)

        top_ids = [x[1] for x in scored[:top_k]]

        # check if correct answer is #1
        if top_ids and top_ids[0] == expected_id:
            correct_at_1 += 1

        # check if correct answer is anywhere in top 3
        if expected_id in top_ids:
            correct_in_top3 += 1
            rank = top_ids.index(expected_id) + 1
            mrr_total += 1.0 / rank
        else:
            # record the failure so i can analyse it later
            failed.append({
                'query': query,
                'expected': expected_id,
                'type': var_type,
                'got_top3': [(x[1], round(x[0], 3)) for x in scored[:top_k]],
            })

    return {
        'p1': round(correct_at_1 / n, 3) if n else 0,
        'r3': round(correct_in_top3 / n, 3) if n else 0,
        'mrr': round(mrr_total / n, 3) if n else 0,
        'total': n,
        'failed': failed,
    }


def main():
    # ---- Load UNESCO dataset ----
    print(f"Loading {UNESCO_CSV}...")
    unesco, _ = load_csv(UNESCO_CSV, 'unique_number', 'name_en')

    # pre-compute normalised names so we dont redo it every query
    for r in unesco:
        r['_norm'] = clean_text(r.get('name_en', ''))
        r['_raw'] = r.get('name_en', '').lower().strip()
        r['unique_number'] = r.get('unique_number', '')
    print(f"  Loaded {len(unesco)} records\n")

    output_rows = []  # will save to csv at the end

    # ==========================================================
    # PART 1 - test all algorithm + preprocess combinations
    # ==========================================================
    print("=" * 70)
    print("  PART 1: PRIMARY TEST SET (30 hand-crafted queries)")
    print("=" * 70)

    num_types = len(set(t[2] for t in TEST_QUERIES))
    print(f"  {len(TEST_QUERIES)} queries, {num_types} variation types\n")

    # table header
    print(f"  {'Algorithm':<20} {'Preproc':<10} {'P@1':>6} {'R@3':>6} {'MRR':>6}")
    print(f"  {'-'*20} {'-'*10} {'-'*6} {'-'*6} {'-'*6}")

    best_mrr = -1
    best = None  # will store (name, preprocess_flag, function, results)

    for algo_name, algo_fn in ALGOS.items():
        for pp in [True, False]:
            res = run_tests(TEST_QUERIES, unesco, algo_fn, use_preprocess=pp)
            label = 'Yes' if pp else 'No'
            print(
                f"  {algo_name:<20} {label:<10} {res['p1']:>6.3f} {res['r3']:>6.3f} {res['mrr']:>6.3f}")

            output_rows.append(['primary', algo_name, label,
                                res['total'], res['p1'], res['r3'], res['mrr']])

            if res['mrr'] > best_mrr:
                best_mrr = res['mrr']
                best = (algo_name, pp, algo_fn, res)

    # show which config won
    bname, bpp, bfn, bres = best
    print(f"\n  Best config: {bname} (preprocess={'Yes' if bpp else 'No'})")
    print(
        f"  P@1={bres['p1']:.3f}  R@3={bres['r3']:.3f}  MRR={bres['mrr']:.3f}")

    # show what failed for the best config
    if bres['failed']:
        print(f"\n  Failed queries ({len(bres['failed'])}):")
        for f in bres['failed']:
            top = f['got_top3'][0] if f['got_top3'] else ('?', 0)
            print(f"    [{f['type']:<15}] \"{f['query'][:50]}\"")
            print(
                f"       expected {f['expected']}, got {top[0]} (score {top[1]:.3f})")

    # breakdown by variation type for best config
    print(f"\n  Breakdown by type ({bname}):")
    print(f"  {'Type':<20} {'n':>3} {'P@1':>6} {'R@3':>6} {'MRR':>6}")
    print(f"  {'-'*20} {'-'*3} {'-'*6} {'-'*6} {'-'*6}")

    # group tests by their type
    by_type = {}
    for t in TEST_QUERIES:
        vtype = t[2]
        if vtype not in by_type:
            by_type[vtype] = []
        by_type[vtype].append(t)

    for vtype in sorted(by_type.keys()):
        group = by_type[vtype]
        r = run_tests(group, unesco, bfn, use_preprocess=bpp)
        print(
            f"  {vtype:<20} {len(group):>3} {r['p1']:>6.3f} {r['r3']:>6.3f} {r['mrr']:>6.3f}")

    # compare against a simple exact-match baseline
    def exact_match(a, b):
        return 1.0 if a == b else 0.0

    baseline = run_tests(TEST_QUERIES, unesco,
                         exact_match, use_preprocess=True)
    print(
        f"\n  Exact-match baseline:  P@1={baseline['p1']:.3f}  R@3={baseline['r3']:.3f}  MRR={baseline['mrr']:.3f}")
    gain = bres['p1'] - baseline['p1']
    print(
        f"  Improvement from fuzzy: +{gain:.3f} ({gain*100:.1f} percentage pts)")

    # ==========================================================
    # PART 2 - cross-source test with WDPA dataset
    # ==========================================================
    if not os.path.exists(WDPA_CSV):
        print(f"\n  Skipping WDPA test - {WDPA_CSV} not found")
        save_results(output_rows)
        return

    print()
    print("=" * 70)
    print("  PART 2: WDPA CROSS-SOURCE RECONCILIATION")
    print("=" * 70)

    # load WDPA and separate out the World Heritage Site rows
    wdpa_all = []
    wdpa_whs = []
    with open(WDPA_CSV, newline='', encoding='utf-8-sig', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            wdpa_all.append(row)
            if 'World Heritage Site' in row.get('DESIG_ENG', ''):
                wdpa_whs.append(row)

    print(f"  Total WDPA rows:     {len(wdpa_all)}")
    print(f"  World Heritage rows: {len(wdpa_whs)}")

    # --- 2A: match English names from WDPA against UNESCO ---
    # these should mostly match since both datasets use official English names
    print(f"\n  -- 2A: English name matching (WDPA NAME_ENG vs UNESCO) --\n")
    print(f"  {'Algorithm':<20} {'Matched':>8} {'Rate':>8} {'Avg Score':>10}")
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*10}")

    for algo_name, algo_fn in ALGOS.items():
        matched = 0
        score_sum = 0.0
        for entry in wdpa_whs:
            q = clean_text(entry.get('NAME_ENG', ''))
            best_s = 0
            for r in unesco:
                s = algo_fn(q, r['_norm'])
                if s > best_s:
                    best_s = s
            score_sum += best_s
            if best_s > 0.9:
                matched += 1

        n = len(wdpa_whs)
        avg = score_sum / n if n else 0
        print(
            f"  {algo_name:<20} {matched:>5}/{n:<3} {matched/n*100:>7.1f}% {avg:>10.3f}")
        output_rows.append(['wdpa_eng', algo_name, 'Yes', n,
                            round(matched/n, 3), '', round(avg, 3)])

    # --- 2B: try matching local/native names against UNESCO English names ---
    # this is expected to do badly since the names are in different languages
    wdpa_diff_lang = [r for r in wdpa_whs
                      if r.get('NAME', '').strip() != r.get('NAME_ENG', '').strip()
                      and r.get('NAME', '').strip()]

    print(f"\n  -- 2B: Local name matching ({len(wdpa_diff_lang)} entries) --")
    print(f"  Testing cross-language matching (expected to be poor)\n")
    print(f"  {'Algorithm':<20} {'Correct':>8} {'Rate':>8} {'Avg Score':>10}")
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*10}")

    for algo_name, algo_fn in ALGOS.items():
        correct = 0
        score_sum = 0.0
        for entry in wdpa_diff_lang:
            q = clean_text(entry.get('NAME', ''))
            expected_norm = clean_text(entry.get('NAME_ENG', ''))

            best_s = 0
            best_match = ''
            for r in unesco:
                s = algo_fn(q, r['_norm'])
                if s > best_s:
                    best_s = s
                    best_match = r['_norm']
            score_sum += best_s
            if best_match == expected_norm:
                correct += 1

        n = len(wdpa_diff_lang)
        avg = score_sum / n if n else 0
        print(
            f"  {algo_name:<20} {correct:>5}/{n:<3} {correct/n*100:>7.1f}% {avg:>10.3f}")
        output_rows.append(['wdpa_local', algo_name, 'Yes', n,
                            round(correct/n, 3) if n else 0, '',
                            round(avg, 3) if n else 0])

    # --- 2C: score distribution for ALL wdpa rows ---
    # most of these are not unesco sites so scores should be low
    print(f"  -- 2C: All WDPA rows ({len(wdpa_all)}) vs UNESCO --")
    print(f"  Score distribution using {bname}:\n")

    high = 0
    med = 0
    low = 0
    all_scores = []
    false_positives = []

    for entry in wdpa_all:
        q = clean_text(entry.get('NAME_ENG', '') or entry.get('NAME', ''))
        if not q:
            continue
        best_s = 0
        best_name = ''
        for r in unesco:
            s = bfn(q, r['_norm'])
            if s > best_s:
                best_s = s
                best_name = r.get('name_en', '')
        all_scores.append(best_s)
        if best_s > 0.9:
            high += 1
            is_whs = 'World Heritage Site' in entry.get('DESIG_ENG', '')
            if not is_whs:
                false_positives.append({
                    'wdpa_name': entry.get('NAME_ENG', '') or entry.get('NAME', ''),
                    'desig':     entry.get('DESIG_ENG', ''),
                    'matched':   best_name,
                    'score':     round(best_s, 3),
                })
        elif best_s > 0.7:
            med += 1
        else:
            low += 1

    n = len(all_scores)
    avg = sum(all_scores) / n if n else 0
    true_pos = high - len(false_positives)
    precision = true_pos / high if high else 0

    print(f"  Total:               {n}")
    print(f"  High conf (>0.9):    {high} ({high/n*100:.1f}%)")
    print(f"  Medium (0.7-0.9):    {med} ({med/n*100:.1f}%)")
    print(f"  Low (<0.7):          {low} ({low/n*100:.1f}%)")
    print(f"  Average score:       {avg:.3f}")
    print(f"\n  Of {high} high-conf hits:")
    print(f"    True positives  (actual WHS):  {true_pos}")
    print(f"    False positives (non-WHS):     {len(false_positives)}")
    print(f"    Precision at >0.9 threshold:   {precision:.3f}")

    if false_positives:
        print(f"\n  False positive examples (non-WHS rows scoring >0.9):")
        print(
            f"  {'Score':>6}  {'WDPA Name':<30} {'Designation':<28} {'Wrongly matched to':<30}")
        print(f"  {'-'*6}  {'-'*30} {'-'*28} {'-'*30}")
        for fp in false_positives[:10]:
            print(
                f"  {fp['score']:>6.3f}  {fp['wdpa_name'][:30]:<30} {fp['desig'][:28]:<28} {fp['matched'][:30]:<30}")

    output_rows.append(['wdpa_all', bname, 'Yes', n,
                        round(high/n, 3), round(precision, 3), round(avg, 3)])


def save_results(rows, path="evaluation_results.csv"):
    """Save all the numeric results to a CSV for the report."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['test_set', 'algorithm', 'preprocess', 'n',
                         'score_1', 'score_2', 'score_3'])
        writer.writerows(rows)
    print(f"\n  Saved results to {path}")


if __name__ == '__main__':
    main()
