# Product 1 Gold Fixtures

This directory contains frozen gold-standard benchmarks for Product 1 quality
evaluation.  Each subdirectory represents a distinct quality dimension.

## Directory Layout

```
gold/
  parser/               -- Parsing quality (block/page/bbox/order/table/formula)
  coordinate/           -- Coordinate geometry precision (normalized bbox/polygon)
  citation/             -- Citation accuracy (text/page/block support)
  retrieval/            -- Retrieval quality (Recall@k, MRR, nDCG)
  memory_privacy/       -- Memory isolation and privacy controls
  memory_deletion/      -- Memory deletion completeness (tombstone/cache)
  learning_event/       -- Learning event integrity and replay
  rule_baseline/        -- Rule-based baseline mastery accuracy
  safety_policy/        -- Safety policy enforcement (platform/course rules)
  migration/            -- Database migration forward compatibility
  rollback/             -- Migration rollback integrity
```

## Fixture Provenance

Every fixture MUST have its provenance recorded.  The `provenance.json` file
at this level tracks the source, license, owner, and usage restriction for
each category.  Fixtures without recorded provenance MUST NOT be used for
release-gate decisions.

## Strict Separation

These gold benchmarks are DISTINCT from fake/contract tests in
`backend/tests/product1/`:

| Type | Purpose | Example |
|------|---------|---------|
| Fake/contract tests | Prove control flow, error semantics, isolation | `FakeParserProvider` |
| Gold benchmarks | Prove real quality (parsing, retrieval, citation) | Frozen annotated PDF |

Do NOT mix these two categories.  Contract tests must never claim model
quality.  Gold benchmarks must never be altered to pass a failing test.

## Populating Fixtures

Each category directory is initially empty.  Populate with:

1. Self-authored or clearly licensed documents (no proprietary/copyrighted data
   without written permission).
2. Annotated gold-standard outputs (JSON, annotations, expected metrics).
3. A per-category manifest (manifest.json) listing all samples and their
   expected measurements.

See `tests/benchmarks/product1/runner.py` for the benchmark runner interface.
