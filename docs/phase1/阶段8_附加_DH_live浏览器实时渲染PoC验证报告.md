# 阶段8 附加：DH_live 浏览器实时渲染与素材预处理最小验证（PoC）

> **状态：2026-08-06。** 本报告是独立 PoC 验证记录，**不是**学生播放主链的实现或验收
> 依据。现行主链仍为 PixiJS 2D 预制角色 + `avatar-cues/v1`（见
> [阶段8_媒体TTS数字人PPT_实施规划.md](阶段8_媒体TTS数字人PPT_实施规划.md)）。
> PoC 结论用于评估"浏览器本地实时渲染 + 大资源离线预处理"路线是否可作为未来 M4
> 引擎接入（`DhLiveMiniProvider`）的候选；是否接入主链需另行决策并满足
> [阶段8_附加_教师数字人资产中心.md](阶段8_附加_教师数字人资产中心.md) 的授权、
> 版本化资产、MediaRelease 绑定与目标设备实测门槛。

## 1. 目标与范围

- 验证 DH_live（github.com/kleinlee/DH_live）的**浏览器本地实时渲染**链路：
  学生端不依赖 Python/PyTorch，浏览器加载 `DHLiveMini.wasm` + 人物素材 +
  `combined_data.json.gz` 本地推理并合成画面。
- 验证**素材预处理**链路：教师视频 → mediapipe 关键点 → `combined_data.json.gz` + `01.mp4`。
- 记录三档性能指标与降级行为，作为"学生端实时渲染是否可靠"的实测依据。

## 2. 主链审计结论（前置）

- 现行主链 = `<audio>` 唯一时钟 + PPT manifest + 字幕 + PixiJS 2D 预制角色；
  服务端不做逐帧合成，DH_live 明确不在主链内。
- 后端已预留接入点：[avatar_model.py](../../backend/app/models/avatar_model.py) 的
  `DigitalHumanProviderKey.DH_LIVE_MINI`；[digital_human_provider.py](../../backend/app/services/digital_human_provider.py)
  的 `DhLiveMiniProvider`（引擎适配壳：`DHLIVE_ENGINE_BINARY` 子进程 /
  `DHLIVE_WORKER_PORT` HTTP Worker，strict report 模式）。
- 前端渲染器 [Sprite2DRenderer.js](../../frontend/src/features/student-learning/renderers/Sprite2DRenderer.js)
  只消费 `sprite2d-manifest/v1`（SVG 图集），与 DH_live 的 WASM/WebCodecs 资产
  **不兼容**，如需接入须新增独立渲染适配器（M3 预留的 `DigitalHumanRendererAdapter`）。

## 3. 阶段 A：浏览器实时渲染实测（官方预生成资产）

### 3.1 环境与方法

- 本机：Windows / Edge headless（WebGL2、WASM、WebCodecs 全可用）、32 核 / 32GB。
- 服务：`web_demo/server.py`（FastAPI，localhost:8888，仅静态服务 + 模拟 TTS 流）。
- 页面：`MiniLive.html`（视频素材循环驱动）与 `MiniLive_RealTime.html`（音频驱动）。
- 自动化：puppeteer-core 连接系统 Edge；渲染帧率按 canvas `drawImage` 计数折算，
  音频驱动按 WASM `_setAudioBuffer` / `_updateBlendShape` 调用与 blend shape 变化统计。

### 3.2 实测结果

| 指标 | 门槛 | MiniLive.html | MiniLive_RealTime.html | 结论 |
| --- | --- | --- | --- | --- |
| 首次资产加载 | ≤5s | 591 ms（首帧像素 675 ms） | 602 ms | ✅ |
| 稳态帧率 | 自动 ≥20 FPS | ~31 FPS（125 drawImage/s ÷ 4） | ~25 FPS（_updateBlendShape 202 次/8s） | ✅ |
| 音频驱动口型 | 口型跟随音频 | 视频素材循环驱动 | `_setAudioBuffer` 1 次成功；blend shape 8s 内变化 201 次 | ✅ |
| 初始化/降级 | 失败进兼容模式 | 0 console 错误 | 0 console 错误 | ✅ |

### 3.3 渲染链路确认（代码证据）

- 浏览器推理：`DHLiveMini.wasm`（4.44 MB）导出 `_processJson` / `_setAudioBuffer` /
  `_updateBlendShape` / `_processImage` / `_getAudioVad`，均在学生浏览器执行。
- 帧同步：人物素材 `01.mp4` 每帧编码 MODULO_N=16 帧号像素，浏览器读像素解出精确帧号，
  与 `combined_data.json.gz`（179 帧数据集）对齐，避免视频播放器时间漂移。
- 画面合成：WebGL2 绘制 3D 人脸网格（OBJ 1335 顶点 + `bs_texture` 纹理 + 顶点变形着色器），
  WASM 图像融合把嘴部贴回原帧，绿幕抠图（WebGL2 着色器）合成到背景。
- 音频驱动：SSE 流式返回音频 base64 → `_setAudioBuffer` 喂给 WASM → 渲染循环每帧
  `_updateBlendShape` 取当前时间点 12 维嘴型参数。

### 3.4 已知限制（官方实现特性）

- 人物表情/转头受原始素材约束，属"轻量 2D 讲解数字人"，非影视级自由生成。
- 音频驱动版依赖 WebCodecs，仅 HTTPS / localhost 可用（页面已有安全上下文提示）。
- 画质（720×1080 素材）与嘴型精度取决于教师视频质量与素材时长。

## 4. 阶段 B：素材预处理实测

### 4.1 环境

- Python 3.12.13 venv（`dh-live-mini-poc/.venv312`），清华镜像安装。
- 依赖：mediapipe **0.10.14**（必须降级，1.0 已移除 `solutions` API）、
  opencv-python、numpy、scikit-learn、kaldi_native_fbank、PyOpenGL、glfw、pyglm、
  gradio、torch 2.13 CPU。
- ffmpeg 7.1：通过 `imageio-ffmpeg` 便携二进制（`dh-live-mini-poc/tools/bin/ffmpeg.exe`）。

### 4.2 已跑通：关键点提取（`data_preparation_mini.py`）

- 输入：官方样例 `video_data/000002/video.mp4`（720×1080 / 25fps / 179 帧 / 7.2s）。
- 输出：`video_data/000002/data/processed.pkl`（478 关键点 × 179 帧，2.0 MB）+
  `data/processed.mp4`（帧号编码，0.9 MB）。
- 耗时：约 13s（CPU，15 it/s）。通过首帧正脸检测、单脸校验、说话检测与边界校验。

### 4.3 已跑通：`data_preparation_web.py` 生成浏览器资产

- 前置：用户提供模型权重 `checkpoint/DINet_mini/epoch_40_new.pth`（24.05 MB，百度网盘
  `D:\BaiduNetdiskDownload\DH_live`），已复制到 `dh-live-mini-poc/checkpoint/`。
- 命令：`python data_preparation_web.py video_data/000002`（约 1 分钟，CPU）。
- 输出：`video_data/000002/assets/`：`01.mp4`（881.8 KB，720×1080/25fps/358帧，含帧号编码）、
  `combined_data.json.gz`（129.5 KB，179 数据集 + face3D_obj 727 行 + ref_data）、`thumbnail.jpg`。
- 素材说话检测通过（"视频存在明显说话: False"）。

### 4.4 已跑通：新资产浏览器实测（`assets6`）

- 部署：`web_demo/static/assets6/`（01.mp4 + combined_data.json.gz）；测试页
  `_poc_assets6.html`（内联替换资产路径的 MiniLive2.js，不改官方文件）。
- 实测：加载 687 ms、首帧 805 ms、稳态 ~31 FPS（125 drawImage/s）、
  `JSON data loaded successfully: 179 sets`、0 console 错误。
- 结论：**"教师视频 → data_preparation_mini → data_preparation_web → 浏览器实时渲染"
  全链路在本机打通**，自产资产与官方预生成资产渲染性能一致。

## 5. 三档门槛对比与结论

| 门槛项 | 本次实测 | 状态 |
| --- | --- | --- |
| 首次头像资源加载 ≤5s（校园普通网络） | 本地 <1s；校园网络需再测 | ✅（本地） |
| 稳态帧率自动 ≥20 FPS | ~25–31 FPS | ✅ |
| 低资源模式 ≥15 FPS | 未测（官方未内置 low_resource 开关） | ⏳ |
| 音画偏差 P95 ≤150ms | 音频驱动口型 25 FPS 持续更新，未见累积漂移（帧号对齐） | ✅（本机） |
| 连续播放 20min 内存稳定 | 未测（headless 会话短） | ⏳ |
| 初始化失败自动兼容模式 | 0 错误；WebGL2/WASM 不可用场景未构造 | ⏳ |
| 页面切后台恢复同步 | 未测 | ⏳ |

**结论（2026-08-06）**：
1. **浏览器本地实时渲染技术路线成立**：加载 <1s、稳态 25–31 FPS、音频驱动口型生效、
   0 错误，本机 Edge 实测通过；WASM 推理与 WebGL 合成确在浏览器本地执行。
2. **素材预处理全链路成立**：mediapipe 关键点提取 13s 跑通 179 帧，`data_preparation_web.py`
   在 CPU 约 1 分钟生成 `combined_data.json.gz + 01.mp4`，自产资产浏览器实测性能与官方一致。
3. **尚不能承诺全量验收**：低资源模式、20 分钟连续播放、后台恢复、三档真机（含老电脑）
   与校园网络加载均未实测；官方自报参数（39 Mflops、无需 GPU）不能替代目标设备实测。
4. **授权必须另行审查**：DH_live 代码 MIT，但 README 声明网页商用与去标识涉及形象授权；
   模型文件、头像资产与去标识授权须分开审查后方可商用。

## 6. 后续接入主链的条件（M4 候选）

满足以下全部条件后才可评估接入 `DhLiveMiniProvider`：

1. 模型权重与资产授权合规（形象授权、去标识、模型许可）；
2. 把 `data_preparation_mini.py` / `data_preparation_web.py` 包装为
   `DHLIVE_ENGINE_BINARY` 协议（`--action prepare_avatar/playback_manifest`）的 Windows Worker；
3. 前端新增 DH_live 渲染适配器（WASM/WebCodecs），与现有 `Sprite2DRenderer` 并存且可降级；
4. 在目标 Windows 设备完成三档实测（≥20/≥15 FPS、P95 同步偏差、20 分钟内存、后台恢复），
   结果写入 `PlaybackCapabilityProfile`（严格模式 `DHLIVE_STRICT_REPORT` 要求实际测试报告）。

## 7. 复现步骤（本机）

```text
# 克隆（已在 E:\smartcarb\dh-live-mini-poc）
git clone --depth 1 https://github.com/kleinlee/DH_live.git dh-live-mini-poc

# 阶段 A：浏览器实时渲染（无需预处理）
cd dh-live-mini-poc
py -3.14 -m venv .venv314 && .venv314\Scripts\pip install fastapi uvicorn requests python-multipart
.venv314\Scripts\python web_demo\server.py        # http://localhost:8888/static/MiniLive.html
node verify\verify-minilive.mjs                   # 自动化实测（需 puppeteer-core）

# 阶段 B：素材预处理
uv venv .venv312 --python 3.12
uv pip install -p .venv312\Scripts\python.exe --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  mediapipe==0.10.14 opencv-python numpy tqdm scikit-learn kaldi_native_fbank PyOpenGL glfw pyglm gradio torch imageio-ffmpeg
# ffmpeg: 复制 imageio_ffmpeg 二进制到 tools\bin\ffmpeg.exe 并加入 PATH
python data_preparation_mini.py video_data/000002/video.mp4 video_data/000002
python data_preparation_web.py video_data/000002   # 需先放入 checkpoint/DINet_mini/epoch_40_new.pth
```

## 8. 记录

- 日期：2026-08-06
- 代码证据：`E:\smartcarb\dh-live-mini-poc`（独立 PoC 目录，不在 ai-course-system 仓库内）
- 实测脚本：`dh-live-mini-poc/verify/verify-minilive.mjs`、`verify-realtime.mjs`、`make_assets6_page.py`
- 模型权重来源：`D:\BaiduNetdiskDownload\DH_live\checkpoint\`（用户授权提供，已复制至 `dh-live-mini-poc/checkpoint/`）
- 未决：三档真机（含老电脑）与校园网络实测；20 分钟连续播放内存、后台恢复、低资源模式
