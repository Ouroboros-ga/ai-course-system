"""Provider implementations (ports) for the agent layer.

This subpackage holds the concrete port implementations that adapt
application services into the port protocols consumed by LangGraph nodes.
The former flat ``tools/`` modules have been reorganized into domain
subpackages here; the old ``tools/<name>.py`` paths remain importable via
backward-compatible re-export shims.

Layout:

- ``providers/retrieval/demo``       — retrieval-demo ports (scope, graph,
  evidence) plus the small callable adapters historically bundled there
  (student modeling, recommendation, learning-event, sandbox).
- ``providers/cognition/``           — cognition state, student modeling,
  and KG-MEST shadow ports.
- ``providers/sandbox/coding``       — coding diagnosis and student history.
- ``providers/recommendation/``      — next-action recommendation port.
- ``providers/teaching/``            — learning events, conversation context,
  and the OpenAI-compatible LLM adapter.
- ``providers/research/``           — web research and question bank ports.
- ``providers/governance/``          — tool governance and teacher safety valve.
- ``providers/experiment/``          — course experiments and visualization.
- ``providers/fakes``               — offline test fakes (flat; no subpackage).

Submodules are imported directly (e.g.
``from app.platform.agents.providers.cognition import CallableCognitionPort``);
this package does not re-export every name.
"""
