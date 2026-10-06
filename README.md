# Customer Intelligence Platform

An executable reference slice for an evidence-oriented customer intelligence workflow. It demonstrates how live conversation state, deterministic business policy, governed guidance, bounded language-model explanation, and post-call enrichment can work together without allowing asynchronous results to override newer truth.

The repository is intentionally small and local-first:

- Python 3.12+, FastAPI, and SQLite.
- Synthetic customer and conversation data only.
- One process with an explicit per-call coordinator; no distributed service estate.
- Deterministic adapters for policy, sentiment, eligibility, guidance, and race tests.
- An optional real-model adapter kept behind the same bounded explanation interface.

## Run locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765>. The Workbench opens in a customer-service view: the main question is what the customer needs now and what the agent should do next. Switch to “Supervisor review” for service outcome/post-call review or “Technical evidence” for versions, dependencies, lifecycle and traces. Use “Run complete scenario” for the first walkthrough, or advance one step at a time to inspect why a recommendation is suppressed and later released. API documentation is available at `/docs`.

If `frontend/index.html` is opened directly as a local file, the page can still reach a running local API through its explicit `http://127.0.0.1:8765` base URL. The HTTP URL above is the recommended entry point because it keeps the browser and API origin together.

Run the deterministic suite with:

```bash
pytest -q
```

## What is implemented

The reference path covers:

- canonical transcript revisions and whole-transcript derived snapshots;
- aspect sentiment, known themes, and complaint signal separate from authoritative complaint state;
- trusted authorization with current permission checks at mutation and publication boundaries;
- fixed-contract propensity, deterministic eligibility, suppression, and contextual ranking;
- guidance citations with source/version metadata;
- structured protected facts plus bounded explanation validation;
- complete assistance-view snapshots ordered by monotonic `ui_seq`;
- separate business outcome and delivery lifecycle;
- dependency expiry, call-end invalidation, and deletion anti-resurrection;
- immutable post-call input snapshots and lexicographic enrichment precedence;
- structured traces and evidence labels.

The default run is contract evidence, not a production deployment, a scale benchmark, a legal/compliance certification, or proof of business uplift. Optional external model evidence must be configured separately and is labelled as such.

## Architecture boundary

The local reference implementation deliberately leaves telephony, enterprise identity, cloud search, production data platforms, and distributed event infrastructure behind adapter interfaces. Those are deployment choices for a later integration path; the business invariants are exercised locally first.

See [docs/architecture.md](docs/architecture.md), [docs/data-contracts.md](docs/data-contracts.md), and [docs/demo-scenario.md](docs/demo-scenario.md).
