# Sprint 05 — Storage Layer Complete

**Date:** 2026-04-21
**Step (Parte K):** 5 — Storage completo (DuckDB, SQLite, Chroma, filesystem, in-memory)
**Status:** ✅ Complete

---

## What was done

Filled out the remaining four storage backends plus the in-memory test doubles the downstream modules will take as constructor arguments:

- `storage/duckdb_repo.py` — `DuckDBRepository` with the four analytical tables (`prices_eod`, `factor_series`, `peer_metrics_history`, `computed_betas`), typed upsert helpers (`insert_prices`, `insert_factor_series`, `insert_peer_metrics`, `insert_betas`), and a generic SQL `query` interface.
- `storage/sqlite_repo.py` — `MetadataRepository` on SQLAlchemy 2.0 typed ORM with five tables (`companies`, `archetypes`, `clusters`, `company_clusters`, `company_peers`) and CRUD/join helpers.
- `storage/chroma_repo.py` — `RAGRepository` wrapping ChromaDB's persistent client, collections partitioned by document type, metadata filtering, batch upsert, and an **injectable** embedding function (`EmbeddingFn = Callable[[list[str]], list[list[float]]]`).
- `storage/filesystem_repo.py` — `DocumentRepository` for PDF/blob storage at `{base}/{ticker}/{doc_type}/{filename}`.
- `storage/inmemory.py` — `InMemoryRepository[T]` and `InMemoryVersionedRepository[T]` as drop-in `Repository` / `VersionedRepository` doubles for unit tests.
- Unit tests for each: 5 new test files, 54 cases in total, covering happy paths, upsert semantics, error paths, and interface equivalence against the YAML concretes.

## Decisions taken

1. **`RAGRepository` takes an injectable `EmbeddingFn` with a deterministic stub fallback.** The OpenAI embeddings provider lands in Sprint 6; until then tests need hermetic, offline embeddings. The fallback `default_stub_embedding_fn` hashes input text with SHA-256 and maps the digest into a 16-dim `[0, 1)` vector — deterministic (identical text → identical vector), distinct (different text → different vector), and free of any external calls. Production code MUST inject a real fn — documented in the module docstring.
2. **`_InjectedEmbeddingFn` adapter implements Chroma's `EmbeddingFunction[Documents]` protocol.** Lets the injected plain callable participate in Chroma's normal `get_or_create_collection(embedding_function=...)` flow; no separate "pre-computed embeddings" path required. Type-ignored at the `_collection` call because Chroma's generic parameter is a union the stubs model imprecisely.
3. **`index_batch` rejects mixed metadata.** Chroma forbids `[dict, None, dict]` in a single call. The helper accepts a list of `(id, text, metadata|None)` tuples; if **every** tuple supplies a dict it is passed through, otherwise metadata is dropped for the whole batch. Explicit test (`test_batch_index_mixed_metadata_drops_all_metadata`) pins the behaviour.
4. **`DuckDBRepository` is NOT a `Repository[T]` subclass.** Its access pattern is set- and SQL-based rather than single-entity CRUD (`get(key)` doesn't model time-series rows well). It exposes typed insert helpers and a generic `query(sql, params)` — the contract that the downstream analytics module actually needs.
5. **DuckDB inserts use `ON CONFLICT ... DO UPDATE`** so ingestion is idempotent per primary key. `insert_prices` defaults the four nullable OHLCV columns in case the caller omits them; the other three tables default their optional columns similarly. Spec D.5 only showed `close` being upserted; extended to every mutable column so the upsert is lossless.
6. **`MetadataRepository` uses SQLAlchemy 2.0 declarative `DeclarativeBase` + `Mapped[...]`** for typed mappings. Each method opens a session-per-call with `with Session(engine) as session, session.begin()` — SQLite's concurrency story is poor, and scoping sessions keeps the surface tight. `NotFoundError` is raised if a join-side is missing (e.g., `link_company_to_cluster("GHOST", ...)`), matching the typed-exception contract.
7. **`DocumentRepository` is type-agnostic about blob content** — callers pass `bytes`, receive `bytes`. No PDF-specific parsing; `filesystem_repo` is a dumb store. Overwrites on re-store (callers version via filename, e.g. `2024-12-31_10K.pdf`).
8. **`InMemoryRepository` takes a `key_fn` callable.** Avoids encoding the ticker-normalisation / cluster-id logic of each concrete in the in-memory variant. Tests pass `lambda e: e.ticker` for `Position`, `lambda s: s.ticker` + `lambda s: s.snapshot_id` for `ValuationSnapshot`, etc. Interface is identical to the YAML concretes (verified by `isinstance(repo, Repository)` / `isinstance(repo, VersionedRepository)` assertions).
9. **SQLite / DuckDB / Chroma tests all use `tmp_path`** for per-test isolation. Chroma's `PersistentClient(path=str(tmp_path))` creates a fresh DB per test, removing any cross-test state contamination.
10. **Chroma collection names must be 3–512 chars matching `[a-zA-Z0-9._-]`.** Discovered when a test used `"c"` as the collection name. Tests use `"docs"`, `"filings"`, `"notes_mixed"`, etc. No implementation-level validation added — trust Chroma's error message.

## Spec auto-corrections

1. **DuckDB upsert coverage** — spec D.5 only upserted `close`. Extended every `DO UPDATE SET` clause to cover every mutable column in the table, so a re-ingest with corrected OHLCV replaces the full row rather than leaving stale values.
2. **Spec-exception naming continuity** — kept `NotFoundError` (not spec's `EntityNotFoundError`) for SQLite's "unknown foreign key" failures, consistent with Sprint 4 decision.
3. **Chroma embedding-function type** — spec mentions "injectable embedding function" abstractly; implementation needed an adapter because Chroma's API is protocol-based, not callable-based. `_InjectedEmbeddingFn` wraps a plain `Callable[[list[str]], list[list[float]]]`.
4. **`types-pyyaml` stayed the only typing-stubs dependency.** `types-duckdb`, `sqlalchemy-stubs`, `chromadb-types` either don't exist or are redundant (all three ship real annotations now). No new dev deps in Sprint 5.

## Files created / modified

```
A  src/portfolio_thesis_engine/storage/duckdb_repo.py       (4 tables, typed inserts, query)
A  src/portfolio_thesis_engine/storage/sqlite_repo.py       (MetadataRepository, 5 tables)
A  src/portfolio_thesis_engine/storage/chroma_repo.py       (RAGRepository with injectable fn)
A  src/portfolio_thesis_engine/storage/filesystem_repo.py   (DocumentRepository)
A  src/portfolio_thesis_engine/storage/inmemory.py          (InMemoryRepository + versioned)
A  tests/unit/test_duckdb_repo.py                           (7 test cases)
A  tests/unit/test_sqlite_repo.py                           (10 test cases)
A  tests/unit/test_chroma_repo.py                           (15 test cases)
A  tests/unit/test_filesystem_repo.py                       (9 test cases)
A  tests/unit/test_inmemory_repo.py                         (13 test cases)
A  docs/sprint_reports/05_storage_completo.md               (this file)
```

## Verification

```bash
$ uv run pytest
# 176 passed in 5.78s

$ uv run ruff check src tests
# All checks passed!

$ uv run ruff format --check src tests
# all files formatted

$ uv run mypy src
# Success: no issues found in 23 source files
```

## Tests passing / failing + coverage

All 176 tests pass (54 new Sprint 5 + 122 from prior sprints).

| Storage module              | Stmts | Miss | Cover |
| --------------------------- | ----- | ---- | ----- |
| `storage/__init__.py`       |   0   |  0   | 100 % |
| `storage/base.py`           |  31   |  0   | 100 % |
| `storage/yaml_repo.py`      | 178   | 16   |  91 % |
| `storage/duckdb_repo.py`    |  62   |  4   |  94 % |
| `storage/sqlite_repo.py`    |  84   |  2   |  98 % |
| `storage/chroma_repo.py`    |  65   |  8   |  88 % |
| `storage/filesystem_repo.py`|  37   |  4   |  89 % |
| `storage/inmemory.py`       |  51   |  1   |  98 % |
| **Storage total**           | 508   | 35   | **93 %** |
| **Project total**           | 1129  | 36   |  97 % |

All storage modules clear the ≥85% target. Uncovered lines are defensive error-wrapping paths that require OS-level failure injection (disk full, permission errors) we chose not to mock this sprint.

## Problems encountered

1. **Chroma collection-name validation** — first test run failed because the DI test used `"c"` as a collection name. Chroma requires 3+ chars. Renamed test fixtures to `"docs"`, `"notes_mixed"`, etc. No code change needed.
2. **Chroma metadata validation** — Chroma forbids empty dicts and rejects a `metadatas` list that mixes dicts with `None`. The initial `index_batch` implementation replaced `None` with `{}`, which errored. Rewrote to pass metadata only when all docs supply one; documented the contract and added a dedicated test (`test_batch_index_mixed_metadata_drops_all_metadata`).
3. **Chroma typing noise** — mypy strict flagged the injected embedding function's input type (Chroma expects `list[str] | list[np.ndarray]`), and the metadatas argument (Chroma expects `Mapping[str, scalar-union]` not `dict[str, Any]`). Resolved with two targeted `# type: ignore[arg-type]` at the Chroma call sites, with explanatory comments. chromadb's own typing is still maturing.
4. **SQLAlchemy relationship back-population warnings** discarded — we're not using ORM relationships for queries in Phase 0, just as schema declarations. No behavioural impact.
5. **No data corruption, no flaky tests** across three full `uv run pytest` runs during this sprint.

## Next step

**Sprint 6 — LLM orchestrator.** Build `llm/base.py` (`LLMProvider` protocol), `llm/cost_tracker.py`, `llm/anthropic_provider.py`, `llm/openai_provider.py` (embeddings only — and this is what will plug into `RAGRepository` via its `embedding_fn` parameter), `llm/retry.py` with tenacity, `llm/router.py` for judgment/analysis/classification model selection. Tests via mocked providers. Coverage target ≥85 %.
