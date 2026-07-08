# M4A 鎵ц鎶ュ憡

鏇存柊鏃堕棿锛?026-07-08

## 淇敼鑼冨洿

| 鏂囦欢 | 绫诲瀷 | 璇存槑 |
|---|---|---|
| `pytest.ini` | pytest 閰嶇疆 | `testpaths` 浠庝笉瀛樺湪鐨?`tests` 鏀逛负 `backend/tests` |
| `backend/app/models/database.py` | 鏈€灏忚涓轰繚鎸佸瀷鍙祴璇曟€т慨鏀?| 澧炲姞 `AI_COURSE_DATABASE_URL` 娴嬭瘯瑕嗙洊锛涚敓浜ч粯璁や粛涓?`database/smart_class.db` |
| `backend/app/main.py` | 鏈€灏忚涓轰繚鎸佸瀷鍙祴璇曟€т慨鏀?| 澧炲姞 `AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS`锛涚敓浜ч粯璁や粛鎵ц渚濊禆妫€鏌ャ€佸缓琛ㄣ€佽縼绉?|
| `backend/tests/conftest.py` | 娴嬭瘯澶瑰叿 | 鏂板娴嬭瘯 DB銆乀estClient銆乼oken銆佸閮ㄧ綉缁滈樆鏂€乫ake 娉ㄥ叆鍜屽彈鎺т复鏃剁洰褰?|
| `backend/tests/fakes.py` | 娴嬭瘯 fake | 鏂板 LLM/TTS/澹伴煶澶嶅埢/PPT/鏁板瓧浜?fake |
| `backend/tests/test_m4a_isolation.py` | M4A 娴嬭瘯 | 瑕嗙洊瀹夊叏瀵煎叆銆丏B 闅旂銆佸仴搴锋鏌ャ€佺綉缁滈樆鏂€乫ake 妯″紡銆乫ixture 鍙敤鎬?|
| `backend/tests/test_m4a_route_contract.py` | M4A 娴嬭瘯 | 閿佸畾璺敱瀛楁銆乧atch-all 闈?OpenAPI 鐘舵€併€侀噸澶嶈矾鐢便€佸弻鎸傝浇鍜屽凡鐭ュ墠鍚庣璺緞宸紓 |
| `docs/phase1/娴嬭瘯鐜璁捐.md` | 鏂囨。 | 娴嬭瘯鐜璁捐璇存槑 |
| `docs/phase1/璺敱濂戠害鍩虹嚎.md` | 鏂囨。 | 璺敱濂戠害鍩虹嚎璇存槑 |
| `docs/phase1/M4A鎵ц鎶ュ憡.md` | 鏂囨。 | 鏈姤鍛?|

## 瀹為檯鎵ц鍛戒护

宸ヤ綔鐩綍鍧囦负锛?
```text
E:\smartcarb\ai-course-system
```

| 鍛戒护 | 缁撴灉 |
|---|---|
| `.venv\Scripts\python.exe -m pytest --collect-only -q` | 澶辫触锛氭牴鐩綍 `.venv` 缂哄皯 pytest锛屾姤 `No module named pytest` |
| `uv run --frozen --no-sync pytest --collect-only -q` | 澶辫触锛氭彁鏉冨悗浠嶆姤 `Failed to spawn: pytest` |
| `backend\.venv\Scripts\python.exe -m pytest --collect-only -q` | 閫氳繃锛歚147 tests collected in 0.27s` |
| `backend\.venv\Scripts\python.exe -m py_compile backend\app\main.py backend\app\models\database.py backend\tests\conftest.py backend\tests\fakes.py backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py` | 閫氳繃 |
| `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py -q` | 閫氳繃锛歚13 passed, 10 warnings in 1.11s` |

## 娴嬭瘯缁撴灉

```text
pytest collection: passed, 147 tests collected
M4A tests: passed
M4A passed: 13
M4A failed: 0
M4A skipped: 0
M4A warnings: 10
py_compile: passed
```

10 涓?warning 鍧囨潵鑷幇鏈変唬鐮佷簨瀹烇細`datetime.utcnow()` 寮冪敤鎻愮ず锛屼互鍙?FastAPI 閽堝閲嶅 Operation ID 鐨勬彁绀恒€侻4A 涓嶄慨澶嶈繖浜涢棶棰橈紝鍙妸瀹冧滑璁板綍涓哄悗缁噸鏋勯闄┿€?
## 娴嬭瘯鏁版嵁搴撹矾寰?
娴嬭瘯鐜鐢?`backend/tests/conftest.py` 璁剧疆锛?
```text
AI_COURSE_DATABASE_URL=sqlite:///E:/smartcarb/ai-course-system/.pytest_tmp/ai_course_m4a/test_smart_class.db
```

`test_engine` 鍦ㄥ惎鍔ㄥ墠鍒犻櫎娈嬬暀娴嬭瘯 DB锛屽垱寤虹嫭绔?SQLite engine锛岀粨鏉熷悗 drop tables銆乨ispose engine锛屽苟鐢?`pytest_sessionfinish` 娓呯悊娴嬭瘯鏍圭洰褰曘€?
鐢熶骇榛樿璺緞浠嶇敱 `backend/app/models/database.py` 淇濇寔涓猴細

```text
E:\smartcarb\ai-course-system\database\smart_class.db
```

## 濡備綍璇佹槑鏈闂敓浜ф暟鎹簱

宸叉墽琛屼繚鎶ゆ€ф祴璇曪細

- `backend/tests/test_m4a_isolation.py::test_app_uses_test_database_and_never_production_database`
- `backend/tests/test_m4a_isolation.py::test_temporary_database_can_create_models`

鏂█璇佹嵁锛?
- `database.DATABASE_URL == os.environ["AI_COURSE_DATABASE_URL"]`
- `database.DATABASE_URL != database.DEFAULT_DATABASE_URL`
- `database.PRODUCTION_DATABASE_PATH` 涓嶅嚭鐜板湪娴嬭瘯 URL 涓?- 瀹為檯寤烘ā鍐欏叆鍙戠敓鍦?`test_smart_class.db`

## 濡備綍璇佹槑鏈皟鐢ㄧ湡瀹炲閮ㄦ湇鍔?
宸叉墽琛屼繚鎶ゆ€ф祴璇曪細

- `backend/tests/test_m4a_isolation.py::test_unmocked_external_network_call_is_blocked`
- `backend/tests/test_m4a_isolation.py::test_common_fakes_support_success_timeout_unavailable_and_malformed_modes`

澶瑰叿璇佹嵁锛?
- `block_external_network` autouse fixture 闃绘柇闈?loopback socket
- `install_external_fakes` autouse fixture patch 宸茬煡 LLM銆乀TS銆佸０闊冲鍒汇€丳PT銆佹暟瀛椾汉瀹㈡埛绔紩鐢?- `FakeLLMClient`銆乣FakeTTSClient`銆乣FakeVoiceCloneClient`銆乣FakePPTClient`銆乣FakeDigitalHumanClient`銆乣FakeHTTPXClient` 瑕嗙洊 `success`銆乣timeout`銆乣service_unavailable`銆乣malformed`/`malformed_response`銆乣business_failure`
- 娴嬭瘯鐜鏄惧紡娓呯┖ `LLM_API_KEY`銆乣DOUBAO_API_KEY`銆乣QWEN_API_KEY`銆乣WENXIN_API_KEY`銆乣OPENAI_API_KEY` 绛夊閮ㄦ湇鍔″瘑閽ュ彉閲?
## 鏄惁淇敼涓氬姟浠ｇ爜

鏄紝淇敼浜嗕袱澶勬渶灏忚涓轰繚鎸佸瀷鍙祴璇曟€т唬鐮侊細

1. `backend/app/models/database.py`
2. `backend/app/main.py`

鍘熷洜锛歁0-M3 宸茬‘璁?`app.main` 瀵煎叆鏈熷瓨鍦ㄤ緷璧栨鏌ヨ嚜鍔ㄥ畨瑁呫€佸缓琛ㄥ拰杩佺Щ鍓綔鐢紝涓旀暟鎹簱 URL 鍥哄畾鎸囧悜鐢熶骇 SQLite銆備粎闈?fixture/monkeypatch 鏃犳硶鍦ㄦā鍧楀鍏ュ墠鍙潬鏇挎崲杩欎簺琛屼负锛屽洜姝ゅ鍔犳祴璇曠幆澧冨彉閲忓紑鍏炽€?
鐢熶骇榛樿琛屼负淇濇寔涓嶅彉锛?
- 鏈缃?`AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS` 鏃讹紝浠嶆墽琛屼緷璧栨鏌ャ€佸缓琛ㄥ拰杩佺Щ銆?- 鏈缃?`AI_COURSE_DATABASE_URL` 鏃讹紝浠嶄娇鐢?`database/smart_class.db`銆?- 鏈敼鍙樺叕寮€ API銆佹暟鎹簱鐢熶骇缁撴瀯銆佸惎鍔ㄥ懡浠ゆ垨鐢ㄦ埛鍙琛屼负銆?

## M4B 鍓嶇疆琛ュ厖锛歜usiness_failure fake 鑳藉姏

2026-07-08 琛ュ厖 `backend/tests/fakes.py` 鐨?`business_failure` 妯″紡锛屼粎淇敼娴嬭瘯 fake 涓庢祴璇曟枃妗ｏ紝涓嶄慨鏀?endpoint銆乻ervice銆乵odel 鎴栫敓浜т唬鐮併€?
`business_failure` 琛ㄧず澶栭儴鏈嶅姟璇锋眰鏈韩瀹屾垚锛屽苟杩斿洖缁撴瀯鍖栧搷搴旓紝浣嗕笟鍔¤涔夊け璐ワ紱瀹冧笉閫氳繃缃戠粶寮傚父妯℃嫙锛屼篃涓嶉€氳繃 malformed response 妯℃嫙銆傚綋鍓嶈鐩栵細

- LLM锛氳繑鍥?`LLMResponse`锛屼絾 `content` 涓虹┖涓?`finish_reason="business_failure"`锛沗simple_chat` 杩斿洖鍙В鏋?JSON 涓?`status="failed"`銆?- TTS锛氳繑鍥炵粨鏋勫寲 dict锛宍status="failed"`銆乣code="TTS_SYNTHESIS_FAILED"`銆乣audio_data` 涓虹┖銆?- PPT锛歚create_ppt_task` 杩斿洖鎴愬姛 `sid`锛屼絾 `wait_for_completion` 杩斿洖 `PPTTaskResult(status="failed")`锛宍get_task_progress` 杩斿洖 `pptStatus="failed"`銆?- Digital human锛氬仴搴锋鏌ユ垚鍔燂紝浣?`generate_video` 杩斿洖绌?`video_path`锛屽苟甯?`status="failed"` 涓庨敊璇俊鎭€?- Voice clone锛氳繑鍥炵粨鏋勫寲缁撴灉锛屼絾 `clone_status="failed"`銆?- HTTPX锛氳繑鍥?HTTP 200锛屼絾 JSON 涓氬姟 `code` 闈?0 涓?`status="failed"`锛岀敤浜庢硾闆?杩滅▼ httpx 绫昏矾寰勫悗缁祴璇曘€?
鏂板 fake 鑷祴锛?
```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4b_fakes.py -q
6 passed in 0.49s
```

鍥炲綊楠岃瘉锛?
```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py -q
13 passed, 10 warnings in 1.50s
```

闄愬埗锛氭湰娆″彧琛ラ綈 M4B 鍓嶇疆娴嬭瘯鑳藉姏锛屽皻鏈獙璇佸悇 endpoint/service 瀵逛笟鍔″け璐ョ殑鐪熷疄澶勭悊鏄惁瀹屾暣銆傚悗缁?M4B 涓氬姟鍐掔儫娴嬭瘯鑻ュ彂鐜扮姸鎬佹湭钀藉簱銆侀敊璇俊鎭湭璁板綍鎴栦笟鍔＄姸鎬佹湭鏆撮湶锛屽簲璁板綍涓衡€滃凡纭涓氬姟缂洪櫡鈥濇垨鎺ㄨ繜鍒?M6/M7 澶勭悊锛屼笉鍦ㄦ祴璇曞熀绾块樁娈甸『鎵嬩慨涓氬姟鍔熻兘銆?## 鍥炴粴鏂规硶

鍥炴粴 M4A 鍙垹闄ゆ柊澧炴祴璇曞拰鏂囨。锛屽苟杩樺師涓夊閰嶇疆/鏈€灏忎唬鐮佷慨鏀癸細

1. 鍒犻櫎锛?   - `backend/tests/conftest.py`
   - `backend/tests/fakes.py`
   - `backend/tests/test_m4a_isolation.py`
   - `backend/tests/test_m4a_route_contract.py`
   - `docs/phase1/娴嬭瘯鐜璁捐.md`
   - `docs/phase1/璺敱濂戠害鍩虹嚎.md`
   - `docs/phase1/M4A鎵ц鎶ュ憡.md`
2. 杩樺師锛?   - `pytest.ini` 鐨?`testpaths = tests`
   - `backend/app/models/database.py` 鐨勫浐瀹?`DATABASE_URL`
   - `backend/app/main.py` 鐨勫鍏ユ湡鍚姩鍓綔鐢ㄥ師鍐欐硶

## 涓嬩竴姝ュ缓璁?
M4B 搴斾粠鍏抽敭涓氬姟鍐掔儫娴嬭瘯寮€濮嬶紝鍙褰曠湡瀹炲け璐ワ紝涓嶅垹闄ゃ€佷笉 skip銆佷笉 xfail 鏃㈡湁娴嬭瘯锛涗紭鍏堣鐩栫櫥褰曘€佽绋?鏂囨。銆佸鐢熼€夎銆佹挱鏀俱€侀棶绛斻€佽繘搴︺€丳PT/TTS/鏁板瓧浜?Mock 娴佺▼銆
## M4B 前置复核：business_failure fake 能力（2026-07-08）

本次仅修改测试 fake 与 fake 自测，未修改 endpoint、service、model 或生产代码。

已在 `backend/tests/fakes.py` 为以下外部服务 fake 确认 `business_failure` 模式：

- LLM：返回可解析/结构化结果，但内容为空或业务状态失败。
- TTS：返回结构化结果，但 `status="failed"`、`code="TTS_SYNTHESIS_FAILED"`，且音频为空。
- PPT：任务创建返回 `sid`，后续任务状态返回 `failed`。
- 数字人：健康检查成功，视频生成返回 `status="failed"` 且 `video_path` 为空。
- 声音复刻：返回结构化结果，但 `clone_status="failed"`。
- HTTPX/泛雅类远程调用：HTTP 200，但业务 `code` 非 0 且 `status="failed"`。

验证命令：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4a_isolation.py backend\tests\test_m4a_route_contract.py -q
13 passed, 10 warnings in 1.14s

backend\.venv\Scripts\python.exe -m pytest backend\tests\test_m4b_fakes.py -q
6 passed in 0.14s
```

限制：本次只补齐 M4B 前置 fake 能力和 fake 自测；尚未证明各业务 endpoint/service 均已完整处理业务失败。若后续 M4B 主流程测试发现错误状态、错误信息或业务状态未正确记录，应记录为“已确认业务缺陷”或“待 M6/M7 处理”，不在测试基线阶段顺手补业务功能。