"""Storage layer — repositories, unit of work, concrete backends.

Modules access storage only through the :class:`Repository` or
:class:`VersionedRepository` abstract bases defined in
:mod:`portfolio_thesis_engine.storage.base`. Concrete backends:

- YAML files — human-editable source of truth for entities.
- DuckDB — analytical time series (prices, factors, betas).
- SQLite — relational metadata (companies, clusters, peers).
- ChromaDB — vector store for RAG.
- Filesystem — blob storage for PDFs and other raw documents.
- In-memory — drop-in test doubles for any of the above.
"""
