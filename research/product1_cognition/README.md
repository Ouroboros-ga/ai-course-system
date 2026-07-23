# Product 1 Cognition Research Sandbox

`cognition/kg_mest.py` is a dependency-free, synthetic-data KG-MEST baseline.
It is not connected to `backend/app`, production databases, formal Memory,
existing mastery scores or user-facing recommendations.

Run its tests with:

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s research\product1_cognition\tests -p "test_kg_mest.py" -v
```

The source, fixture and test files are the current research baseline.  Old
bytecode-only artefacts are historical remnants and are not implementation
evidence.

`cognition/legacy_prerequisite_candidates.py` is a read-only bridge for the
legacy `KnowledgeRelation(relation_type="prerequisite")` records.  It requires
an already course-scoped export, produces only `status="candidate"` graph
edges, and deliberately has no promotion API.  A candidate cannot be consumed
by `adapt_cognition_graph` until an external graph-governance workflow supplies
an accepted, evidence-backed, acyclic course snapshot.

For a real read-only Shadow hand-off, use the five-file local bundle format:
`manifest.json`, `graph_nodes.json`, `graph_relations.json`,
`review_decisions.json`, and `learning_events.json`. The standard-library tool
`tools/run_shadow_bundle.py --bundle-dir <directory>` validates the governance
declarations before running and prints a report without raw source IDs or event
payloads. It is not a production API and never opens a database connection.
The manifest must also contain canonical SHA-256 values for all four input
artifacts, so a reviewed bundle cannot silently run against changed content.
`fixtures/shadow_bundle_synthetic_v1/` is a fully synthetic executable example.
