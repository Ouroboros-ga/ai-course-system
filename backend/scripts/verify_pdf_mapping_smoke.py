"""Re-check PDF mapping workspace rendering after the parse pipeline settled."""
import json
import os
import sys

import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
COURSE_ID = 1


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=120) as client:
        login = client.post("/api/v1/user/login", json={"username": "TTT", "password": "123456"})
        token = login.json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}
        state = client.get(f"/api/v1/course-editor/course/{COURSE_ID}/ppt-mapping", headers=headers)
        materials = state.json()["data"]["ppt_materials"]
        pdf = next((item for item in materials if item["name"].endswith(".pdf")), None)
        if pdf is None:
            print("NO_PDF_MATERIAL_FOUND")
            return 1
        version_id = pdf["material_version_id"]
        ws = client.get(
            f"/api/v1/course-editor/course/{COURSE_ID}/ppt-mapping/workspace",
            params={"material_version_id": version_id, "page_start": 1, "page_size": 12},
            headers=headers,
        )
        payload = ws.json()["data"]
        print("WORKSPACE", json.dumps({
            "page_count": payload.get("page_count"),
            "render_warning": payload.get("render_warning"),
            "message": payload.get("message"),
        }, ensure_ascii=False))
        for page in payload.get("pages", []):
            print("PAGE", json.dumps({
                "page": page.get("page"),
                "image_url": bool(page.get("image_url")),
                "image_source": page.get("image_source"),
                "ocr_available": page.get("ocr_available"),
            }, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
