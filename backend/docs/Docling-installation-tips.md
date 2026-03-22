```bash
# 1. 确认 GPU
nvidia-smi

# 2. 升级 uv
uv self update

# 3. 进入项目目录（如果已经在就不用再 cd）
cd ~/projects/ai-course-system

# 4. 添加 PyTorch（自动选择 CUDA 后端）
uv pip install torch torchvision --torch-backend=auto

# 5. 添加 Docling
uv pip install docling

# 6. 验证 PyTorch GPU
uv run python -c "
import torch
print('PyTorch version:', torch.__version__)
print('CUDA available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('CUDA version (runtime):', torch.version.cuda)
    print('GPU:', torch.cuda.get_device_name(0))
"
```

More
```bash
#设置 HF 镜像环境变量
export HF_ENDPOINT="https://hf-mirror.com"
# 下载 Docling 所需的全部模型到本地缓存
uv run docling-tools models download
```

Then you can see:
```plaintext
Using the CLI: `docling --artifacts-path=/home/will_m/.cache/docling/models FILE` 
Using Python: see the documentation at <https://docling-project.github.io/docling/usage>.
```

So
```bash
cd ../test/assets
uv run docling --artifacts-path=/home/will_m/.cache/docling/models --to md U1.pdf
```

Add them to the dependence list of uv.
```bash
uv pip freeze > requirements.txt

# pipdeptree, a module for analyzing requirements.txt
uv pip install pipdeptree

pipdeptree | grep -v '^\s' | grep -v 'pipdeptree' | awk '{print $1}' | xargs -I {} uv add {}

uv add "fastapi>=0.135.1" "pytest>=9.0.2" "sqlmodel>=0.0.37" "passlib[bcrypt]>=1.7.4" "pillow>=12.1.1" "pydantic-settings>=2.13.1" "python-dotenv>=1.2.2" "python-jose[cryptography]>=3.5.0" "python-multipart>=0.0.22" "python-pptx>=1.0.2" "uvicorn>=0.41.0" "httpx>=0.28.1"
```
