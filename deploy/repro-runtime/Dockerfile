# repro-runtime 控制服务镜像（T1-b 验证用；生产部署另行决策）。
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY service.py swerex_adapter.py ./
# 清华镜像源优先（服务器直连 PyPI 亦可，构建失败时改直连重试）。
RUN pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    "swe-rex==1.4.0" "aiohttp>=3.10" "fastapi>=0.115" "uvicorn>=0.30" "httpx>=0.27" \
 && python -c "from swerex.deployment.docker import DockerDeployment; print('swe-rex ok')"
EXPOSE 8401
# 容器内必须绑 0.0.0.0（绑容器内 127 会导致宿主端口映射 RST）；
# 对外收敛由 docker -p 127.0.0.1:8401:8401 保证，宿主外不可达。
CMD ["python", "-m", "uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8401"]
