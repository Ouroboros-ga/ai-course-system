# CodeNexus Repro Worker（P1-W1）
# 不可信论文仓库的受限执行器：独立容器、非 root 运行、资源限额在 compose/run
# 时施加（--cpus/--memory/--pids-limit），本镜像只装最小执行栈。
#
# 构建（服务器境内网络走清华 PyPI 镜像）：
#   docker build -t repro-worker:latest \
#     --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple deploy/repro-worker/
FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list ; \
    apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" \
    "fastapi>=0.115.0" "uvicorn>=0.34.0" "httpx>=0.28.0" "pydantic>=2.10.0"

# 预装 torch（tuna 镜像，全量 ~3GB：torch 2.14 在 import 时即硬性要求 CUDA
# 库，无法裁剪）。镜像体积换确定性——任务步骤只装轻量依赖。宿主机需预留
# ~6GB 磁盘；/jobs 任务配额（2GB）与镜像互不影响。
RUN pip install --no-cache-dir torch==2.14.0 --index-url "${PIP_INDEX_URL}" \
 && python -c "import torch; print('torch', torch.__version__)" \
 && python -c "import torch; print('cpu-matmul:', (torch.ones(2,2) @ torch.ones(2,2)).sum().item())"

# 非 root 运行；工作目录独立挂载（代码内另强制 2GB 配额）
RUN useradd --create-home --shell /usr/sbin/nologin worker \
    && mkdir -p /jobs \
    && chown -R worker:worker /jobs

WORKDIR /app
COPY --chown=worker:worker worker.py /app/worker.py

ENV REPRO_WORKER_WORKSPACE_ROOT=/jobs \
    REPRO_WORKER_HOST=0.0.0.0 \
    REPRO_WORKER_PORT=8400

USER worker
EXPOSE 8400

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8400/health || exit 1

CMD ["python", "-m", "uvicorn", "worker:app", "--host", "0.0.0.0", "--port", "8400"]
