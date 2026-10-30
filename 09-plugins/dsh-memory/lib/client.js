/**
 * dsh-memory — 浏览器半侧
 * ----------------------------------------------------------------------------
 * 以 dsh.client bundle 格式加载（手写 ModuleLoader bundle，无需构建）。
 *
 * 在侧边栏（sidebar.panellist）注册「记忆库」图标入口，点击后在中央面板
 * （main slot，key = dsh-memory）渲染长期记忆库页面：
 *   - 展示全部记忆（重要性排序）、标签、创建/使用时间
 *   - 支持单条删除（POST /dsh-memory/delete）
 *   - 支持刷新（GET /dsh-memory/list）
 *
 * 注册 id 必须等于 loader entry 名（dsh-memory）。
 * 页面数据来自 Host 半侧的 /dsh-memory/list 接口。
 */
window.__ModuleLoader__.load({
  id: 'dsh-memory',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })

    var react = require('react')
    var h = react.createElement

    var PANEL_ID = 'dsh-memory'
    var API_LIST = '/dsh-memory/list'
    var API_DELETE = '/dsh-memory/delete'

    /* ---------- 样式（内联，跟随主题继承文字色） ---------- */
    var cardStyle = {
      border: '1px solid rgba(127,127,127,0.28)',
      borderRadius: '10px',
      padding: '12px 14px',
      marginBottom: '10px',
      background: 'rgba(127,127,127,0.06)'
    }
    var tagStyle = {
      display: 'inline-block',
      padding: '1px 8px',
      marginRight: '6px',
      borderRadius: '999px',
      fontSize: '11px',
      lineHeight: '18px',
      background: 'rgba(127,127,127,0.16)'
    }
    var btnStyle = {
      border: '1px solid rgba(127,127,127,0.35)',
      borderRadius: '8px',
      background: 'transparent',
      color: 'inherit',
      font: 'inherit',
      fontSize: '12px',
      padding: '4px 12px',
      cursor: 'pointer'
    }

    function fmtDate(value) {
      if (!value) return '—'
      var d = new Date(value)
      if (isNaN(d.getTime())) return String(value).slice(0, 10)
      var pad = function (n) { return n < 10 ? '0' + n : String(n) }
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes())
    }

    /* ---------- 图标：书本 + 记忆点 ---------- */
    function MemoryIcon(props) {
      var size = (props && props.size) || 16
      return h('svg', {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.8,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true'
      },
        h('path', { key: 'b1', d: 'M4 6c0-1.1.9-2 2-2h5v16H6c-1.1 0-2-.9-2-2V6Z' }),
        h('path', { key: 'b2', d: 'M11 4h7c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2h-7V4Z' }),
        h('path', { key: 'l1', d: 'M7 8h1M7 12h1M14 8h3M14 12h3M14 16h1.5' })
      )
    }

    /* ---------- 数据钩子 ---------- */
    function useMemories() {
      var tickState = react.useState(0)
      var tick = tickState[0]
      var setTick = tickState[1]
      var dataState = react.useState({ loading: true, memories: [], total: 0, updatedAt: null, error: null })
      var data = dataState[0]
      var setData = dataState[1]

      react.useEffect(function () {
        var alive = true
        setData(function (prev) {
          return { loading: true, memories: prev.memories, total: prev.total, updatedAt: prev.updatedAt, error: null }
        })
        fetch(API_LIST, { cache: 'no-store' }).then(function (res) {
          return res.json()
        }).then(function (body) {
          if (!alive) return
          if (body && body.ok) {
            setData({ loading: false, memories: body.memories || [], total: body.total || 0, updatedAt: body.updatedAt || null, error: null })
          } else {
            setData({ loading: false, memories: [], total: 0, updatedAt: null, error: (body && body.error) || '加载记忆库失败' })
          }
        }).catch(function (err) {
          if (!alive) return
          setData({ loading: false, memories: [], total: 0, updatedAt: null, error: String(err && err.message ? err.message : err) })
        })
        return function () { alive = false }
      }, [tick])

      return {
        data: data,
        refresh: function () { setTick(function (t) { return t + 1 }) }
      }
    }

    function deleteMemory(id, content) {
      var ok = window.confirm('永久删除这条记忆？\n\n' + String(content || '').slice(0, 100))
      if (!ok) return Promise.resolve(false)
      return fetch(API_DELETE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: id })
      }).then(function (res) {
        return res.json().then(function (body) {
          return { status: res.status, body: body }
        }, function () {
          return { status: res.status, body: null }
        })
      }).then(function (result) {
        if (result.status !== 200 || !result.body || result.body.ok !== true) {
          throw new Error((result.body && result.body.error) || ('HTTP ' + result.status))
        }
        return true
      })
    }

    /* ---------- 单条记忆卡片 ---------- */
    function MemoryCard(props) {
      var m = props.memory
      var removable = props.onDelete
      var tags = (m.tags || []).map(function (t, i) {
        return h('span', { key: 'tag' + i, style: tagStyle }, String(t))
      })
      return h('div', { style: cardStyle },
        h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' } },
          h('span', { style: { fontSize: '11px', opacity: 0.55, fontFamily: 'monospace' } }, m.id || ''),
          h('span', { style: { fontSize: '11px', opacity: 0.75, color: 'inherit' } }, '重要性 ' + String(m.importance || 3) + '/5'),
          tags,
          removable
            ? h('button', {
              style: { marginLeft: 'auto', ...btnStyle, color: '#e5484d', borderColor: 'rgba(229,72,77,0.5)' },
              title: '删除这条记忆',
              onClick: function () {
                removable(m.id, m.content).then(function (ok) { if (ok) props.onChanged() }).catch(function (err) {
                  window.alert('删除失败：' + (err && err.message ? err.message : String(err)))
                })
              }
            }, '删除')
            : null
        ),
        h('div', { style: { fontSize: '13px', lineHeight: '1.6', whiteSpace: 'pre-wrap' } }, String(m.content || '')),
        h('div', { style: { marginTop: '6px', fontSize: '11px', opacity: 0.45 } },
          '创建 ' + fmtDate(m.createdAt) + (m.lastUsedAt ? ' · 最近使用 ' + fmtDate(m.lastUsedAt) : '')
        )
      )
    }

    /* ---------- 分类（类似相册：全部 / 按类别浏览） ---------- */
    var CATEGORIES = ['全部', '用户偏好', '项目', '技术', '环境', '教训', '其他']
    var CATEGORY_TAGS = {
      '用户偏好': ['preference'],
      '项目': ['project'],
      '技术': ['tech', 'plugin'],
      '环境': ['environment', 'env', 'workspace'],
      '教训': ['lesson', 'qq']
    }
    var chipStyle = {
      border: '1px solid rgba(127,127,127,0.35)',
      borderRadius: '999px',
      background: 'transparent',
      color: 'inherit',
      font: 'inherit',
      fontSize: '12px',
      padding: '4px 12px',
      cursor: 'pointer',
      opacity: 0.85
    }
    var chipActiveStyle = Object.assign({}, chipStyle, {
      background: 'rgba(127,127,127,0.28)',
      borderColor: 'rgba(127,127,127,0.6)',
      opacity: 1
    })

    function categorize(memories) {
      var groups = { '全部': memories.slice() }
      var claimed = {}
      CATEGORIES.slice(1).forEach(function (cat) {
        var wanted = CATEGORY_TAGS[cat] || []
        groups[cat] = memories.filter(function (m) {
          var tags = (m.tags || []).map(function (t) { return String(t).toLowerCase() })
          var hit = wanted.some(function (w) { return tags.indexOf(w) >= 0 })
          if (hit) claimed[m.id] = true
          return hit
        })
      })
      groups['其他'] = memories.filter(function (m) { return !claimed[m.id] })
      return groups
    }

    /* ---------- 记忆库页面 ---------- */
    function MemoryPanel() {
      var hook = useMemories()
      var data = hook.data
      var memories = data.memories || []
      var activeState = react.useState('全部')
      var activeCat = activeState[0]
      var setActiveCat = activeState[1]
      var groups = categorize(memories)
      var visible = groups[activeCat] || []

      var header = h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' } },
        h('span', { style: { opacity: 0.85, display: 'inline-flex' } }, h(MemoryIcon, { size: 20 })),
        h('h2', { style: { margin: 0, fontSize: '18px', fontWeight: 600 } }, '记忆库'),
        h('span', { style: { fontSize: '12px', opacity: 0.55 } }, String(data.total) + ' 条'),
        h('button', { style: { marginLeft: 'auto', ...btnStyle }, onClick: hook.refresh }, data.loading ? '刷新中…' : '刷新')
      )

      var subtitle = h('div', { style: { fontSize: '12px', opacity: 0.5, marginBottom: '14px' } },
        '长期记忆 · 每个会话自动加载 · 更新于 ' + (data.updatedAt ? fmtDate(data.updatedAt) : '—')
      )

      var chips = h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' } },
        CATEGORIES.map(function (cat) {
          var count = (groups[cat] || []).length
          return h('button', {
            key: cat,
            style: activeCat === cat ? chipActiveStyle : chipStyle,
            onClick: function () { setActiveCat(cat) }
          }, cat + ' ' + count)
        })
      )

      var body
      if (data.error) {
        body = h('div', { style: { ...cardStyle, color: '#e5484d' } }, '加载失败：' + data.error)
      } else if (data.loading && memories.length === 0) {
        body = h('div', { style: { ...cardStyle, opacity: 0.6 } }, '加载中…')
      } else if (visible.length === 0) {
        body = h('div', { style: { ...cardStyle, opacity: 0.6 } }, activeCat === '全部' ? '记忆库还是空的。让我记点东西吧。' : '这个分类下还没有记忆。')
      } else {
        body = h('div', null, visible.map(function (m) {
          return h(MemoryCard, { key: m.id, memory: m, onDelete: deleteMemory, onChanged: hook.refresh })
        }))
      }

      return h('div', { style: { height: '100%', overflow: 'auto', padding: '28px 24px 48px' } },
        h('div', { style: { maxWidth: '860px', margin: '0 auto' } }, header, subtitle, chips, body)
      )
    }

    /* ---------- 注册 ---------- */
    var inject = ['slots']

    function apply(ctx) {
      if (!ctx || !ctx.slots) return

      // 侧边栏图标入口：等待 sidebar.panellist 声明后再注册（参照 dsh-chat-background 的 slots.inject 模式）
      var registerSidebar = function () {
        try {
          ctx.slots.register({
            name: 'sidebar.panellist',
            id: PANEL_ID,
            order: 5,
            label: function () { return '记忆库' }
          }, function (owner) {
            return h(MemoryIcon, { size: (owner && owner.size) || 16 })
          })
        } catch (err) {
          console.error('[dsh-memory] 注册侧边栏入口失败：', err)
        }
      }
      if (typeof ctx.slots.inject === 'function') {
        try { ctx.slots.inject('sidebar.panellist', registerSidebar) } catch (err) { registerSidebar() }
      } else {
        registerSidebar()
      }

      // 中央面板页面（key 与侧边栏 entry id 一致）：同样等待 main slot 声明
      var registerPanel = function () {
        try {
          ctx.slots.register({
            name: 'main',
            key: PANEL_ID
          }, MemoryPanel)
        } catch (err) {
          console.error('[dsh-memory] 注册记忆库页面失败：', err)
        }
      }
      if (typeof ctx.slots.inject === 'function') {
        try { ctx.slots.inject('main', registerPanel) } catch (err) { registerPanel() }
      } else {
        registerPanel()
      }
    }

    exports.apply = apply
    exports.inject = inject
    return module.exports
  }
})
