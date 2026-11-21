/**
 * dsh-chat-background — 浏览器半侧
 * ----------------------------------------------------------------------------
 * 以 dsh.client bundle 格式加载（手写 ModuleLoader bundle，无需构建）。
 *
 * 走的是 DSH 官方扩展点，不硬改 DOM 结构：
 *   1) ctx.theme.overrideTokens(source, tokens) —— 主题令牌覆盖层。ui-layout 的
 *      presenter 会把合成后的每个令牌写成 body 的行内 CSS 变量，所以覆盖
 *      --dsw-alias-bg-* 就等于换掉各层表面色，且自动跟随浅色/深色两套。
 *   2) ctx.slots.register({name:'settings.section'}) —— 在设置页加「对话背景」。
 *
 * 配置以 Host 为真源（GET/POST /dsh-chat-bg/config），本机再缓存一份到
 * localStorage 用于首屏秒出；Host 路由不可达时（桌面端 file:// + IPC 形态）
 * 完全回落到本地配置。
 *
 * 图片两种来源：本地路径（由 Host 的 /dsh-chat-bg/image 读盘流回）或直接给 URL。
 *
 * 0.3.0 新增：图片模式下的「Wallpaper Engine 壁纸库」卡片与自绘覆盖层弹窗。
 *   - GET  /dsh-chat-bg/wallpapers         —— 清单 + 构建状态 + 当前选中
 *   - POST /dsh-chat-bg/wallpapers/select  —— 把某张壁纸设为对话背景
 *   - POST /dsh-chat-bg/wallpapers/refresh —— 触发静态封面重新生成
 * 弹窗只用普通 div / button / img 自绘（没有 react-dom，所以不能 portal），
 * 样式全部走 ensurePanelCss 注入、类名统一 __cbgw_ 前缀。
 *
 * 注册 id 必须等于 package.json 的 name（client-modules 的 graph row id 取包名，
 * 不是 cordis.patch.yml 里的 entry id）。改包名/scope 时必须同步改这里，否则
 * 客户端按 row id 找不到注册 → 回落单资源 URL 再执行一遍 → duplicate factory 崩溃。
 */
window.__ModuleLoader__.load({
  id: '@un10086/dsh-chat-background',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })

    var react = require('react')
    var h = react.createElement

    var STORE_KEY = 'dsh-chat-background:config'
    var SOURCE = 'dsh-chat-background'
    var STYLE_ID = 'dsh-chat-background/runtime.css'
    var API = '/dsh-chat-bg/config'
    var API_IMAGE = '/dsh-chat-bg/image'
    /* 0.3.0 壁纸库接口 */
    var API_WALLPAPERS = '/dsh-chat-bg/wallpapers'
    var API_SELECT = '/dsh-chat-bg/wallpapers/select'
    var API_REFRESH = '/dsh-chat-bg/wallpapers/refresh'
    /* 构建进行中每 2.5s 轮询一次清单 */
    var POLL_MS = 2500
    /* ui-layout 的 presenter 在深色方案下给 body 打这个属性 */
    var DARK_ATTR = 'data-ds-dark-theme'

    var DEFAULTS = {
      enabled: false,
      mode: 'color',
      colorLight: '#f3efe6',
      colorDark: '#15171b',
      imagePath: '',          // 本地图片绝对路径（Host 读盘供给）
      imageUrl: '',           // 或直接给 http(s)/data URL
      surfaceAlpha: 0.72,
      scrim: 0.18,
      sidebar: true
    }

    var imageVersion = ''

    /* ── 配置读写 ───────────────────────────────────────────────────────── */

    function clamp(n, lo, hi) {
      n = Number(n)
      if (!isFinite(n)) return lo
      return n < lo ? lo : n > hi ? hi : n
    }

    function isHex(v) {
      return typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v)
    }

    function sanitize(raw) {
      var src = raw && typeof raw === 'object' ? raw : {}
      return {
        enabled: src.enabled === true,
        mode: src.mode === 'image' ? 'image' : 'color',
        colorLight: isHex(src.colorLight) ? src.colorLight.toLowerCase() : DEFAULTS.colorLight,
        colorDark: isHex(src.colorDark) ? src.colorDark.toLowerCase() : DEFAULTS.colorDark,
        imagePath: typeof src.imagePath === 'string' ? src.imagePath.trim().slice(0, 1024) : '',
        imageUrl: typeof src.imageUrl === 'string' ? src.imageUrl.trim().slice(0, 2048) : '',
        surfaceAlpha: clamp(src.surfaceAlpha == null ? DEFAULTS.surfaceAlpha : src.surfaceAlpha, 0.2, 1),
        scrim: clamp(src.scrim == null ? DEFAULTS.scrim : src.scrim, 0, 0.8),
        sidebar: src.sidebar !== false
      }
    }

    function loadCache() {
      try {
        var text = window.localStorage.getItem(STORE_KEY)
        if (text === null) return sanitize(DEFAULTS)
        return sanitize(JSON.parse(text))
      } catch (err) {
        return sanitize(DEFAULTS)
      }
    }

    function saveCache(cfg) {
      try {
        window.localStorage.setItem(STORE_KEY, JSON.stringify(cfg))
      } catch (err) { /* 配额满/隐私模式：忽略 */ }
    }

    /* ── 颜色 ───────────────────────────────────────────────────────────── */

    function hexToRgba(hex, alpha) {
      var safe = isHex(hex) ? hex : '#000000'
      var r = parseInt(safe.slice(1, 3), 16)
      var g = parseInt(safe.slice(3, 5), 16)
      var b = parseInt(safe.slice(5, 7), 16)
      return 'rgba(' + r + ',' + g + ',' + b + ',' + Number(clamp(alpha, 0, 1)).toFixed(3) + ')'
    }

    /* ── 主题令牌层 ─────────────────────────────────────────────────────── */

    var themeService = null
    var layerDisposer = null

    function releaseLayer() {
      if (typeof layerDisposer === 'function') {
        try { layerDisposer() } catch (err) { /* noop */ }
      }
      layerDisposer = null
    }

    function pair(value) {
      return { light: value, dark: value }
    }

    /** 图片真正的来源：本地路径优先，其次直接 URL。 */
    function imageSource(cfg) {
      if (cfg.imagePath) {
        var q = imageVersion ? '?v=' + encodeURIComponent(imageVersion) : ''
        return API_IMAGE + q
      }
      return cfg.imageUrl || ''
    }

    function tokensFor(cfg) {
      if (!cfg || cfg.enabled !== true) return null
      var usingImage = cfg.mode === 'image' && imageSource(cfg) !== ''
      var layers = [
        '--dsw-alias-bg-layer-1',
        '--dsw-alias-bg-layer-2',
        '--dsw-alias-bg-overlay',
        '--dsw-alias-bg-module-platform'
      ]
      var tokens = {}

      if (usingImage) {
        tokens['--dsw-alias-bg-base'] = pair('transparent')
        var a = cfg.surfaceAlpha
        for (var i = 0; i < layers.length; i++) {
          tokens[layers[i]] = {
            light: hexToRgba(cfg.colorLight, a),
            dark: hexToRgba(cfg.colorDark, a)
          }
        }
        if (cfg.sidebar) {
          tokens['--dsw-specific-sidebar-fill'] = {
            light: hexToRgba(cfg.colorLight, Math.min(1, a + 0.1)),
            dark: hexToRgba(cfg.colorDark, Math.min(1, a + 0.1))
          }
        }
        return tokens
      }

      tokens['--dsw-alias-bg-base'] = { light: cfg.colorLight, dark: cfg.colorDark }
      for (var j = 0; j < layers.length; j++) {
        tokens[layers[j]] = { light: cfg.colorLight, dark: cfg.colorDark }
      }
      if (cfg.sidebar) {
        tokens['--dsw-specific-sidebar-fill'] = { light: cfg.colorLight, dark: cfg.colorDark }
      }
      return tokens
    }

    function syncLayer(cfg) {
      var tokens = tokensFor(cfg)
      releaseLayer()
      if (tokens === null || themeService === null || typeof themeService.overrideTokens !== 'function') return
      try {
        layerDisposer = themeService.overrideTokens(SOURCE, tokens)
      } catch (err) {
        layerDisposer = null
      }
    }

    /* ── 运行时 CSS（body 底色 / 背景图）──────────────────────────────────── */

    function escapeUrl(url) {
      return String(url).replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\r?\n/g, '')
    }

    function cssFor(cfg) {
      if (!cfg || cfg.enabled !== true) return ''
      var src = imageSource(cfg)
      var usingImage = cfg.mode === 'image' && src !== ''
      var dark = 'body[' + DARK_ATTR + ']'

      if (!usingImage) {
        return 'body{background-color:' + cfg.colorLight + ' !important}' +
          dark + '{background-color:' + cfg.colorDark + ' !important}'
      }

      var url = 'url("' + escapeUrl(src) + '")'
      var lightScrim = 'rgba(255,255,255,' + cfg.scrim.toFixed(3) + ')'
      var darkScrim = 'rgba(0,0,0,' + cfg.scrim.toFixed(3) + ')'
      var base = 'background-size:cover;background-position:center;background-repeat:no-repeat;' +
        'background-attachment:fixed;'
      return 'body{background-color:' + cfg.colorLight + ' !important;' + base +
        'background-image:linear-gradient(' + lightScrim + ',' + lightScrim + '),' + url + ' !important}' +
        dark + '{background-color:' + cfg.colorDark + ' !important;' + base +
        'background-image:linear-gradient(' + darkScrim + ',' + darkScrim + '),' + url + ' !important}'
    }

    function styleTag() {
      if (typeof document === 'undefined') return null
      var tag = document.querySelector('style[data-plugin-css="' + STYLE_ID + '"]')
      if (tag === null) {
        tag = document.createElement('style')
        tag.dataset.plugin = SOURCE
        tag.dataset.pluginCss = STYLE_ID
        if (document.head) document.head.appendChild(tag)
      }
      return tag
    }

    function syncCss(cfg) {
      var tag = styleTag()
      if (tag === null) return
      tag.textContent = cssFor(cfg)
    }

    function removeCss() {
      if (typeof document === 'undefined') return
      var tag = document.querySelector('style[data-plugin-css="' + STYLE_ID + '"]')
      if (tag !== null && tag.parentNode) tag.parentNode.removeChild(tag)
    }

    function applyConfig(cfg) {
      syncLayer(cfg)
      syncCss(cfg)
    }

    /* ── 壁纸库：纯函数（不碰 DOM，测试直接可测）──────────────────────────── */

    var TYPE_LABELS = {
      scene: '场景',
      video: '视频',
      web: '网页',
      other: '其他'
    }

    function typeLabel(type) {
      return TYPE_LABELS[type] || TYPE_LABELS.other
    }

    /** 播放列表序号徽标；不在 WE 播放列表里返回空串。 */
    function playlistLabel(item) {
      if (!item) return ''
      var index = Number(item.playlistIndex)
      if (!isFinite(index) || index <= 0) return ''
      return '#' + Math.floor(index)
    }

    /** 计数徽标文案，例如 `369 张 · 场景 311 / 视频 52 / 网页 5`（按契约不单列 other）。 */
    function countsText(counts) {
      if (!counts || typeof counts !== 'object') return ''
      var total = Number(counts.total) || 0
      var parts = []
      if (Number(counts.scene) > 0) parts.push('场景 ' + Number(counts.scene))
      if (Number(counts.video) > 0) parts.push('视频 ' + Number(counts.video))
      if (Number(counts.web) > 0) parts.push('网页 ' + Number(counts.web))
      return total + ' 张' + (parts.length > 0 ? ' · ' + parts.join(' / ') : '')
    }

    /** 构建进度文案，严格按照契约：`正在生成静态封面 done/total`。 */
    function progressText(build) {
      if (!build || typeof build !== 'object') return ''
      var done = Number(build.done) || 0
      var total = Number(build.total) || 0
      return '正在生成静态封面 ' + done + '/' + (total > 0 ? total : '?')
    }

    function progressPercent(build) {
      if (!build || typeof build !== 'object') return 0
      var done = Number(build.done) || 0
      var total = Number(build.total) || 0
      if (total <= 0) return 0
      var percent = Math.round(done / total * 100)
      return percent < 0 ? 0 : percent > 100 ? 100 : percent
    }

    function byTitle(a, b) {
      return String(a.title || '').localeCompare(String(b.title || ''), 'zh')
    }

    function resolution(a) {
      return (Number(a.width) || 0) * (Number(a.height) || 0)
    }

    /**
     * 搜索 / 类型筛选 / 排序（全部在客户端完成，369 条全量渲染没问题）。
     * options: { query, type: 'all'|'scene'|'video'|'web', sort: 'playlist'|'name'|'recent'|'resolution' }
     */
    function filterSortItems(items, options) {
      var list = Array.isArray(items) ? items.slice() : []
      var opts = options && typeof options === 'object' ? options : {}
      var query = typeof opts.query === 'string' ? opts.query.trim().toLowerCase() : ''
      var type = typeof opts.type === 'string' ? opts.type : 'all'
      var sort = typeof opts.sort === 'string' ? opts.sort : 'playlist'

      var filtered = list.filter(function (item) {
        if (!item || typeof item !== 'object') return false
        if (type !== 'all' && item.type !== type) return false
        if (query === '') return true
        var title = typeof item.title === 'string' ? item.title.toLowerCase() : ''
        var id = item.id == null ? '' : String(item.id).toLowerCase()
        return title.indexOf(query) >= 0 || id.indexOf(query) >= 0
      })

      if (sort === 'name') {
        filtered.sort(byTitle)
      } else if (sort === 'recent') {
        filtered.sort(function (a, b) {
          var diff = (Number(b.subscriptiondate) || 0) - (Number(a.subscriptiondate) || 0)
          return diff !== 0 ? diff : byTitle(a, b)
        })
      } else if (sort === 'resolution') {
        filtered.sort(function (a, b) {
          var diff = resolution(b) - resolution(a)
          return diff !== 0 ? diff : byTitle(a, b)
        })
      } else {
        /* 播放列表顺序：有 playlistIndex 的按升序在前，没有的按标题排后面 */
        filtered.sort(function (a, b) {
          var ai = a.playlistIndex == null || !isFinite(Number(a.playlistIndex)) ? null : Number(a.playlistIndex)
          var bi = b.playlistIndex == null || !isFinite(Number(b.playlistIndex)) ? null : Number(b.playlistIndex)
          if (ai !== null && bi !== null) return ai - bi
          if (ai !== null) return -1
          if (bi !== null) return 1
          return byTitle(a, b)
        })
      }
      return filtered
    }

    /* ── 壁纸库样式（__cbgw_ 前缀，走 ensurePanelCss 注入）────────────────── */

    function galleryCss() {
      return [
        /* 图片模式卡片 */
        '.__cbgw_card{min-width:0;max-width:100%;overflow-wrap:anywhere}',
        '.__cbgw_head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}',
        '.__cbgw_title{font-size:13px;font-weight:600;color:var(--dsw-alias-label-primary);min-width:0}',
        '.__cbgw_badge{font-size:11px;line-height:1.5;padding:1px 8px;border-radius:999px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-3);color:var(--dsw-alias-label-tertiary);white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis}',
        '.__cbgw_current{display:flex;align-items:center;gap:10px;min-width:0;border:1px solid var(--dsw-alias-border-l2);border-radius:10px;padding:8px;background:var(--dsw-alias-bg-layer-3)}',
        '.__cbgw_currentThumb{width:112px;height:63px;flex:0 0 112px;border-radius:6px;object-fit:cover;background:var(--dsw-alias-bg-layer-1);display:block}',
        '.__cbgw_currentMeta{display:flex;flex-direction:column;gap:4px;min-width:0;flex:1 1 auto}',
        '.__cbgw_currentTitle{font-size:12px;font-weight:600;color:var(--dsw-alias-label-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}',
        '.__cbgw_currentSub{font-size:11px;color:var(--dsw-alias-label-tertiary);line-height:1.5}',
        '.__cbgw_actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}',
        '.__cbgw_btn{border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-3);color:var(--dsw-alias-label-primary);border-radius:8px;padding:6px 14px;font:inherit;font-size:13px;line-height:1.4;cursor:pointer;max-width:100%;white-space:normal;text-align:center}',
        '.__cbgw_btn:hover:not(:disabled){border-color:var(--dsw-alias-state-business-primary)}',
        '.__cbgw_btn:disabled{opacity:.55;cursor:default}',
        '.__cbgw_progress{display:flex;flex-direction:column;gap:5px;min-width:0}',
        '.__cbgw_bar{height:6px;border-radius:999px;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l2);overflow:hidden}',
        '.__cbgw_barFill{height:100%;background:var(--dsw-alias-state-business-primary);transition:width .3s ease}',
        '.__cbgw_note{font-size:11px;line-height:1.55;color:var(--dsw-alias-label-tertiary);overflow-wrap:anywhere}',
        /* fixed 覆盖层弹窗：祖先可能有 transform/overflow，所以宽高都留 100% 上限兜底 */
        '.__cbgw_overlay{position:fixed;top:0;right:0;bottom:0;left:0;width:100vw;height:100vh;height:100dvh;z-index:2000;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;background:rgba(0,0,0,.55)}',
        '.__cbgw_modal{position:relative;display:flex;flex-direction:column;width:min(1100px,92vw);max-width:100%;height:min(760px,88vh);max-height:100%;min-width:0;min-height:0;border-radius:14px;background:var(--dsw-alias-bg-module-platform);color:var(--dsw-alias-label-primary);border:1px solid var(--dsw-alias-border-l2);box-shadow:0 18px 60px rgba(0,0,0,.45);overflow:hidden;box-sizing:border-box}',
        '.__cbgw_modalHead{display:flex;align-items:center;gap:10px;flex:0 0 auto;padding:12px 16px;border-bottom:1px solid var(--dsw-alias-border-l2);min-width:0}',
        '.__cbgw_modalTitle{font-size:15px;font-weight:600;color:var(--dsw-alias-label-primary);min-width:0}',
        '.__cbgw_close{margin-left:auto;flex:0 0 auto}',
        '.__cbgw_toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;flex:0 0 auto;padding:10px 16px;border-bottom:1px solid var(--dsw-alias-border-l2);min-width:0}',
        '.__cbgw_search{flex:1 1 180px;min-width:110px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-3);color:var(--dsw-alias-label-primary);border-radius:8px;padding:6px 10px;font:inherit;font-size:12px;outline:none;box-sizing:border-box}',
        '.__cbgw_search:focus{border-color:var(--dsw-alias-state-business-primary)}',
        '.__cbgw_sel{flex:0 0 auto;max-width:100%;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-3);color:var(--dsw-alias-label-primary);border-radius:8px;padding:6px 8px;font:inherit;font-size:12px}',
        '.__cbgw_body{flex:1 1 auto;min-height:0;overflow:auto;padding:12px 16px}',
        '.__cbgw_grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;align-content:start}',
        '.__cbgw_item{position:relative;display:block;width:100%;min-width:0;padding:0;margin:0;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;overflow:hidden;aspect-ratio:16/9;background:var(--dsw-alias-bg-layer-3);cursor:pointer;font:inherit;color:inherit;text-align:left}',
        '.__cbgw_item:hover{border-color:var(--dsw-alias-state-business-primary)}',
        '.__cbgw_itemOn{outline:2px solid var(--dsw-alias-state-business-primary);outline-offset:-2px;border-color:var(--dsw-alias-state-business-primary)}',
        '.__cbgw_thumb{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;display:block;background:var(--dsw-alias-bg-layer-1)}',
        '.__cbgw_itemTitle{position:absolute;left:0;right:0;bottom:0;padding:18px 6px 5px;font-size:11px;line-height:1.35;color:#fff;background:linear-gradient(transparent,rgba(0,0,0,.75));display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word}',
        '.__cbgw_itemIdx{position:absolute;top:5px;left:5px;padding:1px 6px;border-radius:999px;font-size:10px;line-height:1.5;color:#fff;background:rgba(0,0,0,.62);font-variant-numeric:tabular-nums}',
        '.__cbgw_itemType{position:absolute;top:5px;right:5px;padding:1px 6px;border-radius:999px;font-size:10px;line-height:1.5;color:#fff;background:rgba(0,0,0,.62)}',
        '.__cbgw_check{position:absolute;right:6px;bottom:6px;width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;background:var(--dsw-alias-state-business-primary)}',
        '.__cbgw_empty{padding:48px 0;text-align:center;font-size:12px;color:var(--dsw-alias-label-tertiary)}',
        '.__cbgw_modalFoot{flex:0 0 auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 16px;border-top:1px solid var(--dsw-alias-border-l2);min-width:0}',
        '.__cbgw_modalStatus{flex:1 1 auto;min-width:0;font-size:12px;color:var(--dsw-alias-label-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
        '.__cbgw_modalFoot .__cbgw_note{flex:0 0 auto}',
        /* 弹窗必须不透明：图片模式下 --dsw-alias-bg-* 会被本插件改成半透明（让壁纸透出来），
           弹窗里如果继续用这些令牌，设置页的文字会从壁纸库背后透出来。这里给弹窗一套
           自己的不透明配色变量，浅色/深色主题各一套。 */
        '.__cbgw_modal{--cbgw-panel:#f7f5f1;--cbgw-text:#1b1e24;--cbgw-muted:#666d7a;--cbgw-line:rgba(0,0,0,.14);--cbgw-soft:rgba(0,0,0,.05);--cbgw-field:#ffffff;background:var(--cbgw-panel);color:var(--cbgw-text)}',
        'body[data-ds-dark-theme] .__cbgw_modal{--cbgw-panel:#171a1f;--cbgw-text:#eceef2;--cbgw-muted:#a2a8b4;--cbgw-line:rgba(255,255,255,.16);--cbgw-soft:rgba(255,255,255,.08);--cbgw-field:#22262d}',
        '.__cbgw_modal .__cbgw_modalHead,.__cbgw_modal .__cbgw_toolbar,.__cbgw_modal .__cbgw_modalFoot{border-color:var(--cbgw-line)}',
        '.__cbgw_modal .__cbgw_modalTitle{color:var(--cbgw-text)}',
        '.__cbgw_modal .__cbgw_badge{border-color:var(--cbgw-line);background:var(--cbgw-soft);color:var(--cbgw-muted)}',
        '.__cbgw_modal .__cbgw_search,.__cbgw_modal .__cbgw_sel{background:var(--cbgw-field);color:var(--cbgw-text);border-color:var(--cbgw-line)}',
        '.__cbgw_modal .__cbgw_btn{background:var(--cbgw-soft);border-color:var(--cbgw-line);color:var(--cbgw-text)}',
        '.__cbgw_modal .__cbgw_item{background:var(--cbgw-soft);border-color:var(--cbgw-line)}',
        '.__cbgw_modal .__cbgw_modalStatus,.__cbgw_modal .__cbgw_note,.__cbgw_modal .__cbgw_empty{color:var(--cbgw-muted)}',
        '.__cbgw_modal .__cbgw_bar{background:var(--cbgw-soft);border-color:var(--cbgw-line)}',
        '@media (max-width:720px){.__cbgw_overlay{padding:8px}.__cbgw_modal{width:96vw;height:92vh;max-width:96vw;max-height:92vh}}'
      ].join('')
    }

    /* ── 设置页样式（面板 + 壁纸库）───────────────────────────────────────── */

    var CSS_TEXT = [
      '.__cbg_root{max-width:620px;display:flex;flex-direction:column;gap:14px;font-size:13px;color:var(--dsw-alias-label-primary)}',
      '.__cbg_group{border:1px solid var(--dsw-alias-border-l2);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:12px}',
      '.__cbg_field{display:flex;flex-direction:column;gap:5px}',
      '.__cbg_label{font-size:12px;font-weight:600;color:var(--dsw-alias-label-primary)}',
      '.__cbg_hint{font-size:11px;line-height:1.55;color:var(--dsw-alias-label-tertiary)}',
      '.__cbg_row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}',
      '.__cbg_input{border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-3);font:inherit;color:var(--dsw-alias-label-primary);border-radius:8px;padding:6px 10px;font-size:12px;box-sizing:border-box;width:100%;outline:none;font-family:ui-monospace,Consolas,monospace}',
      '.__cbg_input:focus{border-color:var(--dsw-alias-state-business-primary)}',
      '.__cbg_select{border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-3);color:var(--dsw-alias-label-primary);border-radius:8px;padding:6px 8px;font:inherit;font-size:13px;min-width:160px}',
      '.__cbg_check{display:flex;align-items:flex-start;gap:8px;cursor:pointer}',
      '.__cbg_check input{margin-top:2px;accent-color:var(--dsw-alias-state-business-primary)}',
      '.__cbg_swatch{width:38px;height:26px;padding:0;border:1px solid var(--dsw-alias-border-l2);border-radius:6px;background:transparent;cursor:pointer}',
      '.__cbg_btn{border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-3);color:var(--dsw-alias-label-primary);border-radius:8px;padding:6px 14px;font:inherit;font-size:13px;cursor:pointer}',
      '.__cbg_btn:hover{border-color:var(--dsw-alias-state-business-primary)}',
      '.__cbg_range{flex:1;min-width:140px;accent-color:var(--dsw-alias-state-business-primary)}',
      '.__cbg_value{font-variant-numeric:tabular-nums;min-width:44px;text-align:right;font-size:12px;color:var(--dsw-alias-label-tertiary)}',
      '.__cbg_status{font-size:12px;color:var(--dsw-alias-label-tertiary)}'
    ].join('') + galleryCss()

    function ensurePanelCss() {
      if (typeof document === 'undefined') return
      if (document.querySelector('style[data-plugin-css="' + SOURCE + '/panel.css"]') !== null) return
      var tag = document.createElement('style')
      tag.dataset.plugin = SOURCE
      tag.dataset.pluginCss = SOURCE + '/panel.css'
      tag.textContent = CSS_TEXT
      if (document.head) document.head.appendChild(tag)
    }

    function Field(props) {
      return h('div', { className: '__cbg_field' },
        h('label', { className: '__cbg_label' }, props.label),
        props.children,
        props.hint ? h('div', { className: '__cbg_hint' }, props.hint) : null
      )
    }

    /* ── 壁纸库：渲染（全部是普通纯函数，不调用 hook）──────────────────────── */

    function renderProgress(percent, build) {
      return h('div', { className: '__cbgw_progress' },
        h('div', { className: '__cbgw_bar' },
          h('div', { className: '__cbgw_barFill', style: { width: percent + '%' } })),
        h('div', { className: '__cbgw_note' }, progressText(build))
      )
    }

    function renderCurrentWallpaper(gallery, selectedItem) {
      var thumb = null
      var title = ''
      var sub = ''
      if (selectedItem) {
        thumb = h('img', {
          className: '__cbgw_currentThumb',
          src: selectedItem.thumb,
          alt: selectedItem.title || '',
          loading: 'lazy',
          draggable: false
        })
        title = selectedItem.title || selectedItem.id
        var bits = [typeLabel(selectedItem.type)]
        var label = playlistLabel(selectedItem)
        if (label !== '') bits.push(label)
        sub = bits.join(' · ')
      } else if (gallery !== null && gallery.selectedCustom === true) {
        title = '自定义本地图片'
        sub = '当前壁纸不是来自壁纸库'
      } else {
        title = '未选择'
        sub = '点「打开壁纸库」挑一张'
      }
      return h('div', { className: '__cbgw_current' },
        thumb,
        h('div', { className: '__cbgw_currentMeta' },
          h('div', { className: '__cbgw_currentTitle' }, title),
          h('div', { className: '__cbgw_currentSub' }, sub)
        )
      )
    }

    /** 图片模式下的「壁纸库」卡片：当前壁纸 / 计数 / 三个动作 / 构建进度。 */
    function renderWallpaperCard(props) {
      var gallery = props.gallery
      var galleryOk = !!(gallery && gallery.ok === true)
      var items = galleryOk && Array.isArray(gallery.items) ? gallery.items : []
      var build = gallery && gallery.build ? gallery.build : null
      var buildRunning = !!(build && build.state === 'running')
      var buildFailed = !!(build && build.state === 'error')

      var selectedId = galleryOk ? gallery.selectedId : null
      var selectedItem = null
      for (var i = 0; i < items.length; i++) {
        if (items[i] && items[i].id === selectedId) {
          selectedItem = items[i]
          break
        }
      }

      var children = []
      children.push(h('div', { className: '__cbgw_head' },
        h('div', { className: '__cbgw_title' }, 'Wallpaper Engine 壁纸库'),
        galleryOk ? h('span', { className: '__cbgw_badge' }, countsText(gallery.counts)) : null
      ))

      if (galleryOk) {
        children.push(renderCurrentWallpaper(gallery, selectedItem))
      } else {
        children.push(h('div', { className: '__cbgw_note' },
          props.loading
            ? '正在读取壁纸库…'
            : (gallery !== null && gallery.message ? gallery.message : '壁纸库接口不可用（需 0.3.0 Host 生效）')))
      }

      if (buildRunning) {
        children.push(renderProgress(progressPercent(build), build))
      } else if (buildFailed && build.message) {
        children.push(h('div', { className: '__cbgw_note' }, '生成失败：' + build.message))
      }

      if (galleryOk) {
        children.push(h('div', { className: '__cbgw_actions' },
          h('button', { className: '__cbgw_btn', type: 'button', onClick: props.onOpen }, '打开壁纸库'),
          h('button', {
            className: '__cbgw_btn',
            type: 'button',
            disabled: items.length === 0,
            onClick: props.onRandom
          }, '随机一张'),
          h('button', {
            className: '__cbgw_btn',
            type: 'button',
            disabled: buildRunning || props.busy,
            onClick: props.onRefresh
          }, buildRunning ? '正在生成…' : '重新扫描/生成')
        ))
      } else {
        children.push(h('div', { className: '__cbgw_actions' },
          h('button', {
            className: '__cbgw_btn',
            type: 'button',
            disabled: buildRunning || props.busy,
            onClick: props.onRefresh
          }, buildRunning ? '正在生成…' : '生成壁纸库')
        ))
      }

      return h.apply(null, ['div', { className: '__cbg_group __cbgw_card' }].concat(children))
    }

    function renderGalleryCell(item, selectedId, onSelect) {
      var selected = !!(selectedId && item && item.id === selectedId)
      var label = playlistLabel(item)
      return h('button', {
        key: item.id,
        type: 'button',
        className: '__cbgw_item' + (selected ? ' __cbgw_itemOn' : ''),
        title: (item.title || item.id) + '（' + typeLabel(item.type) + '）',
        onClick: function () { onSelect(item) }
      },
        h('img', {
          className: '__cbgw_thumb',
          src: item.thumb,
          alt: item.title || '',
          loading: 'lazy',
          draggable: false
        }),
        label !== '' ? h('span', { className: '__cbgw_itemIdx' }, label) : null,
        h('span', { className: '__cbgw_itemType' }, typeLabel(item.type)),
        h('span', { className: '__cbgw_itemTitle' }, item.title || item.id),
        selected ? h('span', { className: '__cbgw_check' }, '✓') : null
      )
    }

    /** 自绘 fixed 覆盖层壁纸库弹窗（无 react-dom，只能随设置树内联渲染）。 */
    function renderGalleryModal(props) {
      var gallery = props.gallery || {}
      var build = gallery.build || null
      var buildRunning = !!(build && build.state === 'running')
      var items = Array.isArray(props.items) ? props.items : []
      var total = gallery.counts && Number(gallery.counts.total) > 0
        ? Number(gallery.counts.total)
        : (Array.isArray(gallery.items) ? gallery.items.length : 0)
      var filterNote = props.query ? '筛选出 ' + items.length + ' / ' + total + ' 张' : '共 ' + total + ' 张'
      var statusText = props.status || (filterNote + ' · 点击任意一张立即生效')
      var grid = items.length === 0
        ? h('div', { className: '__cbgw_empty' }, '没有匹配的壁纸')
        : h('div', { className: '__cbgw_grid' }, items.map(function (item) {
          return renderGalleryCell(item, props.selectedId, props.onSelect)
        }))

      return h('div', { className: '__cbgw_overlay' },
        h('div', {
          className: '__cbgw_modal',
          role: 'dialog',
          'aria-modal': 'true',
          'aria-label': '壁纸库'
        },
          h('div', { className: '__cbgw_modalHead' },
            h('div', { className: '__cbgw_modalTitle' }, '壁纸库'),
            h('span', { className: '__cbgw_badge' }, countsText(gallery.counts)),
            h('button', {
              className: '__cbgw_btn __cbgw_close',
              type: 'button',
              onClick: props.onClose
            }, '关闭')
          ),
          h('div', { className: '__cbgw_toolbar' },
            h('input', {
              className: '__cbgw_search',
              type: 'search',
              spellCheck: false,
              placeholder: '搜索标题或 id',
              value: props.query,
              onChange: function (e) { props.onQuery(e.target.value) }
            }),
            h('select', {
              className: '__cbgw_sel',
              value: props.type,
              title: '类型筛选',
              onChange: function (e) { props.onType(e.target.value) }
            },
              h('option', { value: 'all' }, '全部'),
              h('option', { value: 'scene' }, '场景'),
              h('option', { value: 'video' }, '视频'),
              h('option', { value: 'web' }, '网页')
            ),
            h('select', {
              className: '__cbgw_sel',
              value: props.sort,
              title: '排序',
              onChange: function (e) { props.onSort(e.target.value) }
            },
              h('option', { value: 'playlist' }, '播放列表顺序'),
              h('option', { value: 'name' }, '名称'),
              h('option', { value: 'recent' }, '最近订阅'),
              h('option', { value: 'resolution' }, '分辨率')
            ),
            h('button', {
              className: '__cbgw_btn',
              type: 'button',
              disabled: items.length === 0,
              onClick: props.onRandom
            }, '随机一张'),
            h('button', {
              className: '__cbgw_btn',
              type: 'button',
              disabled: buildRunning || props.busy,
              onClick: props.onRefresh
            }, buildRunning ? '正在生成…' : '重新生成'),
            h('button', { className: '__cbgw_btn', type: 'button', onClick: props.onClose }, '完成')
          ),
          h('div', { className: '__cbgw_body' }, grid),
          h('div', { className: '__cbgw_modalFoot' },
            h('div', { className: '__cbgw_modalStatus' }, statusText),
            buildRunning ? h('div', { className: '__cbgw_note' }, progressText(build)) : null
          )
        )
      )
    }

    /* ── 设置页 ─────────────────────────────────────────────────────────── */

    function Panel() {
      var cfgState = react.useState(loadCache())
      var cfg = cfgState[0]
      var setCfg = cfgState[1]
      var statusState = react.useState('')
      var status = statusState[0]
      var setStatus = statusState[1]

      /* 壁纸库状态 */
      var galleryState = react.useState(null)
      var gallery = galleryState[0]
      var setGallery = galleryState[1]
      var galleryLoadingState = react.useState(false)
      var galleryLoading = galleryLoadingState[0]
      var setGalleryLoading = galleryLoadingState[1]
      var galleryBusyState = react.useState(false)
      var galleryBusy = galleryBusyState[0]
      var setGalleryBusy = galleryBusyState[1]
      var galleryOpenState = react.useState(false)
      var galleryOpen = galleryOpenState[0]
      var setGalleryOpen = galleryOpenState[1]
      var queryState = react.useState('')
      var query = queryState[0]
      var setQuery = queryState[1]
      var typeState = react.useState('all')
      var typeFilter = typeState[0]
      var setTypeFilter = typeState[1]
      var sortState = react.useState('playlist')
      var sortBy = sortState[0]
      var setSortBy = sortState[1]
      var modalStatusState = react.useState('')
      var modalStatus = modalStatusState[0]
      var setModalStatus = modalStatusState[1]
      var pollTickState = react.useState(0)
      var pollTick = pollTickState[0]
      var setPollTick = pollTickState[1]

      ensurePanelCss()

      function push(next, note) {
        setCfg(next)
        saveCache(next)
        applyConfig(next)
        if (typeof fetch !== 'function') { setStatus('Host 接口不可用，仅存本机'); return }
        fetch(API, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(next)
        }).then(function (r) { return r.json() }).then(function (body) {
          if (body && body.ok === true) {
            imageVersion = body.imageVersion || ''
            applyConfig(next)
            setStatus(note || '已保存')
          } else {
            setStatus('保存失败：' + ((body && body.error) || '未知错误'))
          }
        }).catch(function () {
          setStatus('Host 接口不可达，仅存本机浏览器')
        })
      }

      function update(patch, note) {
        push(sanitize(Object.assign({}, cfg, patch)), note)
      }

      /* ── 壁纸库动作 ─────────────────────────────────────────────────── */

      function loadWallpapers() {
        if (typeof fetch !== 'function') {
          setGallery({
            ok: false, counts: null, build: null, items: [],
            selectedId: null, selectedCustom: false,
            message: '壁纸库接口不可用（需 0.3.0 Host 生效）'
          })
          setGalleryLoading(false)
          return Promise.resolve(null)
        }
        setGalleryLoading(true)
        return fetch(API_WALLPAPERS, { headers: { Accept: 'application/json' } })
          .then(function (response) { return response.json() })
          .then(function (body) {
            if (body && body.ok === true) {
              setGallery({
                ok: true,
                counts: body.counts || null,
                build: body.build || null,
                items: Array.isArray(body.items) ? body.items : [],
                selectedId: body.selectedId || null,
                selectedCustom: body.selectedCustom === true,
                message: ''
              })
            } else {
              setGallery({
                ok: false,
                counts: (body && body.counts) || null,
                build: (body && body.build) || null,
                items: [],
                selectedId: null,
                selectedCustom: false,
                message: (body && body.message) || '壁纸库还没生成，点下面按钮生成。'
              })
            }
            setGalleryLoading(false)
            return body
          })
          .catch(function () {
            setGallery({
              ok: false, counts: null, build: null, items: [],
              selectedId: null, selectedCustom: false,
              message: '壁纸库接口不可用（需 0.3.0 Host 生效）'
            })
            setGalleryLoading(false)
            return null
          })
      }

      function selectWallpaper(item) {
        if (!item || item.id == null) return
        if (typeof fetch !== 'function') {
          setModalStatus('Host 接口不可用，无法切换')
          setStatus('Host 接口不可用，无法切换')
          return
        }
        setModalStatus('正在切换：' + (item.title || item.id) + '…')
        fetch(API_SELECT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: item.id })
        }).then(function (response) { return response.json() }).then(function (body) {
          if (!body || body.ok !== true || !body.config) {
            setModalStatus('切换失败：' + ((body && body.error) || 'Host 未返回配置'))
            return
          }
          /* 契约要求：saveCache + applyConfig + setCfg，弹窗保持打开 */
          imageVersion = body.imageVersion || ''
          var next = sanitize(body.config)
          /* 底色跟随壁纸：Builder 在 library.json 里算好了 {light,dark}，选图时覆盖两档底色。
             手动改过颜色的用户，下一次从壁纸库换图仍会重新取色（符合「随壁纸变化」）。 */
          var palette = item.palette
          if (palette && isHex(palette.light) && isHex(palette.dark)) {
            next = sanitize(Object.assign({}, next, {
              colorLight: palette.light,
              colorDark: palette.dark
            }))
          }
          saveCache(next)
          applyConfig(next)
          setCfg(next)
          /* select 接口只写了 imagePath，这里把自动取色后的两档底色再写回 Host 配置 */
          fetch(API, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(next)
          }).catch(function () { /* 颜色落盘失败不影响本次显示 */ })
          setGallery(function (prev) {
            if (!prev) return prev
            return Object.assign({}, prev, { selectedId: item.id, selectedCustom: false })
          })
          var title = (body.item && body.item.title) || item.title || item.id
          setModalStatus('已切换：' + title)
          setStatus('已切换壁纸：' + title)
        }).catch(function () {
          setModalStatus('切换失败：壁纸库接口不可达')
        })
      }

      function randomWallpaper() {
        var items = gallery && gallery.ok === true && Array.isArray(gallery.items) ? gallery.items : []
        if (items.length === 0) {
          setModalStatus('壁纸库还没有可用壁纸')
          setStatus('壁纸库还没有可用壁纸')
          return
        }
        selectWallpaper(items[Math.floor(Math.random() * items.length)])
      }

      function refreshWallpapers(mode) {
        if (typeof fetch !== 'function') { setStatus('Host 接口不可达，仅存本机浏览器'); return }
        setGalleryBusy(true)
        fetch(API_REFRESH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: mode || 'missing' })
        }).then(function (response) { return response.json() }).then(function (body) {
          if (!body || body.ok !== true) {
            setStatus('启动生成失败：' + ((body && body.error) || '未知错误'))
            return
          }
          if (body.build) {
            setGallery(function (prev) {
              var base = prev || {
                ok: false, counts: null, items: [],
                selectedId: null, selectedCustom: false, message: ''
              }
              return Object.assign({}, base, { build: body.build })
            })
          }
          setStatus(body.accepted === false
            ? '已有生成任务在跑，完成后自动刷新。'
            : '已开始生成静态封面，进度会自动刷新。')
          if (body.accepted === false) loadWallpapers()
        }).catch(function () {
          setStatus('启动生成失败：Host 接口不可达')
        }).then(function () {
          setGalleryBusy(false)
        })
      }

      /* 打开设置面板（组件挂载）时拉一次清单 */
      react.useEffect(function () {
        loadWallpapers()
      }, [])

      /* build 运行中每 2.5s 轮询一次；每轮用 pollTick 重新挂表 */
      var buildState = gallery && gallery.build && typeof gallery.build.state === 'string'
        ? gallery.build.state
        : ''
      react.useEffect(function () {
        if (buildState !== 'running') return undefined
        var timer = setTimeout(function () {
          loadWallpapers().then(function () {
            setPollTick(function (n) { return n + 1 })
          })
        }, POLL_MS)
        return function () { clearTimeout(timer) }
      }, [buildState, pollTick])

      var usingImage = cfg.mode === 'image'
      var hasImage = cfg.imagePath !== '' || cfg.imageUrl !== ''
      var galleryOk = !!(gallery && gallery.ok === true)
      var galleryItems = galleryOk && Array.isArray(gallery.items) ? gallery.items : []
      var visibleItems = galleryOk
        ? filterSortItems(galleryItems, { query: query, type: typeFilter, sort: sortBy })
        : []

      return h('div', { className: '__cbg_root' },
        h('div', { className: '__cbg_group' },
          h('label', { className: '__cbg_check' },
            h('input', {
              type: 'checkbox',
              checked: cfg.enabled,
              onChange: function (e) { update({ enabled: e.target.checked }) }
            }),
            h('span', null, '启用自定义背景')
          ),
          h(Field, {
            label: '类型',
            hint: usingImage
              ? '图片模式会把各层表面改成半透明，让图片透上来；面板不透明度与压暗层用来保证文字可读。'
              : '纯色模式只换各层表面底色，层级与文字颜色不变。'
          }, h('select', {
            className: '__cbg_select',
            value: cfg.mode,
            onChange: function (e) { update({ mode: e.target.value }) }
          },
            h('option', { value: 'color' }, '纯色'),
            h('option', { value: 'image' }, '图片')
          )),
          h('div', { className: '__cbg_row' },
            h(Field, { label: '浅色方案底色' },
              h('input', {
                className: '__cbg_swatch',
                type: 'color',
                value: cfg.colorLight,
                onChange: function (e) { update({ colorLight: e.target.value }) }
              })),
            h(Field, { label: '深色方案底色' },
              h('input', {
                className: '__cbg_swatch',
                type: 'color',
                value: cfg.colorDark,
                onChange: function (e) { update({ colorDark: e.target.value }) }
              }))
          ),
          h('div', { className: '__cbg_hint' },
            '从壁纸库选图时会自动按壁纸主色更新浅色 / 深色底色；手动改色后以下次换图取色为准。'),
          h('label', { className: '__cbg_check' },
            h('input', {
              type: 'checkbox',
              checked: cfg.sidebar,
              onChange: function (e) { update({ sidebar: e.target.checked }) }
            }),
            h('span', null, '侧栏也一起换')
          )
        ),
        usingImage ? h('div', { className: '__cbg_group' },
          h(Field, {
            label: '本地图片路径',
            hint: 'Host 直接从磁盘读这张图（支持 jpg/png/webp/gif/avif）。换图后按保存即可，带 mtime 版本号自动刷新缓存。'
          }, h('input', {
            className: '__cbg_input',
            type: 'text',
            spellCheck: false,
            placeholder: 'D:\\Pictures\\wallpaper.jpg',
            value: cfg.imagePath,
            onChange: function (e) { update({ imagePath: e.target.value }) }
          })),
          h(Field, {
            label: '或图片地址',
            hint: 'http(s) 网址或 data:image/... 的 data URL。填了本地路径时以本地路径为准。'
          }, h('input', {
            className: '__cbg_input',
            type: 'text',
            spellCheck: false,
            placeholder: 'https://example.com/wallpaper.jpg',
            value: cfg.imageUrl,
            onChange: function (e) { update({ imageUrl: e.target.value }) }
          })),
          h(Field, {
            label: '面板不透明度',
            hint: '越低越透，图片越明显，文字越难读。'
          }, h('div', { className: '__cbg_row' },
            h('input', {
              className: '__cbg_range',
              type: 'range',
              min: '0.2', max: '1', step: '0.02',
              value: String(cfg.surfaceAlpha),
              onChange: function (e) { update({ surfaceAlpha: e.target.value }) }
            }),
            h('span', { className: '__cbg_value' }, Math.round(cfg.surfaceAlpha * 100) + '%'))),
          h(Field, {
            label: '压暗层',
            hint: '在图片上盖一层同色半透明遮罩：浅色方案盖白、深色方案盖黑。'
          }, h('div', { className: '__cbg_row' },
            h('input', {
              className: '__cbg_range',
              type: 'range',
              min: '0', max: '0.8', step: '0.02',
              value: String(cfg.scrim),
              onChange: function (e) { update({ scrim: e.target.value }) }
            }),
            h('span', { className: '__cbg_value' }, Math.round(cfg.scrim * 100) + '%')))
        ) : null,
        /* 壁纸库卡片：图片模式、位于图片设置下面、恢复默认按钮上面 */
        usingImage ? renderWallpaperCard({
          gallery: gallery,
          loading: galleryLoading,
          busy: galleryBusy,
          onOpen: function () {
            setGalleryOpen(true)
            setModalStatus('')
          },
          onRandom: randomWallpaper,
          onRefresh: function () { refreshWallpapers('missing') }
        }) : null,
        h('div', { className: '__cbg_row' },
          h('button', {
            className: '__cbg_btn',
            type: 'button',
            onClick: function () { push(sanitize(DEFAULTS), '已恢复默认') }
          }, '恢复默认')
        ),
        h('div', { className: '__cbg_status' },
          status || (cfg.enabled
            ? (hasImage || usingImage === false ? '已生效，改动立刻可见。' : '已启用，但还没给图片。')
            : '未启用：界面保持原样。')
        ),
        /* 壁纸库弹窗（fixed 覆盖层，内联在设置树里，祖先 transform 时靠 CSS 兜底） */
        usingImage && galleryOpen && galleryOk ? renderGalleryModal({
          gallery: gallery,
          items: visibleItems,
          selectedId: gallery.selectedId,
          query: query,
          type: typeFilter,
          sort: sortBy,
          busy: galleryBusy,
          status: modalStatus,
          onQuery: setQuery,
          onType: setTypeFilter,
          onSort: setSortBy,
          onSelect: selectWallpaper,
          onRandom: randomWallpaper,
          onRefresh: function () { refreshWallpapers('missing') },
          onClose: function () { setGalleryOpen(false) }
        }) : null
      )
    }

    /* ── 插件 ───────────────────────────────────────────────────────────── */

    var inject = ['slots', 'theme']

    function apply(ctx) {
      themeService = ctx.theme || null
      ensurePanelCss()

      /* 先用本机缓存秒出，再以 Host 配置为准修正 */
      applyConfig(loadCache())

      if (typeof fetch === 'function') {
        fetch(API, { headers: { Accept: 'application/json' } })
          .then(function (r) { return r.json() })
          .then(function (body) {
            if (!body || body.ok !== true || !body.config) return
            imageVersion = body.imageVersion || ''
            var cfg = sanitize(body.config)
            saveCache(cfg)
            applyConfig(cfg)
          })
          .catch(function () { /* Host 不可达：继续用缓存 */ })
      }

      ctx.effect(function () {
        return function () {
          releaseLayer()
          removeCss()
        }
      })

      ctx.slots.inject('settings.section', function () {
        return ctx.slots.register(
          { name: 'settings.section', id: 'chat-background', order: 27, label: '对话背景' },
          function () { return h(Panel, {}) }
        )
      })
    }

    exports.apply = apply
    exports.inject = inject
    /* 仅给测试用，loader 不读这些键。 */
    exports.__test = {
      sanitize: sanitize,
      tokensFor: tokensFor,
      cssFor: cssFor,
      hexToRgba: hexToRgba,
      setImageVersion: function (v) { imageVersion = v },
      Panel: Panel,
      galleryCss: galleryCss,
      countsText: countsText,
      filterSortItems: filterSortItems,
      typeLabel: typeLabel,
      playlistLabel: playlistLabel,
      progressText: progressText,
      progressPercent: progressPercent,
      pollMs: POLL_MS,
      constants: {
        STORE_KEY: STORE_KEY,
        API: API,
        API_IMAGE: API_IMAGE,
        API_WALLPAPERS: API_WALLPAPERS,
        API_SELECT: API_SELECT,
        API_REFRESH: API_REFRESH
      }
    }
    return module.exports
  }
})
