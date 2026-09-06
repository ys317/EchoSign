# 第三方组件

EchoSign 的 MIT 许可证适用于本项目原创代码，不改变第三方软件与模型的许可条款。

- **Chromium / Chrome for Testing**：由 Playwright 对应版本提供，保留完整发行文件及其中的许可资料。组件声明可在浏览器的 `chrome://credits` 中查看。来源：<https://chromium.googlesource.com/chromium/src/+/main/LICENSE>。
- **BGE small zh v1.5**：语义模型来自 [BAAI](https://huggingface.co/BAAI/bge-small-zh-v1.5)，使用 [Qdrant 的 ONNX 转换](https://huggingface.co/Qdrant/bge-small-zh-v1.5)。上游标注为 MIT，随包附有 `licenses/FlagEmbedding-MIT.txt`。
- **Zipformer 中文 ASR**：使用 [sherpa-onnx 的转换模型](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30)，原始权重来自 [yuekai/icefall-asr-multi-zh-hans-zipformer-large](https://huggingface.co/yuekai/icefall-asr-multi-zh-hans-zipformer-large)。该转换模型页面未单独标注权重许可证，相关许可信息以原作者发布说明为准。
- **Python 与运行库**：包括 CustomTkinter、Pillow、NumPy、SoundCard、sherpa-onnx、FastEmbed、ONNX Runtime、Playwright 等。各组件保留原有版权，随包的许可文本位于 `licenses/` 及 `_internal/` 中相应组件目录。

发行包未修改上述浏览器与模型权重。
