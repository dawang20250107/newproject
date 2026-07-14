// 长文本单元格富悬浮卡（付款事项/摘要等被截断的列）：跟随鼠标的浮层，
// 比原生 title 更快显示、可容纳整段文字。付款台账/付款流水/审批管理共用。
import { reactive } from 'vue'

export function useHoverTip() {
  const tip = reactive({ show: false, text: '', x: 0, y: 0 })
  function _pos(e) {
    tip.x = Math.min(e.clientX + 16, window.innerWidth - 340)
    tip.y = Math.min(e.clientY + 18, window.innerHeight - 60)
  }
  function showTip(e, text) { if (!text) return; tip.text = text; _pos(e); tip.show = true }
  function moveTip(e) { if (tip.show) _pos(e) }
  function hideTip() { tip.show = false }
  return { tip, showTip, moveTip, hideTip }
}
