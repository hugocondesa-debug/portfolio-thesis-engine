# Sprint 04 — Storage Base + YAML Repos

**Date:** 2026-04-21
**Step (Parte K):** 4 — Storage base + YAML repositories
**Status:** ✅ Complete

---

## What was done

Built the storage contracts and the YAML-backed implementations of every entity repository the engine needs for human-edited data:

- `storage/base.py` — abstract `Repository[T]`, `VersionedRepository[T]`, `UnitOfWork` (Phase 0 stub), typed-exception re-exports.
- `storage/yaml_repo.py` — generic `YAMLRepository[T]` and `VersionedYAMLRepository[T]`, plus concrete `CompanyRepository`, `PositionRepository`, `PeerRepository`, `MarketContextRepository`, `ValuationRepository` (versioned), `CompanyStateRepository` (versioned).
- Atomic file writes via `tempfile.mkstemp` + `Path.replace`, so a crash between write and rename never corrupts the live file.
- Atomic symlink swaps for the `current` pointer in versioned repos (tmp symlink → `Path.replace`).
- 33 new unit tests covering CRUD, versioning semantics, YAML roundtrip via repos, ticker normalisation (`ASML.AS` → `ASML-AS`), `NotFoundError` on missing version, and a crash-in-the-middle-of-save test that proves the previous `current` stays intact.

## Decisions taken

1. **Typed exceptions live in `shared/exceptions.py` and are re-exported from `storage/base.py`.** Spec D.2 places `StorageError` / `EntityNotFoundError` / `EntityAlreadyExistsError` inside `storage/base.py` directly; but Sprint 2 already defined `StorageError`, `NotFoundError`, `VersionConflictError` in `shared/exceptions.py` for use across all layers. Re-exporting via `__all__` keeps Hugo's naming (`NotFoundError`, `VersionConflictError`) and lets call sites still write `from portfolio_thesis_engine.storage.base import StorageError`. Dropped spec's `EntityAlreadyExistsError` — `VersionConflictError` covers the semantic in a versioned world.
2. **`UnitOfWork` is a stub** with `__enter__`/`__exit__`/`commit`/`rollback` that are no-ops. Each method is annotated with a `TODO Phase 1` comment pointing at the expected behaviour (cross-repo commit/rollback). Call sites can adopt the pattern now without behaviour changing.
3. **Repository `TypeVar` bound is `BaseSchema`, not `BaseModel`.** Since `from_yaml`/`to_yaml` live on `BaseSchema`, that's the real minimum surface area the repositories require. Every top-level schema extends `BaseSchema`, so no loss of coverage.
4. **Atomic write helper is a module-level private `_atomic_write_text`** rather than a `staticmethod`. Tests import it directly to exercise the crash path, and keeping it as a plain function makes the intent obvious — both generic and versioned repos call it.
5. **Crash simulation mocks `Path.replace`** rather than `os.replace`. Ruff's `PTH105` prefers `Path.replace` anyway; patching it scopes the fault to the atomic swap step, which is exactly where crashes would leave partial state.
6. **Ticker normalisation centralised in `_normalise_ticker`**: `.` → `-`. Spec mentions this (`MTRO-L` for `MTRO.L`) but doesn't say where the transformation happens. Putting it at the repo boundary keeps schemas clean (they still carry the original ticker string) and filesystem paths safe.
7. **`PeerRepository` takes `parent_ticker` in its constructor.** Each parent company has its own peers directory; making the parent part of the repo's identity avoids threading it through every call.
8. **`CompanyRepository` and `MarketContextRepository` override `list_keys`** because their layout is `{base}/{key}/ficha.yaml` and `{base}/{cluster_id}/context.yaml` — the default `*.yaml` glob at `base_path` wouldn't find them. Overriding scopes the scan to top-level directories with the expected inner file.
9. **Versioned repos' `_retarget_current` creates the temp symlink in the same directory and uses `Path.replace`** to swap it over the live `current`. Same atomicity guarantee as file writes. Symlinks store the relative target (`{version}.yaml`) rather than absolute paths so the tree is portable.
10. **`get` on versioned repos delegates to `get_current`**, consistent with the spec's "current latest version" reading model. Explicit versions only come via `get_version(key, version)`.

## Spec auto-corrections

1. **Exception naming** — spec used `EntityNotFoundError` / `EntityAlreadyExistsError`; Hugo's prompt uses `NotFoundError` / `VersionConflictError` (which already existed from Sprint 2). Went with Hugo's names; no duplicates created.
2. **Exception location** — spec placed them in `storage/base.py`; keeping in `shared/exceptions.py` and re-exporting. Matches Sprint 2 decision.
3. **Generics syntax** — spec shows the old-style `T = TypeVar("T", bound=BaseModel); class Repository(ABC, Generic[T])`. Ruff UP046 wants PEP 695 `class Repository[T: BaseSchema](ABC)` on Python 3.12. Adopted; no `TypeVar` module-level declaration needed.
4. **`yaml_repo.py` save/load via `entity.to_yaml()` / `entity_class.from_yaml()`** instead of spec D.4's direct `yaml.safe_dump(entity.model_dump(mode="json", exclude_none=True))`. Reuses the Sprint 3 helpers so Decimal precision is preserved identically in both directions. (Also means versioned-snapshot round-trip equality works with the same guarantees as the Sprint 3 schema tests.)
5. **`os.replace` → `Path.replace`** throughout. Same atomic semantics; passes ruff PTH105.

## Files created / modified

```
A  src/portfolio_thesis_engine/storage/__init__.py
A  src/portfolio_thesis_engine/storage/base.py          (Repository, VersionedRepository, UnitOfWork)
A  src/portfolio_thesis_engine/storage/yaml_repo.py     (generic + 6 concrete repos)
A  tests/unit/test_storage.py                           (33 tests)
A  docs/sprint_reports/04_storage_base.md               (this file)
```

## Verification

```bash
$ uv run pytest
# 122 passed in 0.89s

$ uv run ruff check src tests
# All checks passed!

$ uv run ruff format --check src tests
# 28 files already formatted

$ uv run mypy src
# Success: no issues found in 18 source files
```

Crash-safety smoke proof (captured inline in `TestVersionedSaveAtomicity`): starting from one saved `ValuationSnapshot`, a second `save()` is attempted where `Path.replace` is patched to raise `RuntimeError`. Post-crash, `repo.get_current("ACME")` still returns the first snapshot byte-for-byte equal to the original.

## Tests passing / failing + coverage

All 122 tests pass (33 new + 89 from Sprints 1–3).

| Storage module          | Stmts | Miss | Cover |
| ----------------------- | ----- | ---- | ----- |
| `storage/__init__.py`   |   0   |  0   | 100 % |
| `storage/base.py`       |  31   |  0   | 100 % |
| `storage/yaml_repo.py`  | 178   | 16   |  91 % |
| **Storage total**       | 209   | 16   | **92 %** |
| **Project total**       | 828   | 17   |  98 % |

The 16 uncovered lines in `yaml_repo.py` are defensive error wrappers inside try/except that only fire on disk failures (e.g., saving to a path that exists as a directory, which the OS rejects first with a permission/type error). Coverage comfortably clears the Sprint 4 target.

## Problems encountered

1. **`ruff UP046` complained about the spec's `Generic[T]` form.** Migrated to PEP 695 class-generic syntax (`class Repository[T: BaseSchema](ABC):`). Required removing the module-level `TypeVar` declaration and updating every subclass (`VersionedRepository`, `YAMLRepository`, `VersionedYAMLRepository`).
2. **`ruff PTH105`** flagged `os.replace`. Switched to `Path.replace`. Tests' `patch("...os.replace", ...)` had to move to `patch.object(Path, "replace", ...)`.
3. **`ruff RET501`** flagged explicit `return None` in no-op stubs. Removed them — docstrings alone satisfy the function-body requirement.
4. **No design blockers.** The versioned layout with a `current` symlink works cleanly on Linux `tmpfs` (pytest `tmp_path`); no portability concerns surface in Phase 0 because deployment target is Ubuntu 24.04 VPS.

## Next step

**Sprint 5 — remaining backends.** `duckdb_repo.py` with the four analytical tables (prices_eod, factor_series, peer_metrics_history, computed_betas); `sqlite_repo.py` / `MetadataRepository` on SQLAlchemy; `chroma_repo.py` / `RAGRepository` with an injectable `embedding_fn` (deterministic hash stub when none supplied); `filesystem_repo.py` / `DocumentRepository` for blobs; `storage/inmemory.py` with drop-in in-memory variants of `Repository` and `VersionedRepository` for downstream unit tests. Coverage target ≥85 % on storage.
