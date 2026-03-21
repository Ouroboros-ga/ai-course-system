from fastapi import APIRouter, UploadFile, File
import requests

router = APIRouter()

# 你的 KEY
SOMARK_API_KEY = "sk-Ah-CISudxWZzbqVOVHKVhaCqexgYOrEpXekaDW0r8A4"
SOMARK_URL = "https://somark.tech/api/v1/extract/acc_sync"  # 官方正确地址


@router.post("/api/somark/parse")
async def parse_file(file: UploadFile = File(...)):
    try:
        # 读取文件
        file_content = await file.read()

        # ✅ 正确的请求格式（只写一次！）
        resp = requests.post(
            SOMARK_URL,
            files={"file": (file.filename, file_content, file.content_type)},
            data={
                "output_formats": ["markdown", "json"],
                "api_key": SOMARK_API_KEY
            }
        )

        # 打印日志
        print("SoMark 返回状态码:", resp.status_code)
        print("SoMark 返回内容:", resp.text)

        return resp.json()

    except Exception as e:
        print("SoMark 调用失败:", str(e))
        return {"pages": []}