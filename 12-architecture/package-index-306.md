# @deepseek-ai 包索引

> 生成于 2026-11-01 · 数据源 `D:\DeepSeek Harness\resources\app.asar` 内 793 个 `package.json`，去重后 **306** 个 `@deepseek-ai/*` 包。
> 其中 **305** 个带官方 description（原文引用），**1** 个没有（职责列标 `~` 的是我按包名推断，不是官方说法）。

## 怎么用这张表

- 想知道"某个行为是谁负责的" → 按层找
- 想知道"坏了会不会影响我" → 看层：工具层坏了 = 我调不动；权限层坏了 = 全盘被拦；会话层坏了 = 历史丢；界面层坏了 = 看得见但不致命
- **不做的事**：逐包读源码。工具/会话/插件这类数量大的层，知道职责就够，只有我会改的才读到代码级

## 工具（49）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-agent-tool-presentation` | Agent-plane presentation selector: composes one agent's tools as PTC mode or native tool calls |
| 2 | `dsh-client-ui-cordis` | Cordis dynamic-plugin definition card: the keyed cordis_define tool row with its run/stop switch |
| 3 | `dsh-client-ui-settings-agent-loop` | Settings page of the agent loop on the dsh web client's Plugins page: the parallel tool-call cap of the agent- |
| 4 | `dsh-client-ui-skill` | Web skill references and the dedicated skill tool row |
| 5 | `dsh-client-ui-tool` | Client Tool call-tree renderer and keyed per-tool presentation slot |
| 6 | `dsh-compaction-tool-result-pruner` | Replay-safe model-free head/middle/tail pruning for tool-result surface nodes |
| 7 | `dsh-experimental-agent-team-profile` | Agent Teams collaboration, tools, and Web UI in one experimental bundle |
| 8 | `dsh-experimental-auto-review` | Per-tool LLM authorization review for the DeepSeek Harness Auto permission preset |
| 9 | `dsh-experimental-session-search` | Give Agents tools to search and read earlier sessions from the current workspace. |
| 10 | `dsh-experimental-terminal-bundle` | Keep shell processes alive across tool calls. |
| 11 | `dsh-experimental-tool-agent-team` | Scoped model-facing Agent Teams tools over ctx.agentTeams |
| 12 | `dsh-experimental-tool-worktree` | Model tool that creates and enters a new Git worktree |
| 13 | `dsh-jobs` | Background job registry (ctx.jobs) for the DeepSeek Harness — shared ids, owner isolation, polling, cancellati |
| 14 | `dsh-mcp-client` | MCP client bridge: connects to MCP servers and registers their tools on ctx.tools |
| 15 | `dsh-mcp-resources` | Scoped MCP resource discovery and reading through shared model tools |
| 16 | `dsh-plugin-manager` | Current-profile plugin and bundle management shared by dsh CLI, Web and agent tools |
| 17 | `dsh-plugin-market` | Configured plugin market indexes for the Web Discover page and the plugin_market agent tool |
| 18 | `dsh-repeat-tool-reminder` | Repeat-tool-call guard plugin: advisory reminders when an agent loops on identical tool calls |
| 19 | `dsh-session-checkpoint-policy` | Semantic session durability checkpoints before model requests and tool side effects |
| 20 | `dsh-session-format-v3-to-v4` | Streaming tool-role migration and delivery validation from Session V3 to V4 |
| 21 | `dsh-shell-env` | Tool-independent managed DSH_* shell environment registry |
| 22 | `dsh-spill` | Abstract spill storage seam (ctx.spillStore) for the DeepSeek Harness — save oversized tool text and return a  |
| 23 | `dsh-spill-policy` | Token-budgeted tool-result retention with recoverable text and image paths |
| 24 | `dsh-tool-ask-user` | Model-facing ask_user_question tool over the ctx.userQuestions seam |
| 25 | `dsh-tool-bash` | Model-facing bash tool with optional generic background-job and sandbox-escalation support |
| 26 | `dsh-tool-bash-persistent` | Model-facing owner-scoped persistent Bash tool backed by the Harness PTY service |
| 27 | `dsh-tool-call-timeout-policy` | Tool-call timeout policy: a tools/execute wrapper that arms a per-tool deadline on exec.signal and returns TOO |
| 28 | `dsh-tool-cordis` | Read-only runtime API inspection for Harness plugin development |
| 29 | `dsh-tool-fs` | Model-facing filesystem tools (read, write, edit) over the DeepSeek Harness filesystem seam (ctx.fs) |
| 30 | `dsh-tool-fs-search` | Model-facing filesystem discovery tools (glob, grep) backed by the packaged ripgrep binary (@vscode/ripgrep) |
| 31 | `dsh-tool-goal` | Model-facing same-session goal tools with execution-time authority checks |
| 32 | `dsh-tool-jobs` | Model-facing background job control tools (job_output, job_list, job_kill) over the ctx.jobs registry |
| 33 | `dsh-tool-present` | Explicit workspace file delivery declarations for the DeepSeek Harness |
| 34 | `dsh-tool-pwsh` | Model-facing pwsh tool over the bash executor seam |
| 35 | `dsh-tool-pwsh-persistent` | Model-facing owner-scoped persistent PowerShell tool backed by the Harness PTY service |
| 36 | `dsh-tool-ralph` | Model-facing fresh-agent Ralph loop over the workflow and subagent seams |
| 37 | `dsh-tool-schedule` | Model-facing reminder management tools (schedule_create, schedule_list, schedule_update, schedule_delete) over |
| 38 | `dsh-tool-session-query` | Workspace-authorized model-facing session history search, trace, and event read tools |
| 39 | `dsh-tool-skill` | Model-facing skill loading tool for the DeepSeek Harness |
| 40 | `dsh-tool-str-replace-editor` | Model-facing view, create, literal replace, and line insert tool over the Harness filesystem service |
| 41 | `dsh-tool-subagent` | Model-facing subagent delegation tool over the ctx.subagents seam |
| 42 | `dsh-tool-subagent-control` | Globally named send_message, interrupt_agent, and list_agents tools over ctx.subagents continuations |
| 43 | `dsh-tool-terminal` | Six model-facing persistent PTY tools with owner isolation and generic background-job integration |
| 44 | `dsh-tool-todo` | Model-facing todo_write tool over the DeepSeek Harness event-sourced session log |
| 45 | `dsh-tool-web` | Model-facing web tools (web_search, web_fetch) over the DeepSeek Harness web capability seam (ctx.web) |
| 46 | `dsh-tool-workflow` | Model-facing workflow tool: run a JavaScript orchestration script over ctx.workflowEngine |
| 47 | `dsh-tool-working-directory` | Read and change the active Session working directory |
| 48 | `dsh-tool-workspace-dependencies` | The load_workspace_dependencies tool: absolute paths into a bundled Python, Node.js, and pnpm payload |
| 49 | `dsh-tools` | Tool registry and execution pipeline for the DeepSeek Harness |

## 提示词（18）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-agent-instructions` | Workspace context loader for AGENTS.md/CLAUDE.md instruction files |
| 2 | `dsh-command-compact` | Human-facing slash command for explicit session compaction |
| 3 | `dsh-compaction` | Abstract compaction service seam (ctx.compaction) for the DeepSeek Harness |
| 4 | `dsh-compaction-basic` | Token-meter-driven compaction policy and LLM summarization backend for the DeepSeek Harness |
| 5 | `dsh-compaction-image-offload` | Durable image offload for image-capable routes: replace over-budget request images with placeholders and retry |
| 6 | `dsh-experimental-session-titles-bundle` | Refresh session titles as new human prompts arrive. |
| 7 | `dsh-fs-observation-policy` | File-context policy plugin for the DeepSeek Harness — observed-state, read-before-edit, and version-guarded wr |
| 8 | `dsh-harness-dev-context` | Model context naming the DeepSeek Harness checkout and Web GUI URL without letting either change the system pr |
| 9 | `dsh-sandbox-policy` | Per-call sandbox policy resolver and current model context: deployment fallbacks plus each session's mode and  |
| 10 | `dsh-scope` | Scoped-context registration primitive (scope tags, scope-filtered event dispatch) for the DeepSeek Harness |
| 11 | `dsh-session-format-v2-to-v3` | Streaming system-prompt, canonical-envelope and PTC migration into V3 |
| 12 | `dsh-session-reference` | Cross-session snapshot references and durable untrusted model context (ctx.sessionReferenceResolver) |
| 13 | `dsh-session-title-all-prompts-llm` | All-user-messages LLM provider plugin for DeepSeek Harness session titles |
| 14 | `dsh-session-title-first-prompt-llm` | First-message LLM provider plugin for DeepSeek Harness session titles |
| 15 | `dsh-system-prompt` | System prompt assembly registry for the DeepSeek Harness |
| 16 | `dsh-time-context` | Durable per-step context with the current time and elapsed time |
| 17 | `dsh-tmux-context` | Opt-in durable per-step context with this agent's tmux pane and window location |
| 18 | `dsh-working-directory` | Session working directories with durable changes and model context |

## 权限（20）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-atomic-write` | Zero-dependency atomic file replacement: exclusive-create random-suffix temp + rename carrying the caller-stat |
| 2 | `dsh-authorization` | Authorization seam (ctx.authorization): plugin-owned flows that obtain a credential through a conversation wit |
| 3 | `dsh-bash-sandbox` | Sandbox-consuming implementation of the DeepSeek Harness bash executor seam (confines every command via ctx.sa |
| 4 | `dsh-client-ui-approval` | Approval composer takeover over the scoped Remote Event waterfall |
| 5 | `dsh-client-ui-permission-presets` | Permission surfaces: a new-session default in General settings and a current-session /permission popup over th |
| 6 | `dsh-client-ui-sidebar-browser` | Sandboxed Web browser tabs for the right Sidebar |
| 7 | `dsh-cordis-host-runner` | Dynamic package definition registry, host-half sandbox lifecycle, and invoke handler table for model-mounted d |
| 8 | `dsh-fs` | Abstract filesystem capability seam (ctx.fs) for the DeepSeek Harness — vocabulary types, the FileSystem servi |
| 9 | `dsh-fs-sandbox` | Sandbox-enforcing implementation of the DeepSeek Harness filesystem seam: fences write/edit by the per-call sa |
| 10 | `dsh-http-proxy` | Process-wide outbound HTTP proxy policy for DeepSeek Harness: resolve it from the launch environment and insta |
| 11 | `dsh-llm-retry` | Provider-routed LLM request retry policy for the DeepSeek Harness |
| 12 | `dsh-permission-presets` | User-facing permission presets (ctx.permissionPresets) for the DeepSeek Harness: one product-level Permissions |
| 13 | `dsh-ptc-runtime-node` | Node PTC execution with per-call sandboxed processes or in-memory REPL state |
| 14 | `dsh-pwsh-sandbox` | Sandbox-consuming implementation of the DeepSeek Harness PowerShell executor seam (confines every command via  |
| 15 | `dsh-sandbox` | Abstract process-sandbox seam (ctx.sandbox) for the DeepSeek Harness: same-world confinement vocabulary and th |
| 16 | `dsh-sandbox-local` | Local process-sandbox backends for the DeepSeek Harness sandbox seam: bwrap, the npm-distributed landlock-run  |
| 17 | `dsh-sandbox-windows-acl` | Windows ACL write-restriction sandbox backend (restricted-token spawn with capability-SID write allowlist) for |
| 18 | `dsh-session-title-llm` | Shared LLM generation policy for DeepSeek Harness session-title providers |
| 19 | `dsh-user-approval` | User-approval seam (ctx.approval) for the DeepSeek Harness: one-shot permission decisions dispatched to compos |
| 20 | `dsh-workflow-ptc` | Workflow orchestration in the shared sandboxed Node PTC runtime |

## 会话（59）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-api-session-controller` | Session Remote commands, cold reads, and live control transport |
| 2 | `dsh-api-terminal-controller` | Session-owned interactive terminals with shell discovery, screen recovery and typed Remote control |
| 3 | `dsh-attachment` | Durable immutable attachment storage seam for the DeepSeek Harness |
| 4 | `dsh-attachment-local` | Private content-addressed DSH_HOME attachment storage |
| 5 | `dsh-chunked-list` | Persistent append-only chunked lists with bounded copying and JSON checkpoint validation |
| 6 | `dsh-client-ui-agent-preset` | Agent-preset surfaces: the default for later sessions, this session's seat, and the composition editor |
| 7 | `dsh-client-ui-goal` | Session goal surface: GoalBar docked above the composer, read from the goal session projection |
| 8 | `dsh-client-ui-jobs` | Session-header background-job list with on-demand streaming record panels |
| 9 | `dsh-client-ui-message-feedback` | The Web feedback surface: per-message Like/Dislike in the assistant-message action strip and the feedback dial |
| 10 | `dsh-client-ui-model-selection` | Model selection over the shared model catalog, Session projection, and session.selectModel |
| 11 | `dsh-client-ui-open-in-app` | Web "Open In..." controls: the Session-header split button opening the workspace directory in an installed app |
| 12 | `dsh-client-ui-plan` | Plan mode controls, persistent transcript plan cards, and sidebar Markdown previews |
| 13 | `dsh-client-ui-reference` | Unified Web @file and @session reference source |
| 14 | `dsh-client-ui-schedule` | Host task management page and Session reminder catalog |
| 15 | `dsh-client-ui-session` | Session Controller adapter for React and session-scoped slots |
| 16 | `dsh-client-ui-settings-session-log` | General settings control for Session-log upload with DeepSeek API requests |
| 17 | `dsh-client-ui-sidebar` | Sidebar plugin: session multi-level tree, search, grouping, state dots |
| 18 | `dsh-client-ui-sidebar-right` | Right Sidebar: the docking surface's session-bound state, its panel and header expand control, and the navigat |
| 19 | `dsh-command-feedback` | Log-only session feedback: the record event, the sessionFeedback Host Remote, and the human-facing slash comma |
| 20 | `dsh-command-goal` | Human-facing slash command for persisted same-session goals |
| 21 | `dsh-config-editor` | Persist plugin configuration through profile patches and Loader reconciliation |
| 22 | `dsh-deque` | Zero-dependency circular deque with amortized constant-time end operations and bounded vacant storage |
| 23 | `dsh-experimental-client-ui-cot-translation` | Optional machine translation of expanded reasoning, preserving original Session text |
| 24 | `dsh-experimental-inspector-profile` | Optional Web bundle for raw Session logs and Chat node inspection |
| 25 | `dsh-experimental-session-inspector` | Experimental virtualized Session log and live Chat group/node inspectors |
| 26 | `dsh-experimental-translator` | Machine translation with reusable Session results |
| 27 | `dsh-experimental-worktree` | Creates a named Git worktree and changes the calling Session working directory |
| 28 | `dsh-goal` | Event-sourced same-session goal state and lifecycle service for the DeepSeek Harness |
| 29 | `dsh-goal-round-driver` | Race-fenced same-session goal-round driver |
| 30 | `dsh-headless` | The dsh one-shot bundle: a direct core Agent/Session runner over dsh-base with no Host, HTTP, or browser layer |
| 31 | `dsh-message-feedback` | Canonical Session-log ratings and notes for finalized assistant messages |
| 32 | `dsh-otel` | Cordis service for independent ordinary-event and byte-bounded Session-log OTLP channels |
| 33 | `dsh-schedule` | Host-wide durable reminders with shared management and original-Session delivery |
| 34 | `dsh-sdk-minimal` | The standalone minimal SDK profile bundle: JSON-RPC, one DeepSeek adapter, persistent shell, and JSONL session |
| 35 | `dsh-session` | Event-sourced session store for the DeepSeek Harness |
| 36 | `dsh-session-format` | Streaming adjacent Session format migration machinery |
| 37 | `dsh-session-format-catalog` | Build-static first-party Session format codec and migration catalog |
| 38 | `dsh-session-format-v0-to-v1` | Frozen released-v0 Session codec and identity migration to v1 |
| 39 | `dsh-session-format-v1-to-v2` | Frozen released-v1 Session codec and assistant-stream migration to v2 |
| 40 | `dsh-session-log-deepseek` | Incremental lossless session-log request extension for the official DeepSeek LLM API |
| 41 | `dsh-session-log-export` | Web Session-log export command and shared download dialog |
| 42 | `dsh-session-persistence` | Abstract durable session persistence seam (ctx.sessionPersistence) for the DeepSeek Harness |
| 43 | `dsh-session-persistence-jsonl` | JSONL durable session persistence backend for the DeepSeek Harness |
| 44 | `dsh-session-projection` | Session-projection seam: the merge-extensible projection type table, the provider contract, and the ctx.sessio |
| 45 | `dsh-session-projection-cache` | Persisted projection cache (ctx.sessionProjectionCache): durable per-session checkpoint records on the session |
| 46 | `dsh-session-query` | Combined session query service contract with concrete reads, traces, and filters |
| 47 | `dsh-session-query-sqlite` | Concrete ctx.sessionQuery backend with SQLite FTS5 search |
| 48 | `dsh-session-stats` | Whole-log conversation counts and wall times projection (sessionStats) for the DeepSeek Harness |
| 49 | `dsh-session-telemetry` | SessionTelemetryBackend seam for the DeepSeek Harness: session-event capture, projection, redaction, and hando |
| 50 | `dsh-session-telemetry-otel` | Feedback-authorized Session logs over byte-bounded OpenTelemetry HTTP requests |
| 51 | `dsh-session-title` | Log-backed session title service and provider registry for the DeepSeek Harness |
| 52 | `dsh-session-turn-outline` | Whole-log turn outline projection (turnOutline) for the DeepSeek Harness |
| 53 | `dsh-spill-local` | Local-filesystem implementation of the DeepSeek Harness spill storage seam (private session-scoped files) |
| 54 | `dsh-storage` | Storage hub (ctx.storage): named backend registry plus mounted data-form facilities for the DeepSeek Harness |
| 55 | `dsh-storage-domain` | Domain data form (ctx.storage.domain): schema-validated, event-emitting KV domains over storage backends for t |
| 56 | `dsh-storage-json` | JSON file KV storage backend for the DeepSeek Harness storage hub |
| 57 | `dsh-terminal` | Persistent PTY session seam for the DeepSeek Harness — owner-scoped ids, backend registry, interactive sends,  |
| 58 | `dsh-terminal-bash` | Persistent shell PTY backend over the DeepSeek Harness subprocess terminal primitive |
| 59 | `dsh-workspace` | Workspace entity registry (ctx.workspaceRegistry): durable workspace records with validated session attachment |

## 模型（27）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-agent-default-model` | Default model selection shared by Agent entry points |
| 2 | `dsh-api-workspace-files` | Workspace file service and Client resource provider: bounded reads, directory listing, and live metadata over  |
| 3 | `dsh-client-resources` | Unified client resource model: protocol-registered providers turn URL addresses into live values, consumed thr |
| 4 | `dsh-client-ui-deepseek-model-label-1017` | Temporary 1017 release badge for official DeepSeek Flash model labels |
| 5 | `dsh-client-ui-settings-models` | Models settings and shared product-onboarding dialogs over existing settings and credential joins |
| 6 | `dsh-client-ui-settings-subagent` | Settings page of Subagent delegation on the dsh web client's Plugins page: recursion depth, parallel capacity, |
| 7 | `dsh-client-ui-settings-web-search` | Settings page of the DeepSeek web-search provider on the dsh web client's Plugins page: its API key, endpoint, |
| 8 | `dsh-credentials` | Abstract credential seam (ctx.credentials): settings carry references to secrets, providers own the values |
| 9 | `dsh-credentials-local` | File-backed credentials provider ($DSH_HOME/.env under the live process environment) for the DeepSeek Harness |
| 10 | `dsh-deepseek-llm-api-extensions` | Additive request-field registry for the official DeepSeek LLM API adapter |
| 11 | `dsh-experimental-speech-to-text` | Experimental speech recognition with independently selectable providers |
| 12 | `dsh-file-reference-local` | Local-filesystem ctx.fileReferences provider with bounded fuzzy indexes |
| 13 | `dsh-llm` | Provider-neutral LLM service interface for the DeepSeek Harness |
| 14 | `dsh-llm-deepseek` | DeepSeek Messages adapter |
| 15 | `dsh-llm-deepseek-account` | DeepSeek account provider authentication and discovery |
| 16 | `dsh-llm-deepseek-api-key` | DeepSeek api-key provider authentication and discovery |
| 17 | `dsh-llm-pi-ai` | pi-ai-backed DeepSeek adapter for the DeepSeek Harness LLM seam (design-verification twin of dsh-llm-deepseek) |
| 18 | `dsh-plugin-package-inventory-deepseek` | Active Loader-backed plugin package inventory for official DeepSeek LLM API requests |
| 19 | `dsh-skill` | Agent skill provider registry for the DeepSeek Harness |
| 20 | `dsh-skill-badge` | Bundled dsh badge skill provider for DeepSeek Harness |
| 21 | `dsh-skill-filesystem` | Local filesystem skill provider for the DeepSeek Harness |
| 22 | `dsh-subagent` | Abstract subagent seam (ctx.subagents): named-provider registry for delegating to child agents |
| 23 | `dsh-typert-protocol` | Compiler-independent Remote metadata and Typert provider protocols |
| 24 | `dsh-web` | Abstract web access capability seam (ctx.web) for the DeepSeek Harness — search/fetch provider registry, regis |
| 25 | `dsh-web-deepseek-api` | DeepSeek Search and Fetch API providers for the DeepSeek Harness web capability seam (ctx.web) |
| 26 | `dsh-web-fetch-http` | Anonymous public HTTP(S) fetch provider for the DeepSeek Harness web capability seam (ctx.web) |
| 27 | `dsh-web-search-deepseek` | DeepSeek-backed search provider (native web_search via the Anthropic-compatible API) for the DeepSeek Harness  |

## 记忆（6）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-client-modules` | Client module system, dual-face: node half composes the __DSH_BOOT__ entry graph (incremental dsh.client scan, |
| 2 | `dsh-client-ui-plugin-market` | Discover tab of the dsh web Plugins page: browse configured plugin market indexes and install their bundles |
| 3 | `dsh-experimental-plugin-market-bundle` | Experimental custom plugin markets: a Discover tab that browses and installs bundles from plugin market indexe |
| 4 | `dsh-host-frontend-static` | SPA dist server for the Web shell: owns the webserver fallback seat, serving explicit index entries and static |
| 5 | `dsh-host-webserver` | Web route-registration plugin: HTTP and upgrade routes, index transform taps, and static dist fallback; knows  |
| 6 | `dsh-plugin-market-index` | Plugin market index format 1: JSON validation, relative icon resolution, and pinned install arguments |

## 插件（41）

| # | 包 | 职责 |
|---|---|---|
| 1 | `cordis` | Meta-Framework for Modern JavaScript Applications |
| 2 | `cordis-plugin-group` | Nested plugin group for cordis |
| 3 | `cordis-plugin-include` | Include files in cordis configurations |
| 4 | `cordis-plugin-loader` | Plugin loader for cordis |
| 5 | `cordis-plugin-timer` | Timer service for cordis |
| 6 | `dsh` | dsh CLI: profile launch, plugin management, and configuration inspection |
| 7 | `dsh-acp-app` | The dsh ACP profile bundle: automation-only JSON-RPC stdio and process lifecycle over dsh-base |
| 8 | `dsh-agent-loop` | The concrete agent loop plugin for the DeepSeek Harness |
| 9 | `dsh-agent-preset` | Declare an Agent capability composition in Cordis YAML |
| 10 | `dsh-agent-preset-registry` | Declarative Agent preset registry and profile-backed editing |
| 11 | `dsh-app-boot` | Shared boot glue for the app bins: .env loading, fail-loud Loader guards, snapshot-aware config resolution, an |
| 12 | `dsh-base` | The shared dsh core as a profile bundle: the first patch layer of base-backed profiles, inserting core rows ov |
| 13 | `dsh-client-hmr` | Web client graph synchronization and rebuilt-bundle reload transport |
| 14 | `dsh-client-locale` | Locale plugin: Host-backed preference, extensible language catalog, browser fallback, and typed built-in dicti |
| 15 | `dsh-client-ui-attachment` | Dynamic attachment presentation plugin for conversation input, message-image, and trajectory image slots |
| 16 | `dsh-client-ui-entry-customization` | Customize plugin entries in the left sidebar, conversation views, and right sidebar, and quickly create new pl |
| 17 | `dsh-client-ui-layout` | Shell plugin: three-column AppFrame with drag handles, ctx.layout viewing-state service (navigation + panels) |
| 18 | `dsh-client-ui-plugin-manager` | Plugin management for the dsh web client: the sidebar Plugins panel installs, enables, disables, retries, and  |
| 19 | `dsh-client-ui-settings` | Settings domain base plugin: shared configuration forms and the canonical settings slot-type contract |
| 20 | `dsh-client-ui-settings-general` | Settings ownerless-copy and product onboarding plugin: the General section, shell trigger/header chrome conten |
| 21 | `dsh-client-ui-settings-plugin-inventory` | Read-only Cordis Loader inventory tab in Web Plugins settings |
| 22 | `dsh-client-ui-settings-plugins` | Built-in plugins settings section for the dsh web client: the Settings navigation entry and the tab chrome fea |
| 23 | `dsh-client-ui-settings-shell` | Settings page of the shell executor on the dsh web client's Plugins page: the command timeout and the per-stre |
| 24 | `dsh-client-ui-theme` | Theme plugin: Host bootstrap for the pre-plugin palette; DOM-free ThemeRuntime for light/dark/system state; -- |
| 25 | `dsh-client-ui-trajectory` | Trajectory event ledger with an interactive timing overview: pure-consumer plugin registering into the convers |
| 26 | `dsh-client-ui-workspace` | Workspace picker plugin: one WorkspacePicker registered into the sidebar and empty-state workspace slots |
| 27 | `dsh-cmdline` | Immutable command-line handoff from a dsh launcher to any app plugin that injects cmdlineArgs |
| 28 | `dsh-commands` | Plugin-owned human command registry for DeepSeek Harness UIs |
| 29 | `dsh-cordis-client-runner` | Browser half of dynamic dual-half plugin packages: event subscription, closure evaluation, guard facade, and l |
| 30 | `dsh-experimental-badge-skill-bundle` | Let agents add a “powered by dsh” badge to documents, pull requests, and other outputs. |
| 31 | `dsh-experimental-cot-translation-bundle` | Experimental machine translation of expanded reasoning |
| 32 | `dsh-experimental-ralph-bundle` | Run explicitly requested repeated work with fresh agents. |
| 33 | `dsh-experimental-voice-input-bundle` | Experimental voice input with local SenseVoice; downloads its runtime on first use |
| 34 | `dsh-hmr` | Coordinated module and profile configuration hot reload |
| 35 | `dsh-host-plugin-inventory` | Read-only Remote projection of current Cordis Loader plugin state |
| 36 | `dsh-sdk-app` | The dsh SDK profile bundle: stdio JSON-RPC serving and process lifecycle over dsh-base |
| 37 | `dsh-sdk-jsonrpc-server` | Stdio JSON-RPC server plugin for out-of-process DeepSeek Harness SDK clients |
| 38 | `dsh-skill-office` | Bundled Word, PowerPoint, and Excel workflows and LibreOffice Kit operations |
| 39 | `dsh-typert-loader` | Loader integration for generated Typert package contributions |
| 40 | `dsh-util-code-language` | Single file-extension to syntax-highlighting language table shared by Client code surfaces and the Host read c |
| 41 | `dsh-web-app` | The dsh browser-surface bundle: the web patch layer over dsh-base plus the runtime glue plugin (frontend dist  |

## 文件（15）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-api-workspace-controller` | Workspace Remote commands and reconnect-safe state transport |
| 2 | `dsh-client-file-upload` | Agent-scoped browser file upload, streaming intake, and staged receipt service |
| 3 | `dsh-client-ui-commands` | Client command surface: global directory cache, '/' source, three command UI kinds, popupSelect registry |
| 4 | `dsh-client-ui-deliverables` | Changed-files card with per-file comparison tabs, delivery cards, and clickable final-response file references |
| 5 | `dsh-client-ui-directory-picker-browse` | In-app directory browsing surface: the workspace directory-flow owner rendering the host's listing and creatio |
| 6 | `dsh-client-ui-directory-picker-native` | Native directory-picker surface: the renderless workspace directory-flow occupant driving the local Desktop or |
| 7 | `dsh-client-ui-sidebar-files` | Workspace file tree tab type for the right Sidebar: lazy directory listing over the workspaceFiles Remote name |
| 8 | `dsh-file-reference` | File-reference discovery contract and shared @file grammar |
| 9 | `dsh-fs-local` | Local-filesystem implementation of the DeepSeek Harness filesystem seam (ctx.fs) |
| 10 | `dsh-home-paths` | Shared filesystem path helpers for the DeepSeek Harness |
| 11 | `dsh-host-directory-picker` | Abstract workspace-directory picking seam (ctx.directoryPicker) for the DeepSeek Harness web GUI host |
| 12 | `dsh-host-directory-picker-browse` | In-app browsing backend of the directory-picker seam (listing/creation primitives over the host filesystem) |
| 13 | `dsh-native-command` | Host-native command and path-opening utilities with shell-free execution, cancellation, desktop detection, and |
| 14 | `dsh-util-workspace-path` | Browser-safe Workspace path and display helpers |
| 15 | `dsh-workspace-changes` | Per-turn workspace file changes recorded from git working-tree snapshots and whole-file captures, with per-fil |

## 网络（13）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-acp` | Automation-only Agent Client Protocol server for driving DeepSeek Harness agents over JSON-RPC stdio |
| 2 | `dsh-api-account-controller` | Expose safe account operations over authenticated Remote |
| 3 | `dsh-api-gateway` | Typert Remote Host dispatcher and Client API endpoint |
| 4 | `dsh-api-job-controller` | Job Remote observation stream and the reference-counted client job-output service |
| 5 | `dsh-api-remote-access` | Method-level Remote access control for non-owner Peers and the per-Peer access snapshot |
| 6 | `dsh-api-remotes` | Remote BFF assembly for application-selected Host capabilities |
| 7 | `dsh-api-settings-controller` | Remote owner for the configuration surfaces over the settings-domain seams |
| 8 | `dsh-deepseek-account` | Read account state and resolve official API credentials |
| 9 | `dsh-experimental-api-speech-to-text` | Authenticated experimental speech transcription for browser clients |
| 10 | `dsh-host-open-in-app` | Host half of open-in-app: resolved application catalog, icons, and the launch endpoint as three webServer rout |
| 11 | `dsh-host-product-telemetry-otel` | Explicit product usage events exported through OpenTelemetry HTTP logs |
| 12 | `dsh-sdk-protocol` | Shared wire protocol for the DeepSeek Harness SDK runtime: the newline-delimited JSON-RPC stdio transport and  |
| 13 | `node-addon-system` | Prebuilt system primitives: a Linux Landlock launcher and asynchronous POSIX flock through stable Node-API |

## 界面（29）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-client-connection` | Authenticated RPC transport and generation lifecycle |
| 2 | `dsh-client-product-analytics` | Desktop product event collection and authenticated Host reporting |
| 3 | `dsh-client-shortcuts` | Application keyboard command registry and physical-key routing |
| 4 | `dsh-client-ui-brand-official` | Official DeepSeek Harness brand occupants for the Web client's sidebar slots |
| 5 | `dsh-client-ui-chat` | Chat Conversation target, node definitions, renderers, and details surface |
| 6 | `dsh-client-ui-conversation` | Target-neutral Conversation assembly, shell, composer, queue, and view navigation |
| 7 | `dsh-client-ui-input-trigger` | Input trigger pipeline: '/' and '@' detection, candidate menu, pick routing to registered sources |
| 8 | `dsh-client-ui-renderer` | Browser UI renderer: React slot bindings, ctx.uiRenderer, and the assembled application root |
| 9 | `dsh-client-ui-secret-mask` | Web display masking for recognized credentials in sent user text |
| 10 | `dsh-client-ui-settings-account` | Manage DeepSeek login and open Platform billing pages |
| 11 | `dsh-client-ui-shortcuts` | Keyboard shortcut reference, recording, and local preference editing |
| 12 | `dsh-client-ui-sidebar-documentpreview` | Extensible Sidebar previews for Office documents, spreadsheets, Markdown, code, images, PDF, HTML, and plain t |
| 13 | `dsh-client-ui-sidebar-terminal` | Interactive shell tabs for the right Sidebar |
| 14 | `dsh-client-ui-subagent` | Subagent conversation catalog, continuation routing UI, and '@' reference source |
| 15 | `dsh-client-ui-user-questions` | Web ask_user_question composer takeover and plan-review presentation UI |
| 16 | `dsh-client-ui-workflow-run` | Durable workflow-run Conversation Node and nested member disclosure for dsh web |
| 17 | `dsh-desktop-host` | Private Node-mode host process for the Electron desktop application |
| 18 | `dsh-desktop-runtime` | ~（无官方描述，按名推断：desktop runtime） |
| 19 | `dsh-experimental-client-ui-agent-team` | Web Agent Teams roster, task board, and teammate navigation |
| 20 | `dsh-experimental-client-ui-voice-input` | Record speech and insert editable text into the conversation draft |
| 21 | `dsh-experimental-inspector` | Experimental cross-realm CDP hub for Host debugging and Client Runtime inspection |
| 22 | `dsh-host-directory-picker-auto` | Adaptive chooser of the directory-picker seam: resolves the host situation at boot and mounts the native or br |
| 23 | `dsh-host-directory-picker-native` | Native-OS-chooser backend of the directory-picker seam for the DeepSeek Harness web GUI host |
| 24 | `dsh-launch-environment` | Immutable DeepSeek Harness launch environment that records which layer supplied each value |
| 25 | `dsh-lazy-require` | Caller-relative, success-cached lazy loading for CommonJS-compatible Host dependencies |
| 26 | `dsh-plan-mode` | Logged per-agent plan mode with deployment guidance, a direct slash command, and a user-reviewed exit |
| 27 | `dsh-util-crypto` | Zero-dependency browser-safe UUID and byte-encoding helpers |
| 28 | `dsh-util-time` | Zero-dependency time vocabulary shared by wire boundaries: canonicalClientTimeZone (IANA zone validation and c |
| 29 | `dsh-web-frontend` | Web application entry: vite build over the @deepseek-ai/dsh-client-web shell library; dist/ served by apps/cli |

## 运行时骨架（11）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-bash-local` | Local-subprocess implementation of the DeepSeek Harness bash executor seam |
| 2 | `dsh-jobs-local` | Process-local implementation of the DeepSeek Harness background job registry seam |
| 3 | `dsh-ptc-runtime` | Abstract PTC execution seam (ctx.ptcRuntime) for the DeepSeek Harness |
| 4 | `dsh-pwsh-local` | Local PowerShell implementation of the DeepSeek Harness bash executor seam |
| 5 | `dsh-settings` | Abstract user-settings seam (ctx.settings) for the DeepSeek Harness |
| 6 | `dsh-shell` | Abstract bash executor seam (ctx.shell) for the DeepSeek Harness |
| 7 | `dsh-subprocess` | Subprocess seam (ctx.subprocess) for the DeepSeek Harness — managed process groups, bounded spill-backed outpu |
| 8 | `dsh-subprocess-local` | Local-subprocess implementation of the DeepSeek Harness subprocess seam |
| 9 | `dsh-user-questions` | Abstract user-questions seam (ctx.userQuestions) for asking the human during agent runs |
| 10 | `dsh-win32-process` | Shared low-level Win32 process, stdio, and Job Object primitives |
| 11 | `dsh-workflow` | Workflow capability seam: ctx.workflowEngine service, run vocabulary, and workflow/* events |

## 基础库（9）

| # | 包 | 职责 |
|---|---|---|
| 1 | `cosmokit` | A collection of common utilities |
| 2 | `dsh-brand` | Stateless branded primitive types for the DeepSeek Harness |
| 3 | `dsh-output-retention` | Zero-dependency bounded-retention primitive: ItemRetainer/TextRetainer + neutral notice helpers (what did we k |
| 4 | `dsh-package-manifest` | Shared type declarations for package.json.dsh configuration fields |
| 5 | `dsh-timeout` | Zero-dependency timeout/deadline primitive: clampTimeout, deadline, timeoutOf, TimeoutReason (timing + classif |
| 6 | `dsh-token-meter` | Replay-aware token measurement service (ctx.tokenMeter) for the DeepSeek Harness |
| 7 | `dsh-typert-registry` | Runtime registry for generated package reflection and Zod schemas |
| 8 | `dsh-util-values` | Duplicate-install-safe value primitives for the DeepSeek Harness |
| 9 | `schemastery` | Type driven schema validator |

## 智能体（5）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-agent` | Agent interface, registry, initiator scope, and event vocabulary for the DeepSeek Harness |
| 2 | `dsh-experimental-agent-team` | Implicit-root Agent Teams roster, direct peer messaging, and shared task DAG |
| 3 | `dsh-persona` | Composition-authored deployment persona section for the DeepSeek Harness |
| 4 | `dsh-subagent-fork-in-process` | In-process fork subagent backend: runs a child agent seeded with a prefix of the parent's log |
| 5 | `dsh-subagent-spawn-in-process` | In-process spawn subagent backend: runs a fresh child agent on ctx.agents |

## 账户身份（2）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-anonymous-user-id` | Shared anonymous user identity for DeepSeek Harness telemetry and feedback correlation |
| 2 | `dsh-deepseek-account-platform` | Authorize DeepSeek accounts through browser PKCE |

## 外部能力（2）

| # | 包 | 职责 |
|---|---|---|
| 1 | `dsh-experimental-speech-to-text-sensevoice` | Local SenseVoice ONNX transcription with a managed sherpa-onnx process |
| 2 | `dsh-office-to-pdf` | Shared Office-to-PDF conversion with bounded queues and caching |

## 统计

| 层 | 包数 |
|---|---|
| 工具 | 49 |
| 提示词 | 18 |
| 权限 | 20 |
| 会话 | 59 |
| 模型 | 27 |
| 记忆 | 6 |
| 插件 | 41 |
| 文件 | 15 |
| 网络 | 13 |
| 界面 | 29 |
| 运行时骨架 | 11 |
| 基础库 | 9 |
| 智能体 | 5 |
| 账户身份 | 2 |
| 外部能力 | 2 |
| **合计** | **306** |
