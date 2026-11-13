# dsh-papers-panel · 论文库侧栏面板

把论文库搬到 **左侧栏**：一个书本图标点开就是论文列表、arXiv 检索、一键导入。
不用再翻「设置 → Agentero」。

数据不另存一份——直接复用已经装好的 **Agentero** 论文插件（`@poco-ai/agentero-dsh`）
的同源 HTTP 接口 `/agentero/api/*`，论文仍然住在它的 Vault 目录（默认 `E:\论文库`）。

## 装

```text
plugin_manager(action: install_bundle, target: "E:\\DS公作区\\dsh-papers-panel")
```

装完左侧栏多一个「论文库」图标，点开即是面板。

## 面板里能做什么

| 动作 | 背后接口 |
|---|---|
| 看库里所有论文（标题 / 作者 / 年份 / 标签） | `GET /agentero/api/papers` |
| 按关键词从 arXiv 检索 | `POST /agentero/api/discover` |
| 把检索结果一键导入（自动下 PDF） | `POST /agentero/api/import` |
| 看当前库位置与名称 | `GET /agentero/api/vault` |

导入完成后面板自动刷新。读全文、划词翻译、高亮批注仍在 Agentero 自带的论文阅读器里
（在对话里说「帮我读第 N 篇」或「把这篇加入对话」）。

## 鉴权与依赖

- 接口只监听回环地址；除 `GET /agentero/api/vault` 外都要求请求头
  `x-agentero-vault: <vault scope>`，面板会先取 vault 拿到 scope 再带上。
- 没装 Agentero 时面板会显示「读不到论文库」，不报错、不影响其它功能。
- 本插件不改 `@poco-ai/*` 任何文件，升级 Agentero 不会被覆盖。

## 卸载

```text
plugin_manager(action: remove_bundle, target: "@un10086/dsh-papers-panel")
```

论文与 PDF 都在 Vault 里，卸载插件不会动数据。

## 已知边界

- 一次只显示当前 Vault 的论文，暂不支持多库切换（在「设置 → Agentero」里换库）。
- 不提供删除/改标签的按钮，这部分仍在 Agentero 面板与对话工具里做。

## 文件

| 文件 | 作用 |
|---|---|
| `lib/index.js` | Host 半侧，仅生命周期日志（面板逻辑全在浏览器半侧） |
| `lib/client.js` | 浏览器半侧：注册 `sidebar.panellist` + `main` 两个 slot |
| `cordis.patch.yml` | bundle patch，insert 一条 Host entry |
| `icon.svg` | 插件图标（侧栏用 inline SVG，同一稿） |

MIT.
