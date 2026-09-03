import sys
from pathlib import Path

# deploy/repro-worker 是独立服务（不属于 backend/nexus 包），测试时把本目录
# 加进 sys.path 以便 `import worker`。
sys.path.insert(0, str(Path(__file__).resolve().parent))
