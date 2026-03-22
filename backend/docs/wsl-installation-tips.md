> 这是一份基于实际操作经历的 WSL Ubuntu 22.04 安装总结文档。你可以将其保存为 `.md` 文件，或者分享给遇到类似问题的朋友。

---
# WSL Ubuntu 22.04 安装踩坑实录 (Windows 10)
## 1. 硬件与环境背景
*   **系统版本**: Windows 10 19044.7058 (21H2)
*   **硬件配置**:
    *   CPU: AMD Ryzen 5 5600
    *   RAM: 32GB DDR4 3600
    *   GPU: NVIDIA RTX 5060 (8GB VRAM)
    *   Storage: 1TB PCIe 4.0 NVMe SSD
*   **目标**: 在 WSL2 中运行 Ubuntu 22.04，用于部署本地 LLM。
---
## 2. 第一阶段：常规安装失败
### 尝试命令
按照常规教程，在管理员 PowerShell 中执行：
```powershell
wsl --install -d Ubuntu-22.04
```
### 遇到问题
**错误代码 `0x80072ee2`**。
*   **原因**: 网络连接问题，DNS 解析异常，无法连接到 Microsoft Store 服务器。
*   **结论**: 常规在线安装路线在此网络环境下走不通。
---
## 3. 第二阶段：手动下载与“隐形”安装
### 解决方案：绕过 Store 下载
使用 `Invoke-WebRequest` 直接下载 Ubuntu 22.04 的 AppX 包。
**执行命令**：
```powershell
Invoke-WebRequest -Uri https://aka.ms/wslubuntu2204 -OutFile Ubuntu2204.appx -UseBasicParsing
```
*   **结果**: 成功下载 `Ubuntu2204.appx` 文件。
### 安装过程
执行安装命令：
```powershell
Add-AppxPackage .\Ubuntu2204.appx
```
*   **现象**: 命令执行完毕，**没有任何报错，也没有任何提示**。
*   **疑惑**: 执行 `wsl -l -v` 依然提示“适用于 Linux 的 Windows 子系统没有已安装的分发版”。
### 排查过程
使用 `Get-AppxPackage` 检查系统是否真的装了这个包：
```powershell
Get-AppxPackage *Ubuntu*
```
*   **发现**: 系统确实安装了 `CanonicalGroupLimited.Ubuntu_2204.1.7.0_x64__79rhkp1fndgsc`。
*   **原因分析**: AppX 包虽然“安装”了，但处于未初始化状态。它只是作为一个应用存在于系统中，还没有在 WSL 子系统中注册为“发行版”。
---
## 4. 第三阶段：初始化与配置
### 触发初始化
在开始菜单找到 **"Ubuntu 22.04"** 图标并点击启动。
*   **现象**: 弹出终端窗口，显示 `Installing, this may take a few minutes...`，开始解压文件系统。
### 最终障碍：用户名设置
初始化完成后，提示创建 UNIX 用户名。
**错误提示**：
```text
adduser: Please enter a username matching the regular expression configured
via the NAME_REGEX[_SYSTEM] configuration variable.  Use the `--force-badname'
option to relax this check or reconfigure NAME_REGEX.
```
*   **原因**: 输入了包含大写字母的用户名（如 Windows 用户名 `WILL_Moxyz`），不符合 Linux 用户名必须小写的规范。
*   **解决**: 重新输入全小写用户名（例如 `will` 或 `user`），随后设置密码。
### 结果
成功进入 Ubuntu 终端，`wsl -l -v` 终于显示正常：
```text
NAME            STATE           VERSION
Ubuntu-22.04    Running         2
```
---
## 5. 核心经验总结
1.  **网络错误 (0x80072ee2) 是常见门槛**：
    *   如果 `wsl --install` 失败，不要死磕网络设置，直接切换到手动下载 `.appx` 模式是最高效的方案。
2.  **`Add-AppxPackage` 成功不等于 WSL 安装成功**：
    *   这是最容易踩的坑。PowerShell 不报错仅代表“应用包安装成功”，不代表“WSL 发行版已就绪”。
    *   **必做步骤**：必须手动在开始菜单点击图标，或运行安装目录下的 `ubuntu.exe`，完成第一次初始化（解压 rootfs、创建用户），WSL 才会识别它。
3.  **Linux 用户名严格区分大小写**：
    *   WSL 初始化时的用户名必须符合 `NAME_REGEX`：**全小写、字母开头、可包含数字和下划线**。不要照搬 Windows 的大小写混写用户名。
---
## 6. 附录：成功后的检查清单
安装完成后，建议执行以下检查，确保环境就绪：
- [ ] **检查 WSL 版本**：确保是 WSL2（性能更好）。
    ```powershell
    wsl -l -v
    ```
- [ ] **更新软件源**：
    ```bash
    sudo apt update && sudo apt upgrade -y
    ```
- [ ] **检查 GPU 支持**（如需跑 LLM）：
    ```bash
    nvidia-smi
    ```
    *如果能显示显卡信息，说明 CUDA on WSL 环境已就绪。*
---
## 7. 设置虚拟机内存
通过 `Win + R` 运行 `%UserProfile%`
新建或修改文件 `.wslconfig`
```ini
[wsl2]
# 限制 WSL2 最大使用内存为 16GB (可以根据需要调整
memory=16GB
# 限制处理器使用数量 (可选，你的 5600 是 6 核 12 线程，可以设为 4 或 6)
processors=6
# 开启自动释放内存 (需要 WSL 版本支持)
autoMemoryReclaim=gradual 
```
