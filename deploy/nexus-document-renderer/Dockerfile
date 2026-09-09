# F6 文档渲染器镜像（骨架，未构建；构建需单独批准并锁定摘要）
FROM pandoc/core:3 AS pandoc
FROM texlive/texlive:latest

COPY --from=pandoc /usr/local/bin/pandoc /usr/local/bin/pandoc

# CJK 字体（构建时锁定版本；此处为包名，摘要在构建日志中记录）
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    latexmk \
  && rm -rf /var/lib/apt/lists/*

# 可信模板只读挂载（构建期 COPY，运行时只读）
COPY templates/ /opt/renderer/templates/:ro

# 非 root 运行；无外网由部署网络策略保证（见 NETWORK 约定）
USER 65532:65532
ENTRYPOINT ["/opt/renderer/render.sh"]
