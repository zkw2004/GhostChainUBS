# Ghost Chains: Phase 1 Build Pack

Specification pack for a real-time AML transaction risk scoring service.
Everything an implementing agent needs is in `docs/`. Read `CLAUDE.md` first.

## Read order

| # | File | Purpose |
|---|------|---------|
| 0 | [CLAUDE.md](CLAUDE.md) | Agent entrypoint, non-negotiable rules, definition of done |
| 1 | [docs/00-problem-brief.md](docs/00-problem-brief.md) | Plain-language restatement of the challenge |
| 2 | [docs/01-architecture.md](docs/01-architecture.md) | Modules, data structures, request lifecycle |
| 3 | [docs/02-scoring-model.md](docs/02-scoring-model.md) | The scoring mathematics, worked examples |
| 4 | [docs/03-api-contract.md](docs/03-api-contract.md) | Exact endpoint behaviour and error handling |
| 5 | [docs/04-implementation-plan.md](docs/04-implementation-plan.md) | Ordered task list with acceptance criteria |
| 6 | [docs/05-testing-strategy.md](docs/05-testing-strategy.md) | Unit, golden, property, differential, load tests |
| 7 | [docs/06-decisions.md](docs/06-decisions.md) | Decision register for ambiguous spec points |
| 8 | [docs/07-tuning-diagnostics.md](docs/07-tuning-diagnostics.md) | How to react to evaluator diagnostics |
| 9 | [docs/08-phase-2-3-readiness.md](docs/08-phase-2-3-readiness.md) | Forward compatibility hooks |

## The problem in four sentences

A stream of money transfers arrives over HTTP. Each transfer becomes a directed edge
in a graph of entities, and only the last 24 hours of edges are active. For every
transfer, return a score in `[0.0, 1.0]` measuring how much that single edge increased
the graph's capacity to support recurring, circular flow. Grading is on ranking order
and on structural consistency across unseen but related scenarios, never on absolute values.

## Target stack

- Python 3.11+, FastAPI, uvicorn
- No database. All state in process memory, bounded by the 24 hour window.
- pytest, pytest-asyncio, hypothesis
- Docker, deployed to Railway (or any host giving a public HTTPS URL)
- GitHub Actions running the full test suite on every push

## Quickstart for the implementing agent

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
pytest -q
```
