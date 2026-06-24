import { reactive } from 'vue'

// 通用右键菜单状态机。每次调用返回独立实例，便于同一页面多张表格各自持有。
// 仅负责「在哪、为谁、开或关」；菜单项的渲染与视口翻转交给 ContextMenu.vue。
//
// 用法：
//   const ctx = useContextMenu()
//   <tr @contextmenu.prevent="ctx.open($event, rec)">
//   <ContextMenu :ctx="ctx" :items="ctxItems" />   // ctxItems 依据 ctx.menu.payload 计算
export function useContextMenu() {
  const menu = reactive({ show: false, x: 0, y: 0, payload: null })

  function open(e, payload) {
    menu.payload = payload
    menu.x = e.clientX
    menu.y = e.clientY
    menu.show = true
  }

  function close() {
    menu.show = false
    menu.payload = null
  }

  return { menu, open, close }
}
