# Judge0 Runtime Configuration Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `test-driven-development` task-by-task. No production behavior is changed before a focused failing test demonstrates the required contract.

**Goal:** Prevent the general server-runtime initializer from overwriting an already configured remote Judge0 endpoint or its authentication settings.

**Architecture:** `configure-server-runtime.sh` will treat Judge0 as an external dependency by default and leave all existing `JUDGE0_*` settings untouched. A caller must opt in to the existing local Judge0 bootstrap behavior; only that explicit mode creates the local Judge0 environment file and writes the loopback endpoint and matching credentials. A test-only configurable application root lets the shell script be exercised in an isolated temporary directory while preserving `/opt/smartcarb-git` as its production default.

**Tech Stack:** Bash, existing deployment environment files, Python `pytest` test runner invoking Bash.

## Global Constraints

- Do not print, commit, or place Judge0 tokens in tests or documentation.
- Preserve `/opt/smartcarb-git` as the default deployment root.
- Default initialization must not create a local Judge0 secret file or modify any `JUDGE0_*` key.
- Local Judge0 setup remains available only through an explicit bootstrap mode.
- No remote deployment, service restart, dependency change, commit, or push is part of this fix.

---

### Task 1: Preserve externally configured Judge0 by default

**Files:**
- Create: `deploy/tests/test_configure_server_runtime_script.py`
- Modify: `deploy/scripts/configure-server-runtime.sh`

**Interfaces:**
- Consumes: `SMARTCARB_APP_ROOT` as an optional deployment-root override and `SMARTCARB_JUDGE0_BOOTSTRAP_MODE` as the bootstrap mode.
- Produces: a script that preserves all existing `JUDGE0_*` keys in default `preserve` mode.

- [ ] **Step 1: Write the failing test**

```python
def test_runtime_initializer_preserves_existing_remote_judge0_config(tmp_path):
    result = run_initializer(tmp_path, existing_remote_judge0_env)
    assert result.returncode == 0
    assert read_env(tmp_path)["JUDGE0_API_URL"] == "http://192.0.2.24:2358"
    assert read_env(tmp_path)["JUDGE0_AUTHN_TOKEN"] == "remote-authn"
    assert not (tmp_path / "deploy" / "judge0" / ".env").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest deploy/tests/test_configure_server_runtime_script.py -q`

Expected: FAIL because the initializer is fixed to `/opt/smartcarb-git` and has no preserve-by-default contract.

- [ ] **Step 3: Implement the minimal configuration contract**

```bash
readonly app_root="${SMARTCARB_APP_ROOT:-/opt/smartcarb-git}"
judge0_bootstrap_mode="${SMARTCARB_JUDGE0_BOOTSTRAP_MODE:-preserve}"

case "${judge0_bootstrap_mode}" in
  preserve) ;;
  local) configure_local_judge0 ;;
  *) echo "..." >&2; exit 2 ;;
esac
```

Move local secret generation and all `JUDGE0_*` writes into `configure_local_judge0`; do not touch those keys in `preserve` mode.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `backend/.venv/Scripts/python.exe -m pytest deploy/tests/test_configure_server_runtime_script.py -q`

Expected: PASS with the external endpoint and credentials unchanged.

### Task 2: Retain opt-in local bootstrap behavior

**Files:**
- Modify: `deploy/tests/test_configure_server_runtime_script.py`
- Modify: `deploy/scripts/configure-server-runtime.sh`

**Interfaces:**
- Consumes: `SMARTCARB_JUDGE0_BOOTSTRAP_MODE=local`.
- Produces: local `deploy/judge0/.env` plus backend Judge0 settings pointing to `http://127.0.0.1:2358` with generated local credentials.

- [ ] **Step 1: Write the failing test**

```python
def test_runtime_initializer_configures_local_judge0_only_when_requested(tmp_path):
    result = run_initializer(tmp_path, "", mode="local")
    assert result.returncode == 0
    backend_env = read_env(tmp_path)
    assert backend_env["JUDGE0_API_URL"] == "http://127.0.0.1:2358"
    assert (tmp_path / "deploy" / "judge0" / ".env").is_file()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest deploy/tests/test_configure_server_runtime_script.py -q`

Expected: FAIL until explicit `local` mode creates and applies the local Judge0 configuration.

- [ ] **Step 3: Implement only the local-mode branch**

Keep the prior local token generation and header setup inside `configure_local_judge0`. Validate the mode before writing any backend setting, and retain `chmod 600` for every environment file created or modified.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `backend/.venv/Scripts/python.exe -m pytest deploy/tests/test_configure_server_runtime_script.py -q`

Expected: PASS for both external preservation and explicit local initialization.

### Task 3: Verify deployment-script integrity

**Files:**
- Modify: `deploy/scripts/configure-server-runtime.sh`

**Interfaces:**
- Consumes: no additional runtime dependencies.
- Produces: a syntactically valid Bash script whose Judge0 behavior is covered by the focused regression tests.

- [ ] **Step 1: Validate script syntax**

Run: `bash -n deploy/scripts/configure-server-runtime.sh`

- [ ] **Step 2: Run the focused regression test suite**

Run: `backend/.venv/Scripts/python.exe -m pytest deploy/tests/test_configure_server_runtime_script.py -q`

- [ ] **Step 3: Inspect the final diff**

Run: `git diff --check` and `git diff -- deploy/scripts/configure-server-runtime.sh deploy/tests/test_configure_server_runtime_script.py docs/superpowers/plans/2026-08-13-judge0-runtime-config-safety.md`

- [ ] **Step 4: Do not commit**

The user requested a scoped repair, not a commit or push. Leave only the verified local changes for review.
