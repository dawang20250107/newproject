// Excel 式 Shift 区间勾选（系统级复用）
// 按住 Shift 点击复选框 → 从上次点选的锚点行到当前行整段一并勾选/取消
// （以当前行的目标状态填充整段）。普通点击照旧单选切换，并记住锚点。
//
// 用法：const { onRowSelClick, resetAnchor } = useShiftSelect({ items, selectedIds, toggleSingle, onManual })
//   items       — ref/computed<Array>，当前行数组（元素需有 .id）
//   selectedIds — ref<Set>，已选 id 集合
//   toggleSingle— (id) => void，普通单选切换（沿用各表已有副作用）
//   onManual    — 可选 () => void，任意手动改选（含区间）时触发，如退出「跨页全选」态
export function useShiftSelect({ items, selectedIds, toggleSingle, onManual }) {
  let lastIdx = null
  function onRowSelClick(e, idx, id) {
    const list = (items && items.value) || []
    if (e.shiftKey && lastIdx !== null && lastIdx < list.length) {
      if (onManual) onManual()
      const a = Math.min(lastIdx, idx), b = Math.max(lastIdx, idx)
      const turnOn = !selectedIds.value.has(id)   // 目标状态：当前行未选则整段选中，否则整段取消
      const s = new Set(selectedIds.value)
      for (let i = a; i <= b; i++) {
        const rid = list[i] && list[i].id
        if (rid == null) continue
        turnOn ? s.add(rid) : s.delete(rid)
      }
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
