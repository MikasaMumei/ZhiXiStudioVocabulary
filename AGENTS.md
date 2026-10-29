# ZhiXi Studio Vocabulary

Read README.md first, then the relevant docs. Keep changes focused on teachers organizing vocabulary and printing materials.

- Chinese product copy; English code identifiers and descriptive file names.
- PostgreSQL is required for production and integration tests; never replace it with SQLite.
- Keep reusable dictionary values separate from course-specific meanings and pronunciations.
- Unknown American pronunciation stays blank. Do not relabel British or unverified IPA as American.
- Preserve traceable textbook editions, source information and real unit boundaries.
- Printing freezes content and order. Management operations must not rewrite snapshot, documents or checksum.
- Add new immutable Alembic migrations for schema changes. Do not alter published migrations or remove user data as an implicit downgrade.
- Keep PDFs local and deterministic with bundled fonts; no arbitrary URL or host-file fetching.
- Do not commit credentials, private imports, backups, actual deployment configuration or third-party vocabulary collections. Fonts retain their OFL notices.
- Run relevant PostgreSQL workflow checks. For layout changes inspect actual PDF geometry and rendered pages; HTML alone is not PDF validation.
- This file does not authorize production operations, installations, destructive cleanup or publication. Follow the operator's explicit scope.
