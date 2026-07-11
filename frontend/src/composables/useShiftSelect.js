// Excel 式 Shift 区间勾选（系统级复用）
// 按住 Shift 点击复选框 → 从上次点选的锚点行到当前行整段一并勾选/取消
// （以当前行的目标状态填充整段）。普通点击照旧单选切换，并记住锚点。
//
// 复选框视觉以 DOM 为准（不要在复选框上加 .prevent）：
// 浏览器先原生打勾，处理器读 e.target.checked 把状态同步过去。
// 旧写法（.prevent + 状态切换 + :checked 回写）依赖「preventDefault 的回滚
// 发生在 Vue 微任务刷新之前」——部分浏览器内核顺序相反，Vue 刚画上的勾
// 会被回滚擦掉，表现为「点击后勾选框不打勾」。DOM 为准的写法与回滚时机
// 无关，且状态一旦失步会被下一次点击自愈。
//
// 用法：const { onRowSelClick, resetAnchor } = useShiftSelect({ items, selectedIds, toggleSingle, onManual })
//   items       — ref/computed<Array>，当前行数组（元素需有 .id）
//   selectedIds — ref<Set>，已选 id 集合
//   toggleSingle— (id) => void，非复选框触发（如整行点击）时的单选切换兜底
//   onManual    — 可选 () => void，任意手动改选时先触发（如退出「跨页全选」态）
export function useShiftSelect({ items, selectedIds, toggleSingle, onManual }) {
  let lastIdx = null
  function onRowSelClick(e, idx, id) {
    // 任意手动改选（单击或区间）都先触发 onManual——各表借此退出「跨页全选」态
    // 并把本页勾选落地进 selectedIds，之后的切换全部基于真实集合。
    if (onManual) onManual()
    const list = (items && items.value) || []
    // DOM 真值：事件来自复选框时，浏览器已完成原生切换，target.checked 即用户意图
    const domOn = e && e.target && typeof e.target.checked === 'boolean' ? e.target.checked : null
    if (e.shiftKey && lastIdx !== null && lastIdx < list.length) {
      const a = Math.min(lastIdx, idx), b = Math.max(lastIdx, idx)
      const turnOn = domOn !== null ? domOn : !selectedIds.value.has(id)
      const s = new Set(selectedIds.value)
      for (let i = a; i <= b; i++) {
        const rid = list[i] && list[i].id
        if (rid == null) continue
        turnOn ? s.add(rid) : s.delete(rid)
      }
      selectedIds.value = s
    } else if (domOn !== null) {
      const s = new Set(selectedIds.value)
      domOn ? s.add(id) : s.delete(id)
      selectedIds.value = s
    } else {
      toggleSingle(id)
    }
    lastIdx = idx
  }
  // 数据重载/切筛选后建议复位锚点，避免跨数据集的错误区间
  function resetAnchor() { lastIdx = null }
  return { onRowSelClick, resetAnchor }
}
