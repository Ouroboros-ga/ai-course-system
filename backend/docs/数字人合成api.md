API documentation
http://localhost:7860/

API Recorder

14 API endpoints


Choose a language to see the code snippets for interacting with the API.

1. Install the python client (docs) if you don't already have it installed.

copy
$ pip install gradio_client
2. Find the API endpoint below corresponding to your desired function in the app. Copy the code snippet, replacing the placeholder values with your own input data. Or use the 
API Recorder

 to automatically generate your API requests.

api_name: /c_res
copy
from gradio_client import Client

client = Client("http://localhost:7860/")
result = client.predict(
		value=False,
		api_name="/c_res"
)
print(result)
Accepts 1 parameter:
value bool Default: False

The input value that is provided in the "是否强制缩小分辨率,勾选后会按下面的倍数进行缩小渲染视频，优化速度" Checkbox component.

Returns 1 element
api_name: /split_audio
copy
from gradio_client import Client, handle_file

client = Client("http://localhost:7860/")
result = client.predict(
		ori_audio=handle_file('https://github.com/gradio-app/gradio/raw/main/test/test_files/audio_sample.wav'),
		api_name="/split_audio"
)
print(result)
Accepts 1 parameter:
ori_audio dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])) Required

The input value that is provided in the "驱动音频" Audio component. The FileData class is a subclass of the GradioModel class that represents a file object within a Gradio interface. It is used to store file data and metadata when a file is uploaded. Attributes: path: The server file path where the file is stored. url: The normalized server URL pointing to the file. size: The size of the file in bytes. orig_name: The original filename before upload. mime_type: The MIME type of the file. is_stream: Indicates whether the file is a stream. meta: Additional metadata used internally (should not be changed).

Returns 1 element
dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData]))

The output value that appears in the "驱动音频" Audio component.

api_name: /display_video_path
copy
from gradio_client import Client, handle_file

client = Client("http://localhost:7860/")
result = client.predict(
		video={"video":handle_file('https://github.com/gradio-app/gradio/raw/main/demo/video_component/files/world.mp4')},
		api_name="/display_video_path"
)
print(result)
Accepts 1 parameter:
video dict(video: dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])), subtitles: dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])) | None) Required

The input value that is provided in the "上传视频" Video component. null

Returns 1 element
str

The output value that appears in the "视频地址(视频上传不显示没关系，有地址就行)" Textbox component.

api_name: /display_audio_path
copy
from gradio_client import Client, handle_file

client = Client("http://localhost:7860/")
result = client.predict(
		video=handle_file('https://github.com/gradio-app/gradio/raw/main/test/test_files/audio_sample.wav'),
		api_name="/display_audio_path"
)
print(result)
Accepts 1 parameter:
video dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])) Required

The input value that is provided in the "驱动音频" Audio component. The FileData class is a subclass of the GradioModel class that represents a file object within a Gradio interface. It is used to store file data and metadata when a file is uploaded. Attributes: path: The server file path where the file is stored. url: The normalized server URL pointing to the file. size: The size of the file in bytes. orig_name: The original filename before upload. mime_type: The MIME type of the file. is_stream: Indicates whether the file is a stream. meta: Additional metadata used internally (should not be changed).

Returns 1 element
str

The output value that appears in the "音频地址（音频上传不显示没关系，有地址就行" Textbox component.

api_name: /merge_with_ffmpeg_python
copy
from gradio_client import Client, handle_file

client = Client("http://localhost:7860/")
result = client.predict(
		video_path={"video":handle_file('https://github.com/gradio-app/gradio/raw/main/demo/video_component/files/world.mp4')},
		api_name="/merge_with_ffmpeg_python"
)
print(result)
Accepts 1 parameter:
video_path dict(video: dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])), subtitles: dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])) | None) Required

The input value that is provided in the "生成的数字人视频" Video component. null

Returns tuple of 2 elements
[0] dict(video: dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])), subtitles: dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])) | None)

The output value that appears in the "生成的数字人视频" Video component.

[1] dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData]))

The output value that appears in the "生成结果下载" File component.

api_name: /add_box
copy
from gradio_client import Client

client = Client("http://localhost:7860/")
result = client.predict(
		api_name="/add_box"
)
print(result)
Accepts 0 parameters:
Returns 1 element
api_name: /process_video
copy
from gradio_client import Client

client = Client("http://localhost:7860/")
result = client.predict(
		audio_file="Hello!!",
		video_file="Hello!!",
		min_resolution=2,
		if_res=False,
		steps=4,
		api_name="/process_video"
)
print(result)
Accepts 5 parameters:
audio_file str Required

The input value that is provided in the "音频地址（音频上传不显示没关系，有地址就行" Textbox component.

video_file str Required

The input value that is provided in the "视频地址(视频上传不显示没关系，有地址就行)" Textbox component.

min_resolution float Default: 2

The input value that is provided in the "原比例缩小几倍" Number component.

if_res bool Default: False

The input value that is provided in the "是否强制缩小分辨率,勾选后会按下面的倍数进行缩小渲染视频，优化速度" Checkbox component.

steps float Default: 4

The input value that is provided in the "处理批次,越大越快，但可能爆显存" Number component.

Returns tuple of 3 elements
[0] dict(video: dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])), subtitles: dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData])) | None)

The output value that appears in the "生成的数字人视频" Video component.

[1] str

The output value that appears in the "生成时间" Textbox component.

[2] dict(path: str, url: str | None, size: int | None, orig_name: str | None, mime_type: str | None, is_stream: bool, meta: dict(_type: Literal[gradio.FileData]))

The output value that appears in the "生成结果下载" File component.