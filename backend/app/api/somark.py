from fastapi import APIRouter, UploadFile, File
import requests

router = APIRouter()

SOMARK_API_KEY = "sk-Ah-CISudxWZzbqVOVHKVhaCqexgYOrEpXekaDW0r8A4"
SOMARK_URL = "https://somark.tech/api/v1/extract/acc_sync"

@router.post("/api/somark/parse")
async def parse_file(file: UploadFile = File(...)):
    try:
        file_content = await file.read()

        resp = requests.post(
            SOMARK_URL,
            files={"file": (file.filename, file_content, file.content_type)},
            data={
                "output_formats": ["json"],
                "api_key": SOMARK_API_KEY
            },
            timeout=30
        )

        data = resp.json()

        # ==============================
        # ✅ 完全按照你后台的结构来取！
        # ==============================
        pages = []
        result = data.get("data", {}).get("result", {})
        raw_pages = result.get("outputs", {}).get("json", {}).get("pages", [])

        for page in raw_pages:
            content = ""
            for block in page.get("blocks", []):
                content += block.get("content", "") + "\n\n"

            pages.append({
                "title": f"第{page['page_num']+1}页",
                "content": content.strip()
            })

        return {"pages": pages}

    except Exception as e:
        print("错误：", e)
        return {"pages": []}