/* ============================================================================
 * dsh-papers-panel — Host 半侧
 * ----------------------------------------------------------------------------
 * 这一半刻意保持最小：面板的 UI 与数据都在浏览器半侧完成，直接调
 * Agentero 插件已经注册的同源接口（/agentero/api/*），不另建库、不改第三方包。
 *
 * 之所以还要一个 Host 半侧：cordis.patch.yml 里 insert 的 entry 需要一个可加载
 * 的模块入口（package.json main）。这里只做一次生命周期日志，方便排查
 * 「插件到底挂上没有」。
 * ========================================================================== */

export const name = 'papers-panel'
export const inject = []

export function apply(ctx) {
  ctx.effect(() => {
    console.log('[papers-panel] host loaded')
    return () => {
      console.log('[papers-panel] host unloaded')
    }
  })
}
