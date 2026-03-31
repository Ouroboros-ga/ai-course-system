```bash
uv venv --python 3.10
uv init
uv add paddlepaddle-gpu==2.6.1
uv add setuptools
uv add fairy-doc[gpu]
uv add nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12

```

这次对话主要围绕 **使用 magic-doc 解析文档时遇到的 GPU 环境配置和依赖冲突问题** 展开。核心目标是**让 magic-doc 在使用 GPU 加速的同时，以 `uv` 作为包管理工具**。
```bash
Fri Mar 20 16:51:49 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.76.04              Driver Version: 580.97         CUDA Version: 13.0     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce RTX 5060        On  |   00000000:0B:00.0  On |                  N/A |
|  0%   32C    P5             10W /  145W |     998MiB /   8151MiB |      0%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A              24      G   /Xwayland                             N/A      |
|    0   N/A  N/A             516      G   /AWT-EventQueue-                      N/A      |
|    0   N/A  N/A             768      G   /cef_server                           N/A      |
+-----------------------------------------------------------------------------------------+
nvcc: NVIDIA (R) Cuda compiler driver
Copyright (c) 2005-2024 NVIDIA Corporation
Built on Thu_Mar_28_02:18:24_PDT_2024
Cuda compilation tools, release 12.4, V12.4.131
Build cuda_12.4.r12.4/compiler.34097967_0
```

```bash
ldconfig -p | grep libcuda.so
libcuda.so.1 (libc6,x86-64) => /usr/lib/wsl/lib/libcuda.so.1
libcuda.so (libc6,x86-64) => /usr/local/cuda/targets/x86_64-linux/lib/libcuda.so
```