# CM3070 Final Year Project — Final Report

**Topic:** CM3010 Databases and Advanced Data Techniques
**Project Idea:** 2 — Reconciliation service for a dataset
**Project Title:** Reconciliation Service for Cultural Heritage Datasets

---

## Quick Start

```bash
# Start the service
python reconcile_service.py --data whc-sites-2025.csv --port 8000

# Open the web UI
open http://localhost:8000/ui
```

## Key Options

| Option | Default | Description |
|--------|---------|-------------|
| `--data` | `whc-sites-2025.csv` | Path to CSV dataset |
| `--port` | `8000` | Port to listen on |
| `--algorithm` | `sequencematcher` | `sequencematcher`, `levenshtein`, or `jarowinkler` |
| `--filter-field` | auto-detect | e.g. `states_name_en:0.2` |

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `/reconcile` | Reconciliation queries |
| `/detail` | Full record lookup by ID |
| `/ui` | Search interface |
| `/config-ui` | Filter configuration |

## Tests

```bash
pip install pytest
pytest test_reconcile.py -v
```