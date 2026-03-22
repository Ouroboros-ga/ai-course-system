# WSL2 环境下 UV + PyCharm + CUDA 开发环境配置实录
> **文档说明**：本文记录了从 Windows 本地开发迁移至 WSL2 Linux 环境的完整过程，包含文件系统适配、WSL版本升级、PyCharm 配置及 CUDA 环境修复。
---
## 1. 硬件与环境背景
在开始排错前，确认宿主机环境是解决兼容性问题的关键。
- **系统版本**: Windows 10 21H2 (Build 19044.7058)
- **WSL 版本**: WSL 2 (由 WSL 1 升级而来)
- **Linux 发行版**: Ubuntu 22.04 LTS
- **硬件配置**:
  - **CPU**: AMD Ryzen 5 5600
  - **RAM**: 32GB DDR4 3600
  - **GPU**: NVIDIA RTX 5060 (8GB VRAM) 
  - **Storage**: 1TB PCIe 4.0 NVMe SSD
---
## 2. 第一阶段：UV 安装与文件系统避坑 (核心)
这是最容易被忽视但影响最大的步骤。
### 2.1 遇到的问题
最初项目位于 Windows 的 D 盘 (`/mnt/d/...`)，执行 `uv sync` 时报错：
```text
error: Failed to install: ...
Caused by: failed to copy file ... Operation not permitted (os error 1)
```
### 2.2 原因分析
WSL2 通过 DrvFS 挂载的 Windows 分区 (`/mnt/d`) 对 Linux 的文件系统特性支持不完整：
1. **权限限制**：无法完整模拟 Linux 的文件权限位。
2. **硬链接缺失**：`uv` 默认使用硬链接来加速包安装和节省空间，跨文件系统或在不支持硬链接的挂载点上会失败。
### 2.3 解决方案：迁移项目至 Linux 文件系统
将项目移动到 WSL2 的原生文件系统（`~` 目录下），这是官方推荐的最佳实践。
**操作命令**：
```bash
# 1. 在 WSL 中创建项目目录
mkdir -p ~/projects
# 2. 拷贝项目（假设原项目在 /mnt/d/...）
cp -r /mnt/d/WILL_Moxyz/Documents/Python/ai-course-system ~/projects/
# 3. 进入新目录并清理旧的虚拟环境
cd ~/projects/ai-course-system
rm -rf .venv
# 4. 重新同步依赖
uv sync
```
> **提示**：迁移后，不仅解决了权限报错，`uv` 的安装速度和项目运行性能都会有显著提升。
---
## 3. 第二阶段：PyCharm 配置与 Git 报错
项目迁移后，需要重新配置 IDE 以识别 Linux 环境。
### 3.1 遇到的问题
PyCharm 提示：
> 无法在 WSL 中运行 Git: 不支持 WSL 版本 1...
### 3.2 原因分析
PyCharm 对 WSL 的 Git 支持依赖于 WSL 2 的内核特性。此时你的 Ubuntu 发行版运行在 WSL 1 架构上。
### 3.3 解决方案：升级至 WSL 2
**步骤一：安装 WSL2 内核更新包**
如果在转换时报错 "WSL 2 需要更新其内核组件"，需手动下载：
- 下载地址：`https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi`
- 安装完成后重启计算机。
**步骤二：启用虚拟机平台**
以**管理员身份**运行 PowerShell：
```powershell
# 启用虚拟机平台功能
Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
# 重启计算机
Restart-Computer
```
**步骤三：转换发行版**
重启后，在 PowerShell 执行：
```powershell
# 将 Ubuntu 转换为 WSL 2
wsl --set-version Ubuntu 2
# 验证版本 (VERSION 列应显示 2)
wsl -l -v
```
**步骤四：在 PyCharm 中重新配置**
1. 打开项目：`\\wsl$\Ubuntu\home\will_m\projects\ai-course-system`
2. 配置解释器：`Settings > Project > Python Interpreter > Add Interpreter > On WSL`
   - 选择 Existing environment: `/home/will_m/projects/ai-course-system/.venv/bin/python`
---
## 4. 第三阶段：CUDA 环境配置 (针对 AI 开发)
### 4.1 遇到的问题
安装带 GPU 加速的包 `minerU[all]` 时报错：
```text
FileNotFoundError: [Errno 2] No such file or directory: 'nvcc'
```
### 4.2 原因分析
你的硬件配备 **RTX 5060**，但在 WSL2 中仅安装了驱动，未安装 CUDA Toolkit 编译工具，导致无法编译需要 CUDA 支持的 Python 包（如 `flashinfer`）。
### 4.3 解决方案：安装 CUDA Toolkit
**前置检查**：
确保 Windows 上的 NVIDIA 驱动已更新到最新版本（WSL2 不需要单独安装显卡驱动，共用 Windows 驱动）。
**安装步骤**：
```bash
# 1. 移除旧的 GPG Key (如果有)
sudo apt-key del 7fa2af80
# 2. 下载 NVIDIA 官方源配置包 (适配 Ubuntu 22.04)
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
# 3. 安装源
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
# 4. 安装 CUDA Toolkit (建议 12.x 版本以适配新显卡)
sudo apt install cuda-toolkit-12-4
# 5. 配置环境变量
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
# 6. 验证安装
nvcc --version
```
**重试安装**：
```bash
uv add "minerU[all]"
```
---
## 5. 总结与最佳实践
经过以上三个阶段，你的环境已完全就绪。总结关键经验：
1.  **项目位置**：务必将项目放在 WSL2 原生文件系统 (`~/`) 下，避免直接在 `/mnt/c` 或 `/mnt/d` 下操作。
2.  **WSL 版本**：始终使用 WSL 2 以获得最佳兼容性和性能。
3.  **GPU 开发**：在 WSL2 中进行 AI 开发，除了 Windows 驱动外，还需在 Linux 内安装 `cuda-toolkit`。
4.  **UV 使用**：利用 `uv` 的速度优势，配合 WSL2 的高性能 I/O，构建极速开发体验。
```
