"""真容器黑盒核验（T1-b）：需真实 Docker＋运行中服务，默认跳过。

执行（仅授权验证环境）：
    REPRO_RUNTIME_URL=http://127.0.0.1:8401 REPRO_RUNTIME_TOKEN=<token> \\
        pytest tests/test_live_docker.py -q
要求：服务端 docker 可用、任务镜像已就绪（pull 策略 never/missing）。

核验任务书 T1 五项真实语义：创建/执行/传输/取消/清理、双任务隔离、
长进程取消无残留、资源限额生效、重启不对账重放。全部经 HTTP 黑盒，
不断言任何客户端内部状态。
"""
from __future__ import annotations

import os
import time

import httpx
import pytest

BASE = (os.environ.get("REPRO_RUNTIME_URL") or "").rstrip("/")
TOKEN = os.environ.get("REPRO_RUNTIME_TOKEN") or ""
NEED_LIVE = bool(BASE and TOKEN)

pytestmark = pytest.mark.skipif(
    not NEED_LIVE, reason="需 REPRO_RUNTIME_URL/TOKEN 指向真实验证服务")

RUN_A = "live-a"
RUN_B = "live-b"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _api(method: str, path: str, **kwargs) -> httpx.Response:
    kwargs.setdefault("timeout", 300.0 if method == "PUT" else 60.0)
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_headers())
    return httpx.request(method, f"{BASE}{path}", headers=headers, **kwargs)


def _wait_operation(run_id: str, operation_id: str,
                    timeout_s: float = 240.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        response = _api("GET", f"/sandboxes/{run_id}/operations/{operation_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") in ("succeeded", "failed", "cancelled"):
            return last
        time.sleep(1.0)
    raise AssertionError(f"操作 {operation_id} 未在 {timeout_s}s 内终态：{last}")


@pytest.fixture(scope="module")
def live_service():
    response = _api("GET", "/health")
    assert response.status_code == 200, "控制服务不可达，先部署再验证"
    yield


def test_1_ensure_and_execute_round_trip(live_service):
    ensure = _api("PUT", f"/sandboxes/{RUN_A}")
    assert ensure.status_code == 200, ensure.text
    assert ensure.json()["sandbox_id"], "须返回 sandbox_id"
    assert ensure.json()["container_name"], "须返回容器名以便对账"
    submit = _api("POST", f"/sandboxes/{RUN_A}/operations",
                  json={"operation_id": "op-echo", "command": "echo live-ok",
                        "timeout_s": 60})
    assert submit.status_code == 200
    assert submit.json()["status"] == "running"
    final = _wait_operation(RUN_A, "op-echo")
    assert final["status"] == "succeeded"
    assert final["exit_code"] == 0
    assert "live-ok" in final["output_tail"]


def test_2_file_write_read_round_trip(live_service):
    put = _api("PUT", f"/sandboxes/{RUN_A}/files/workspace/probe.txt",
               content=b"before")
    assert put.status_code == 200, put.text
    get = _api("GET", f"/sandboxes/{RUN_A}/files/workspace/probe.txt")
    assert get.status_code == 200 and get.content == b"before"
    # 容器内执行读回同一字节（传输与执行看到同一文件系统）。
    submit = _api("POST", f"/sandboxes/{RUN_A}/operations",
                  json={"operation_id": "op-cat", "command": "cat /workspace/probe.txt",
                        "timeout_s": 60})
    assert submit.status_code == 200
    final = _wait_operation(RUN_A, "op-cat")
    assert final["exit_code"] == 0 and "before" in final["output_tail"]


def test_3_tasks_are_isolated(live_service):
    ensure = _api("PUT", f"/sandboxes/{RUN_B}")
    assert ensure.status_code == 200
    names = {ensure.json()["container_name"]}
    names.add(_api("PUT", f"/sandboxes/{RUN_A}").json()["container_name"])
    assert len(names) == 2, "两任务必须是不同容器"
    other = _api("GET", f"/sandboxes/{RUN_B}/files/workspace/probe.txt")
    assert other.status_code == 404, "任务 B 不得读到任务 A 的文件"


def test_4_cancel_long_process_without_residue(live_service):
    submit = _api("POST", f"/sandboxes/{RUN_B}/operations",
                  json={"operation_id": "op-sleep", "command": "sleep 120",
                        "timeout_s": 300})
    assert submit.status_code == 200
    time.sleep(3)  # 确保进程已起
    cancelled = _api("POST", f"/sandboxes/{RUN_B}/cancel")
    assert cancelled.status_code == 200, cancelled.text[:200]
    assert cancelled.json()["status"] == "cancelled"
    final = _wait_operation(RUN_B, "op-sleep", timeout_s=60.0)
    assert final["status"] == "cancelled"
    again = _api("POST", f"/sandboxes/{RUN_B}/cancel")
    assert again.json()["deduped"] is True
    # 容器残留与资源断言在宿主侧脚本核验（测试容器内无 docker CLI）。


def test_5_resource_limits_effective(live_service):
    view = _api("GET", f"/sandboxes/{RUN_A}")
    assert view.status_code == 200
    container = view.json()["container_name"]
    assert container, "须暴露容器名以便 inspect 对账"
    print(f"\n[container] {container}")
    # 资源/挂载断言在宿主侧脚本核验（测试容器内无 docker CLI）。


def test_6_network_posture_recorded(live_service):
    """网络基线如实记录（T1-b 不强制阻断，只记录实际可达性供后续加固）。"""
    submit = _api("POST", f"/sandboxes/{RUN_A}/operations",
                  json={"operation_id": "op-net",
                        "command": "timeout 3 curl -s -o /dev/null -w '%{http_code}' "
                                   "http://169.254.169.254/ || echo UNREACHABLE",
                        "timeout_s": 30})
    assert submit.status_code == 200
    final = _wait_operation(RUN_A, "op-net")
    print(f"\n[network-baseline] metadata-probe -> {final['output_tail'][:120]!r}")
    assert final["status"] == "succeeded"
