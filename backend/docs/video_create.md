视频生成模块API 调用文档
基础信息
项目	说明	
服务地址	http://localhost:7860/	
客户端库	gradio_client	
安装命令	pip install gradio_client	
一、快速开始
from gradio_client import Client, handle_file
client = Client("http://localhost:7860/")
⚠️ 所有接口均基于上述 client 实例调用，后续示例中省略重复的初始化代码。
二、公共文件参数说明
handle_file() 用于构造上传文件对象，返回结构如下：
{
  "path": "str",          // 服务器端文件存储路径
  "url": "str | None",    // 文件访问 URL
  "size": "int | None",   // 文件大小（字节）
  "orig_name": "str | None",  // 原始文件名
  "mime_type": "str | None",  // MIME 类型
  "is_stream": "bool",    // 是否为流
  "meta": {
    "_type": "gradio.FileData"
  }
}
三、接口列表
1. /c_res — 获取/设置强制缩小分辨率选项
对应界面组件：「是否强制缩小分辨率」复选框
请求参数
参数名	类型	必填	默认值	说明	
value	bool	否	False	是否强制缩小分辨率	
请求示例
result = client.predict(value=False, api_name="/c_res")
print(result)
返回值
位置	类型	说明	
[0]	—	当前复选框状态	
2. /split_audio — 分割驱动音频
对应界面组件：「驱动音频」音频输入
请求参数
参数名	类型	必填	说明	
ori_audio	FileData	✅	需要分割的音频文件	
请求示例
result = client.predict(
    ori_audio=handle_file("/path/to/your/audio.wav"),
    api_name="/split_audio"
)
print(result)
返回值
位置	类型	说明	
[0]	FileData	分割后的音频文件对象	
3. /display_video_path — 获取上传视频的路径
对应界面组件：「上传视频」视频输入 → 「视频地址」文本框
请求参数
参数名	类型	必填	说明	
video	dict	✅	视频文件，结构为 {"video": FileData}，可选含 subtitles 字段	
请求示例
result = client.predict(
    video={"video": handle_file("/path/to/your/video.mp4")},
    api_name="/display_video_path"
)
print(result)
返回值
位置	类型	说明	
[0]	str	视频文件的服务器路径/地址	
4. /display_audio_path — 获取上传音频的路径
对应界面组件：「驱动音频」音频输入 → 「音频地址」文本框
请求参数
参数名	类型	必填	说明	
video	FileData	✅	音频文件	
请求示例
result = client.predict(
    video=handle_file("/path/to/your/audio.wav"),
    api_name="/display_audio_path"
)
print(result)
返回值
位置	类型	说明	
[0]	str	音频文件的服务器路径/地址	
5. /merge_with_ffmpeg_python — 使用 FFmpeg 合并视频音频
对应界面组件：「生成的数字人视频」视频输入 → 合并输出
请求参数
参数名	类型	必填	说明	
video_path	dict	✅	数字人视频文件，结构为 {"video": FileData}	
请求示例
result = client.predict(
    video_path={"video": handle_file("/path/to/generated_video.mp4")},
    api_name="/merge_with_ffmpeg_python"
)
print(result)
返回值
位置	类型	说明	
[0]	VideoData	合并后的视频（含可选字幕）	
[1]	FileData	合并结果的可下载文件	
6. /add_box — 添加处理框
无参数的触发型接口
请求示例
result = client.predict(api_name="/add_box")
print(result)
返回值
位置	类型	说明	
[0]	—	操作结果	
7. /process_video — 🎯 核心接口：数字人视频生成
对应界面组件的主处理流程，将驱动音频与模板视频合成为数字人视频。
请求参数
参数名	类型	必填	默认值	说明	
audio_file	str	✅	—	驱动音频的路径地址（由 /display_audio_path 获取）	
video_file	str	✅	—	模板视频的路径地址（由 /display_video_path 获取）	
min_resolution	float	否	2	原比例缩小倍数（如 2 表示缩小为原来的 1/2）	
if_res	bool	否	False	是否启用强制缩小分辨率以优化渲染速度	
steps	float	否	4	处理批次，值越大速度越快，但显存占用更高	
请求示例
result = client.predict(
    audio_file="/path/to/audio",
    video_file="/path/to/video",
    min_resolution=2,
    if_res=False,
    steps=4,
    api_name="/process_video"
)
print(result)
返回值
位置	类型	说明	
[0]	VideoData	生成的数字人视频（含可选字幕）	
[1]	str	生成耗时文本	
[2]	FileData	生成结果的可下载文件	
四、完整工作流示例
以下演示从上传到生成数字人视频的完整调用流程：
from gradio_client import Client, handle_file
client = Client("http://localhost:7860/")
# ========== Step 1: 上传音频并获取路径 ==========
audio_result = client.predict(
    video=handle_file("/local/path/drive_audio.wav"),
    api_name="/display_audio_path"
)
audio_path = audio_result
print(f"音频地址: {audio_path}")
# ========== Step 2: 上传视频并获取路径 ==========
video_result = client.predict(
    video={"video": handle_file("/local/path/template_video.mp4")},
    api_name="/display_video_path"
)
video_path = video_result
print(f"视频地址: {video_path}")
# ========== Step 3:（可选）分割音频 ==========
split_result = client.predict(
    ori_audio=handle_file("/local/path/drive_audio.wav"),
    api_name="/split_audio"
)
print(f"分割后音频: {split_result}")
# ========== Step 4: 执行数字人视频生成 ==========
gen_result = client.predict(
    audio_file=audio_path,
    video_file=video_path,
    min_resolution=2,        # 分辨率缩小倍数
    if_res=False,            # 是否强制缩小
    steps=4,                 # 处理批次
    api_name="/process_video"
)
generated_video = gen_result[0]   # 生成的视频
generation_time = gen_result[1]   # 生成耗时
download_file   = gen_result[2]   # 下载文件
print(f"生成耗时: {generation_time}")
print(f"视频 URL: {generated_video['video']['url']}")
print(f"下载 URL: {download_file['url']}")
# ========== Step 5:（可选）FFmpeg 合并 ==========
merge_result = client.predict(
    video_path={"video": handle_file(generated_video['video']['path'])},
    api_name="/merge_with_ffmpeg_python"
)
print(f"合并完成: {merge_result[1]['url']}")
五、接口总览表
接口路径	功能	
/c_res	强制缩小分辨率开关	
/split_audio	分割驱动音频	
/display_video_path	获取视频路径	
/display_audio_path	获取音频路径	
/merge_with_ffmpeg_python	FFmpeg 合并音视频	
/add_box	添加处理框	
/process_video	核心：生成数字人视频	
六、注意事项
文件路径：/process_video 的 audio_file 和 video_file 参数接收的是服务器端路径字符串（来自 /display_audio_path 和 /display_video_path 的返回值），而非本地文件路径。
显存控制：steps 参数值越大处理越快，但在 GPU 显存不足时可能导致 OOM（显存溢出），建议从默认值 4 开始逐步调大。
分辨率优化：当 if_res=True 时，会按 min_resolution 倍数缩小分辨率渲染，可显著提升速度，但输出画质会降低。
文件处理顺序：必须先调用 /display_audio_path 和 /display_video_path 获取服务器路径后，再调用 /process_video。