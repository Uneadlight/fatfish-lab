# dsh-vision

给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 加一个 `vision_describe` 工具：**看图理解**（描述画面、读图里的文字、回答问题）。

双引擎：

| 引擎 | 模型 | 什么时候用 |
|---|---|---|
| 智谱 GLM-4V（云端） | `glm-4v-flash`（默认） | 首选；要联网、要 API key、按次计费 |
| Ollama Qwen2.5-VL（本地） | `qwen2.5vl:3b`（默认） | 云端不可用时的兜底；离线、免费、但慢且精度低 |

## 安装

```bash
# 从 npm（发布后）
dsh plugin install dsh-vision

# 或从本地目录
dsh plugin install link:/path/to/dsh-vision
```

装完重启 DSH，工具表里会出现 `vision_describe`。

## 配置

智谱 key 有两种给法，**环境变量优先**：

```bash
# 方式一：环境变量（推荐）
export ZHIPU_API_KEY=你的key           # Windows PowerShell: $env:ZHIPU_API_KEY="你的key"

# 方式二：文件（一行，不要多余空格）
echo 你的key > ~/.dsh/dsh-vision-key.txt
```

Key 在 <https://open.bigmodel.cn/> 控制台申请，`glm-4v-flash` 有免费额度。

**只用本地 Ollama**：不配 key 即可，`mode: "auto"` 会自动落到 Ollama。需要本机装了 Ollama 并拉过模型：

```bash
ollama pull qwen2.5vl:3b
```

## 用法

工具签名：

```
vision_describe(path, question?, mode?, noCache?)
```

| 参数 | 说明 |
|---|---|
| `path` | 图片绝对路径，支持 png / jpg / jpeg / webp / gif / bmp / tiff |
| `question` | 想问什么。不给就默认「详细描述这张图并完整提取文字」 |
| `mode` | `auto`（默认，云端优先、失败兜底本地）/ `api`（只云端）/ `local`（只本地） |
| `noCache` | `true` 跳过缓存重算。默认复用 7 天内同图同问题的结果 |

返回 JSON：

```json
{ "ok": true, "data": { "engine": "zhipu", "model": "glm-4v-flash", "text": "……", "cached": false } }
```

## 什么时候用、什么时候别用

**用**：需要「理解画面语义」时——这张图在讲什么、人物什么表情、界面布局合不合理、这图有什么毛病、图里那几行字连起来是什么意思。

**别用**：
- 只是要「看一眼 / 数个数 / 认个小字 / 确认某个图标在不在」→ 用宿主自带的 `read_image` 直接看。免费、快、不走网络。
- 一张图反复问同一件事 → 第二次开始走缓存，但如果问题每次都不一样，缓存帮不上忙，考虑一次性问全。
- 精确的像素坐标、颜色值、对齐误差 → 视觉模型给不准，用 `read_image` 或代码量。

## 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `ZHIPU_API_KEY` | — | 智谱 key（优先于文件） |
| `DSH_VISION_ZHIPU_MODEL` | `glm-4v-flash` | 换云端模型 |
| `DSH_VISION_MODEL` | `qwen2.5vl:3b` | 换本地 Ollama 模型 |
| `DSH_VISION_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama 地址 |
| `DSH_VISION_OLLAMA_EXE` | `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` | Ollama 可执行文件（服务没起来时自动拉起） |
| `DSH_VISION_CACHE` | 开 | 设 `off` 整体关闭结果缓存 |
| `DSH_VISION_CACHE_TTL_H` | `168`（7 天） | 缓存有效期（小时） |

## 许可证

MIT © 2026 Uneadlight
