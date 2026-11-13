/* ============================================================================
 * dsh-papers-panel — 浏览器半侧（手写 ModuleLoader bundle，无需构建）
 * ----------------------------------------------------------------------------
 * 干两件事：
 *   1) ctx.slots.register({name:'sidebar.panellist', id:'papers'}) —— 左侧栏一个图标
 *   2) ctx.slots.register({name:'main', key:'papers'})            —— 点开是「论文库」页
 *   （DSH 的约定：sidebar.panellist 的每个 id 对应一个同名 main 面板，侧栏自己渲染
 *   按钮、自己 dispatch，我们只需要两边都注册一次。）
 *
 * 数据从同源的 Agentero 插件 HTTP 接口来，不碰它的内部模块：
 *   GET  /agentero/api/vault     —— 返回 {path,name,scope}（唯一不需要 scope 头的）
 *   GET  /agentero/api/papers    —— 论文列表，需 x-agentero-vault: <scope>
 *   POST /agentero/api/discover  —— {keyword}，arXiv 检索
 *   POST /agentero/api/import    —— {text}，text 可以是 arXiv id / DOI / URL
 *
 * 注册 id 必须逐字等于 package.json 的 name：client-modules 的 graph row id 取包名，
 * 不是 cordis.patch.yml 里的 entry id；对不上会被回落成单资源再执行一遍，
 * 第二遍 register 抛 duplicate factory registration，整个 web boot 起不来。
 * ========================================================================== */

window.__ModuleLoader__.load({
  id: '@un10086/dsh-papers-panel',
  factory: function (require) {
    var module = { exports: {} }
    var exports = module.exports

    var react = require('react')
    var h = react.createElement

    var PANEL_ID = 'papers'
    var API = '/agentero/api'
    var STYLE_ID = 'dsh-papers-panel-style'

    var CSS = [
      '.dpp-host{display:flex;flex-direction:column;height:100%;min-height:0;overflow:auto;padding:22px 26px 36px;gap:14px;color:var(--dsw-alias-label-primary,inherit);background:var(--dsw-alias-bg-primary,transparent);font-size:14px;box-sizing:border-box}',
      '.dpp-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}',
      '.dpp-title{font-size:19px;font-weight:600;letter-spacing:.2px;margin:0}',
      '.dpp-sub{color:var(--dsw-alias-label-secondary,#8a8a8a);font-size:12px}',
      '.dpp-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
      '.dpp-input{flex:1;min-width:180px;padding:8px 10px;border-radius:8px;border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.28));background:transparent;color:inherit;font-size:13px;outline:none;box-sizing:border-box}',
      '.dpp-input:focus{border-color:var(--dsw-alias-brand-primary,#4f7cff)}',
      '.dpp-btn{padding:7px 12px;border-radius:8px;border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.28));background:transparent;color:inherit;font-size:13px;cursor:pointer;line-height:1.2}',
      '.dpp-btn:hover:not([disabled]){border-color:var(--dsw-alias-brand-primary,#4f7cff)}',
      '.dpp-btn[disabled]{opacity:.45;cursor:default}',
      '.dpp-btn--primary{background:var(--dsw-alias-brand-primary,#4f7cff);border-color:transparent;color:#fff}',
      '.dpp-btn--tiny{padding:4px 9px;font-size:12px;border-radius:6px}',
      '.dpp-list{display:flex;flex-direction:column;gap:8px}',
      '.dpp-item{padding:10px 12px;border-radius:10px;border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.2));display:flex;flex-direction:column;gap:5px}',
      '.dpp-item-head{display:flex;gap:10px;align-items:flex-start;justify-content:space-between}',
      '.dpp-item-title{font-weight:500;line-height:1.45}',
      '.dpp-item-meta{color:var(--dsw-alias-label-secondary,#8a8a8a);font-size:12px;line-height:1.6}',
      '.dpp-empty{padding:20px;border:1px dashed var(--dsw-alias-border-l1,rgba(127,127,127,.3));border-radius:10px;color:var(--dsw-alias-label-secondary,#8a8a8a);font-size:13px;line-height:1.8}',
      '.dpp-err{padding:10px 12px;border-radius:8px;background:rgba(255,80,80,.1);color:#ff6b6b;font-size:13px;line-height:1.6;white-space:pre-wrap}',
      '.dpp-tag{display:inline-block;padding:1px 6px;border-radius:5px;border:1px solid var(--dsw-alias-border-l1,rgba(127,127,127,.3));font-size:11px;margin-right:4px}',
      '.dpp-sep{height:1px;background:var(--dsw-alias-border-l1,rgba(127,127,127,.16));margin:2px 0}',
      '.dpp-hint{color:var(--dsw-alias-label-secondary,#8a8a8a);font-size:12px;line-height:1.7}'
    ].join('\n')

    /* 第二层样式：对话背景插件会给对话区铺图，面板若透明就糊在壁纸上。
       这里把内容装进一张深色玻璃卡片，不管壁纸深浅都能读清。 */
    var CSS_CARD = [
      '.dpp-host{height:100%;overflow:auto;padding:18px 22px 32px;box-sizing:border-box;font-size:14px;display:block;background:transparent}',
      '.dpp-card{display:flex;flex-direction:column;gap:14px;padding:20px 22px 22px;border-radius:14px;background:rgba(22,24,30,.74);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border:1px solid rgba(255,255,255,.09);box-shadow:0 10px 34px rgba(0,0,0,.3);color:#f3f5f8}',
      '.dpp-card .dpp-title{color:#f7f8fa}',
      '.dpp-card .dpp-sub{color:#a8adba}',
      '.dpp-card .dpp-input{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.18);color:#f3f5f8}',
      '.dpp-card .dpp-input::placeholder{color:rgba(243,245,248,.45)}',
      '.dpp-card .dpp-btn{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.18);color:#f3f5f8}',
      '.dpp-card .dpp-btn:hover:not([disabled]){border-color:#6f9bff;background:rgba(111,155,255,.16)}',
      '.dpp-card .dpp-btn--primary{background:#4f7cff;border-color:transparent;color:#fff}',
      '.dpp-card .dpp-item{background:rgba(255,255,255,.05);border-color:rgba(255,255,255,.1)}',
      '.dpp-card .dpp-item-title{color:#f3f5f8}',
      '.dpp-card .dpp-item-meta{color:#a8adba}',
      '.dpp-card .dpp-empty{border-color:rgba(255,255,255,.2);color:#a8adba;background:rgba(255,255,255,.03)}',
      '.dpp-card .dpp-hint{color:#a8adba}',
      '.dpp-card .dpp-tag{color:#c9cedb;border-color:rgba(255,255,255,.22)}',
      '.dpp-card .dpp-sep{background:rgba(255,255,255,.12)}'
    ].join('\n')

    function ensureCss() {
      if (typeof document === 'undefined') return
      if (document.getElementById(STYLE_ID)) return
      var style = document.createElement('style')
      style.id = STYLE_ID
      style.textContent = CSS + '\n' + CSS_CARD
      document.head.appendChild(style)
    }

    /** 统一读一次响应：{ok,data} → data；{error} 或非 2xx → 抛。 */
    async function call(path, method, body, scope) {
      var headers = {}
      if (scope) headers['x-agentero-vault'] = scope
      if (body) headers['content-type'] = 'application/json'
      var response = await fetch(API + path, {
        method: method || 'GET',
        headers: headers,
        body: body ? JSON.stringify(body) : undefined,
        credentials: 'same-origin'
      })
      var text = await response.text()
      var json = null
      try {
        json = text ? JSON.parse(text) : null
      } catch (_error) {
        json = null
      }
      if (!response.ok) {
        throw new Error((json && json.error) || ('HTTP ' + response.status))
      }
      if (json && typeof json === 'object' && 'error' in json && json.error) {
        throw new Error(String(json.error))
      }
      if (json && typeof json === 'object' && 'ok' in json && 'data' in json) return json.data
      return json
    }

    function authorsOf(paper) {
      var list = paper && Array.isArray(paper.authors) ? paper.authors : []
      if (list.length === 0) return ''
      if (list.length <= 2) return list.join('、')
      return list.slice(0, 2).join('、') + ' 等 ' + list.length + ' 人'
    }

    function PaperRow(props) {
      var paper = props.paper || {}
      var meta = [authorsOf(paper), paper.year ? String(paper.year) : '', paper.date || ''].filter(Boolean).join(' · ')
      var tags = Array.isArray(paper.tags) ? paper.tags : []
      return h(
        'div',
        { className: 'dpp-item' },
        h(
          'div',
          { className: 'dpp-item-title' },
          paper.title || paper.id || '（无标题）'
        ),
        meta ? h('div', { className: 'dpp-item-meta' }, meta) : null,
        tags.length > 0
          ? h(
              'div',
              { className: 'dpp-item-meta' },
              tags.map(function (tag, index) {
                return h('span', { className: 'dpp-tag', key: String(index) }, String(tag))
              })
            )
          : null
      )
    }

    function Panel() {
      var stateHook = react.useState({ phase: 'loading', vault: null, papers: [], error: '' })
      var state = stateHook[0]
      var setState = stateHook[1]

      var keywordHook = react.useState('')
      var keyword = keywordHook[0]
      var setKeyword = keywordHook[1]

      var foundHook = react.useState(null)
      var found = foundHook[0]
      var setFound = foundHook[1]

      var busyHook = react.useState('')
      var busy = busyHook[0]
      var setBusy = busyHook[1]

      var errHook = react.useState('')
      var error = errHook[0]
      var setError = errHook[1]

      async function refresh() {
        try {
          var vault = await call('/vault', 'GET', null, null)
          if (!vault || !vault.scope) {
            setState({ phase: 'novault', vault: vault, papers: [], error: '' })
            return
          }
          var papers = await call('/papers', 'GET', null, vault.scope)
          setState({ phase: 'ready', vault: vault, papers: Array.isArray(papers) ? papers : [], error: '' })
        } catch (failure) {
          setState({ phase: 'error', vault: null, papers: [], error: String((failure && failure.message) || failure) })
        }
      }

      react.useEffect(function () {
        refresh()
      }, [])

      async function discover() {
        var text = keyword.trim()
        if (text === '' || !state.vault) return
        setBusy('discover')
        setError('')
        try {
          var list = await call('/discover', 'POST', { keyword: text }, state.vault.scope)
          setFound(Array.isArray(list) ? list : [])
        } catch (failure) {
          setFound([])
          setError('检索失败：' + String((failure && failure.message) || failure))
        } finally {
          setBusy('')
        }
      }

      async function importPaper(id) {
        if (!state.vault) return
        setBusy('import:' + id)
        setError('')
        try {
          await call('/import', 'POST', { text: String(id) }, state.vault.scope)
          setFound(null)
          setKeyword('')
          await refresh()
        } catch (failure) {
          setError('导入失败：' + String((failure && failure.message) || failure))
        } finally {
          setBusy('')
        }
      }

      var vault = state.vault
      var papers = state.papers

      var header = h(
        'div',
        { className: 'dpp-head' },
        h('h1', { className: 'dpp-title' }, '论文库'),
        h(
          'span',
          { className: 'dpp-sub' },
          state.phase === 'ready' ? (vault && vault.name ? vault.name : '论文库') + ' · ' + papers.length + ' 篇' : '论文库'
        ),
        h('span', { style: { flex: 1 } }),
        h(
          'button',
          { className: 'dpp-btn dpp-btn--tiny', onClick: refresh, disabled: state.phase === 'loading' },
          '刷新'
        )
      )

      var errorBox = error ? h('div', { className: 'dpp-err' }, error) : null

      var body
      if (state.phase === 'loading') {
        body = h('div', { className: 'dpp-empty' }, '正在读取论文库…')
      } else if (state.phase === 'error') {
        body = h('div', { className: 'dpp-empty' }, '读不到论文库：' + state.error + '\n可以看看「设置 → Agentero」里插件是否正常。')
      } else if (state.phase === 'novault') {
        body = h(
          'div',
          { className: 'dpp-empty' },
          '还没有选论文库目录。去「设置 → Agentero」选一个文件夹（例如 E:\\论文库），回来点刷新。'
        )
      } else if (papers.length === 0) {
        body = h(
          'div',
          { className: 'dpp-empty' },
          '库里还没有论文。\n用下面的检索从 arXiv 找一篇导入；或者直接跟我说「帮我查一下 XX 方向的论文」。'
        )
      } else {
        body = h(
          'div',
          { className: 'dpp-list' },
          papers.map(function (paper, index) {
            return h(PaperRow, { paper: paper, key: (paper && paper.id) || String(index) })
          })
        )
      }

      var discoverBox = null
      if (state.phase === 'ready') {
        discoverBox = h(
          'div',
          { style: { display: 'flex', flexDirection: 'column', gap: '10px' } },
          h('div', { className: 'dpp-sep' }),
          h(
            'div',
            { className: 'dpp-row' },
            h('input', {
              className: 'dpp-input',
              placeholder: '从 arXiv 检索，例如 organizational culture',
              value: keyword,
              onChange: function (event) {
                setKeyword(event.target.value)
              },
              onKeyDown: function (event) {
                if (event.key === 'Enter') discover()
              }
            }),
            h(
              'button',
              { className: 'dpp-btn dpp-btn--primary', onClick: discover, disabled: busy !== '' || keyword.trim() === '' },
              busy === 'discover' ? '检索中…' : '检索'
            )
          ),
          found === null
            ? null
            : found.length === 0
              ? h('div', { className: 'dpp-empty' }, '没有找到相关论文，换个关键词试试。')
              : h(
                  'div',
                  { className: 'dpp-list' },
                  found.map(function (paper, index) {
                    var id = paper && (paper.id || paper.ref)
                    return h(
                      'div',
                      { className: 'dpp-item', key: String(id || index) },
                      h(
                        'div',
                        { className: 'dpp-item-head' },
                        h('div', { className: 'dpp-item-title' }, (paper && paper.title) || '（无标题）'),
                        h(
                          'button',
                          {
                            className: 'dpp-btn dpp-btn--tiny',
                            disabled: !id || busy !== '',
                            onClick: function () {
                              importPaper(id)
                            }
                          },
                          busy === 'import:' + id ? '导入中…' : '导入'
                        )
                      ),
                      h(
                        'div',
                        { className: 'dpp-item-meta' },
                        [authorsOf(paper), paper && paper.year ? String(paper.year) : '', id ? 'arXiv:' + id : '']
                          .filter(Boolean)
                          .join(' · ')
                      )
                    )
                  })
                ),
          h('div', { className: 'dpp-hint' }, '导入会把 PDF 下到论文库里，几十秒一篇；导入完成后出现在上面的列表里。')
        )
      }

      var footer = vault && vault.path
        ? h('div', { className: 'dpp-hint' }, '库位置：' + vault.path + '　·　也可以在对话里说「帮我读第 N 篇」或「把这篇加入对话」。')
        : null

      return h(
        'div',
        { className: 'dpp-host' },
        h('div', { className: 'dpp-card' }, header, errorBox, body, discoverBox, footer)
      )
    }

    function PanelIcon(props) {
      var size = (props && props.size) || 16
      return h(
        'svg',
        {
          width: size,
          height: size,
          viewBox: '0 0 24 24',
          fill: 'none',
          stroke: 'currentColor',
          strokeWidth: 1.7,
          strokeLinecap: 'round',
          strokeLinejoin: 'round',
          'aria-hidden': 'true'
        },
        h('path', { d: 'M4 5.5A2.5 2.5 0 0 1 6.5 3H19v15H6.5A2.5 2.5 0 0 0 4 20.5z' }),
        h('path', { d: 'M19 18v3H6.5A2.5 2.5 0 0 1 4 18.5' }),
        h('path', { d: 'M8 7.5h7M8 11h5' })
      )
    }

    function apply(ctx) {
      ensureCss()

      ctx.slots.inject('sidebar.panellist', function () {
        return ctx.slots.register(
          {
            name: 'sidebar.panellist',
            id: PANEL_ID,
            order: 7,
            label: function () {
              return '论文库'
            }
          },
          function (owner) {
            return h(PanelIcon, { size: (owner && owner.size) || 16 })
          }
        )
      })

      ctx.slots.inject('main', function () {
        return ctx.slots.register(
          {
            name: 'main',
            key: PANEL_ID
          },
          function () {
            return h(Panel, {})
          }
        )
      })
    }

    exports.apply = apply
    exports.inject = ['slots']
    exports.__test = { call: call, authorsOf: authorsOf }

    return module.exports
  }
})
