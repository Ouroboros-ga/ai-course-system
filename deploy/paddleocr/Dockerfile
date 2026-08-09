# 独立 PaddleOCR 服务镜像。
# 主后端不安装 paddle；仅此镜像包含 paddleocr/paddlepaddle。
# CPU 推理；固定版本以避免漂移。
FROM python:3.11-slim

# 系统依赖：libgomp（paddlepaddle CPU 运行时需要）、libgl（PIL 处理图片需要）
ARG DEBIAN_MIRROR=deb.debian.org
ARG DEBIAN_SECURITY_MIRROR=deb.debian.org
RUN sed -i \
      -e "s|deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}/debian-security|g" \
      -e "s|deb.debian.org/debian|${DEBIAN_MIRROR}/debian|g" \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用层缓存）。requirements.lock 固定版本。
COPY requirements.lock /app/requirements.lock
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.lock

# 服务代码
COPY service/ /app/service/

WORKDIR /app/service

# 模型缓存卷：paddleocr 首次运行会下载模型到此
ENV PADDLEOCR_HOME=/root/.paddleocr
RUN mkdir -p /root/.paddleocr

# 预热：在构建期触发模型下载并固化到镜像，避免运行时每次拉取。
# 若 models.lock.json 标注 offline_models=true，则跳过预热（用挂载卷的模型）。
ARG PREWARM_MODELS=true
RUN if [ "$PREWARM_MODELS" = "true" ]; then \
        python -c "from provider import PaddleRuntime; assert PaddleRuntime.available, 'prewarm failed: paddleocr not importable'"; \
    fi

EXPOSE 8090

# 健康检查：容器编排据此判定 service_healthy
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8090/health',timeout=4); sys.exit(0 if r.status==200 else 1)" || exit 1

CMD ["python", "app.py"]
