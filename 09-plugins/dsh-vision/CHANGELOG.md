## 2026-11-08 v0.2.2（把「什么时候该用我」写进描述）

- 背景：`lab tools` 实测 42 个会话里 `read_image` 被调 **353 次**、`vision_describe` 只有 **8 次**。不是它不好用，是我把「需要理解画面语义」的事也用「看一眼」的方式处理了——描述里只写了「可以描述、可以 OCR、适合复杂图片」，没写「什么时候不该用它」。
- 改动：工具描述和 `package.json` description 都改成「看图**理解**（不是看图计数）」，并明写两条判据：**该用**=需要理解语义（这图在讲什么/表情/布局合不合理/这图有什么毛病）；**不该用**=只是数个数、认个小字、确认图标在不在 → `read_image` 直看更快也不花钱。
- 为什么不加工具、只改描述：缺的不是能力，是「选工具那一刻的判据」。判据写在工具描述里，它才会在我选工具时出现；写进记忆只会在我想起来时才出现。
- 验证：`node --check lib/index.js` 通过；`package.json` JSON 合法。

## 2026-11-02 v0.2.1（视觉结果缓存）

- 背景：同一张截图反复问同一问题会重复调用智谱付费 API；市场侧 dsh-vision-fallback / dsh-tool-visual-primitives 都做了会话级观察复用。
- 改动：`vision_describe` 增加本地结果缓存，key = 图片内容 sha256 + question + mode；命中直接返回并标注 `引擎: cache(原引擎)`。缓存写 `~/.dsh/dsh-vision-cache.json`（临时文件 + rename 原子写），默认 7 天 TTL、最多 100 条，按最久未用淘汰；新增 `noCache=true` 强制重算；`DSH_VISION_CACHE=off` 可整体关闭，`DSH_VISION_CACHE_TTL_H` / `DSH_VISION_CACHE_MAX` 可调。
- 不引依赖：只用 node:crypto / node:fs 内置模块。
- 验证：`node --check` 通过；缓存命中冒烟测试（伪 key + 预置缓存）不触发网络直接返回；`noCache` 能绕过缓存。

## 2026-10-26 v0.2.0（Ollama 按需启动）

- 背景：用户不希望 Ollama 常驻占内存。
- 改动：callOllama 前调用 ensureOllama()——1.2s 探测 /api/tags，没在跑就 spawn ollama.exe serve（detached/stdio ignore/windowsHide），随后 300ms×50 轮轮询端口就绪（最多 15s）。可用 DSH_VISION_OLLAMA_EXE / DSH_VISION_OLLAMA_URL 覆盖。
- 效果：智谱 API 主路径完全不碰 Ollama；只有兜底或 mode=local 才启动本地模型。
- 验证：node --check 通过。
