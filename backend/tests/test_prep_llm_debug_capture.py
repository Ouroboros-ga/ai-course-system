from app.platform.agents.providers.llm.debug_capture import LocalPrepLLMDebugCaptureStore


def test_local_prep_capture_requires_explicit_course_opt_in(tmp_path):
    store = LocalPrepLLMDebugCaptureStore(root=tmp_path)

    assert store.capture(
        course_id=87, run_id="run_before", trace_id="trace", agent_type="prep",
        stage="plan", purpose="test", attempt=1,
        messages=[{"role": "user", "content": "private prompt"}],
        response_content="private response", model="model", finish_reason="stop",
        usage={}, requested_max_tokens=2048, temperature=0.2,
        response_format={"type": "json_object"}, provider_options={"thinking": {"type": "disabled"}},
        response_format_fallback=False,
    ) is None

    assert store.set_enabled(course_id=87, enabled=True) is True
    path = store.capture(
        course_id=87, run_id="run_after", trace_id="trace", agent_type="prep",
        stage="plan", purpose="test", attempt=1,
        messages=[{"role": "user", "content": "private prompt"}],
        response_content="private response", model="model", finish_reason="stop",
        usage={"output_tokens": 3}, requested_max_tokens=2048, temperature=0.2,
        response_format={"type": "json_object"}, provider_options={"thinking": {"type": "disabled"}},
        response_format_fallback=False,
    )

    assert path is not None and path.is_file()
    records = store.read_run(course_id=87, run_id="run_after")
    assert records[0]["request"]["messages"][0]["content"] == "private prompt"
    assert records[0]["response"]["content"] == "private response"
    assert records[0]["request"]["provider_options"] == {"thinking": {"type": "disabled"}}
    assert store.read_run(course_id=88, run_id="run_after") == []


def test_local_prep_capture_rejects_non_prep_agents(tmp_path):
    store = LocalPrepLLMDebugCaptureStore(root=tmp_path)
    store.set_enabled(course_id=87, enabled=True)

    path = store.capture(
        course_id=87, run_id="challenge", trace_id="trace", agent_type="edu_coding_challenge",
        stage="generate", purpose="coding_challenge_generation", attempt=1,
        messages=[{"role": "user", "content": "must not persist"}],
        response_content="must not persist either", model="model", finish_reason="stop",
        usage={}, requested_max_tokens=2048, temperature=0.2,
        response_format={"type": "json_object"}, provider_options={},
        response_format_fallback=False,
    )

    assert path is None
    assert store.read_run(course_id=87, run_id="challenge") == []
