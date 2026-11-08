# Fixture document 3 — Version pair: attendance clause, old vs new (fixture corpus)

> FIXTURE ONLY. A tiny hand-written version pair for CI, not real
> FAST-NUCES documents. It exists so the version-sensitive golden
> questions (G09, G10) have something to retrieve in the e2e-eval job,
> and so the `superseded` filter can be exercised without the full
> corpus. Never cite it as a university source.

## Old version — Undergraduate Academic Rules, Aug 2023 (SUPERSEDED)

### Clause 1 — Attendance requirement

A student must attend at least 75% of the lectures of a course. A student
whose attendance falls below 75% is not permitted to sit the final
examination of that course.

Metadata for this version: `doc_version: "2023-08"`, `superseded: true`.

## Current version — Academic Rules Handbook, Jun 2026 (CURRENT)

### Clause 1.21 — Attendance requirement

A student must attend at least 80% of the lectures, tutorials and
laboratory sessions of a course. A student whose attendance falls below
80% is not permitted to sit the final examination of that course.

Metadata for this version: `doc_version: "2026-06"`, `superseded: false`.

## Why this pair exists

The same rule, two clause numbers (1 vs 1.21) and two thresholds
(75% vs 80%). A retriever without the `superseded` filter can faithfully
return the old version and confidently quote a repealed clause — failure
mode E. The correct answer to "which clause states the attendance
requirement?" is the CURRENT version: clause 1.21.

> NOTE: the 75% / 80% figures are FIXTURE values invented for CI. The
> real clause numbers (1 vs 1.21) are documented in assignment sec. 2;
> the real threshold must be read from the fetched Handbook — see
> `eval/golden.yaml` (G02, G09, marked `verified: false` for the value).
