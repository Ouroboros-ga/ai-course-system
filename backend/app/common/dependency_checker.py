import importlib
import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

PYTHON_DEPENDENCIES = [
    {"package": "fastapi", "import_name": "fastapi", "required": True},
    {"package": "sqlmodel", "import_name": "sqlmodel", "required": True},
    {"package": "pydantic-settings", "import_name": "pydantic_settings", "required": True},
    {"package": "python-dotenv", "import_name": "dotenv", "required": True},
    {"package": "python-jose", "import_name": "jose", "required": True},
    {"package": "python-multipart", "import_name": "multipart", "required": True},
    {"package": "uvicorn", "import_name": "uvicorn", "required": True},
    {"package": "httpx", "import_name": "httpx", "required": True},
    {"package": "bcrypt", "import_name": "bcrypt", "required": True},
    {"package": "pillow", "import_name": "PIL", "required": True},
    {"package": "pymupdf", "import_name": "fitz", "required": True},
    {"package": "docling", "import_name": "docling", "required": True},
    {"package": "transformers", "import_name": "transformers", "required": True},
    {"package": "onnxruntime", "import_name": "onnxruntime", "required": True},
    {"package": "pdfplumber", "import_name": "pdfplumber", "required": False},
    {"package": "python-docx", "import_name": "docx", "required": False},
    {"package": "python-pptx", "import_name": "pptx", "required": False},
]

EXTERNAL_TOOLS = [
    {
        "name": "LibreOffice",
        "purpose": "Office文档(PPTX/PPT/DOCX/DOC/XLS/XLSX)转PDF",
        "check_command": None,
        "paths": [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            "/usr/bin/libreoffice",
            "/usr/bin/soffice",
            "/usr/local/bin/libreoffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ],
        "env_var": "LIBREOFFICE_PATH",
        "install_hint_windows": "下载安装: https://www.libreoffice.org/download/ 或 winget install TheDocumentFoundation.LibreOffice",
        "install_hint_linux": "sudo apt install libreoffice (Ubuntu/Debian) 或 sudo yum install libreoffice (CentOS/RHEL)",
        "install_hint_mac": "brew install --cask libreoffice",
    },
    {
        "name": "FFmpeg/FFprobe",
        "purpose": "音频时长精确计算、视频处理",
        "check_command": ["ffprobe", "-version"],
        "paths": [],
        "env_var": None,
        "install_hint_windows": "下载安装: https://ffmpeg.org/download.html 或 winget install Gyan.FFmpeg",
        "install_hint_linux": "sudo apt install ffmpeg (Ubuntu/Debian) 或 sudo yum install ffmpeg (CentOS/RHEL)",
        "install_hint_mac": "brew install ffmpeg",
    },
]


def check_python_package(import_name: str) -> bool:
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def install_python_package(package: str) -> bool:
    try:
        logger.info(f"Installing Python package: {package}")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info(f"Successfully installed: {package}")
            return True
        else:
            logger.error(f"Failed to install {package}: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error installing {package}: {e}")
        return False


def check_external_tool(tool_info: dict) -> dict:
    result = {
        "name": tool_info["name"],
        "purpose": tool_info["purpose"],
        "found": False,
        "path": None,
    }

    env_path = os.environ.get(tool_info.get("env_var", ""))
    if env_path and os.path.exists(env_path):
        result["found"] = True
        result["path"] = env_path
        return result

    for path in tool_info.get("paths", []):
        if os.path.exists(path):
            result["found"] = True
            result["path"] = path
            return result

    if tool_info.get("check_command"):
        cmd = tool_info["check_command"]
        if shutil.which(cmd[0]):
            result["found"] = True
            result["path"] = shutil.which(cmd[0])
            return result

    return result


def run_dependency_check(auto_install: bool = True) -> dict:
    logger.info("=" * 60)
    logger.info("AI智课系统 - 依赖检查")
    logger.info("=" * 60)

    report = {
        "python_ok": True,
        "python_missing": [],
        "python_installed": [],
        "external_tools": [],
    }

    for dep in PYTHON_DEPENDENCIES:
        if check_python_package(dep["import_name"]):
            logger.info(f"  [OK] {dep['package']} ({dep['import_name']})")
        else:
            logger.warning(f"  [MISSING] {dep['package']} ({dep['import_name']})")
            if auto_install:
                if install_python_package(dep["package"]):
                    if check_python_package(dep["import_name"]):
                        report["python_installed"].append(dep["package"])
                        logger.info(f"  [INSTALLED] {dep['package']}")
                    else:
                        report["python_missing"].append(dep["package"])
                        if dep["required"]:
                            report["python_ok"] = False
                        logger.error(f"  [FAILED] {dep['package']} installed but still cannot import")
                else:
                    report["python_missing"].append(dep["package"])
                    if dep["required"]:
                        report["python_ok"] = False
            else:
                report["python_missing"].append(dep["package"])
                if dep["required"]:
                    report["python_ok"] = False

    logger.info("")
    logger.info("外部工具检查:")
    for tool in EXTERNAL_TOOLS:
        check_result = check_external_tool(tool)
        report["external_tools"].append(check_result)
        if check_result["found"]:
            logger.info(f"  [OK] {check_result['name']}: {check_result['path']}")
        else:
            platform = "windows" if os.name == "nt" else "linux"
            hint_key = f"install_hint_{platform}"
            hint = tool.get(hint_key, tool.get("install_hint_linux", ""))
            logger.warning(f"  [MISSING] {check_result['name']} - {check_result['purpose']}")
            logger.warning(f"    安装方式: {hint}")

    logger.info("")
    logger.info("=" * 60)
    if report["python_ok"]:
        logger.info("Python依赖检查通过")
    else:
        logger.error("Python依赖检查失败，部分必需包缺失")

    missing_tools = [t for t in report["external_tools"] if not t["found"]]
    if missing_tools:
        logger.warning(f"外部工具缺失: {', '.join(t['name'] for t in missing_tools)}")
        logger.warning("部分功能可能受限，请参考上方安装方式手动安装")
    else:
        logger.info("外部工具检查通过")

    logger.info("=" * 60)

    return report
