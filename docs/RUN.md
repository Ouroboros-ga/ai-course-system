# 后端 BACKEND
```bash
cd ..
cd ./backend/
uv run python -m uvicorn app.main:app --reload --host  0.0.0.0  --port 8000
```

# 前端 FRONTEND
```sh
cd ..
cd ./frontend/
npm run dev
```

Press Key `o` on your keyboard.
or
visit [here](http://localhost:5173)

# ABOUT
- API 服务: http://localhost:8001
- API 文档: http://localhost:8001/docs

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")