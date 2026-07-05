import { ref, onMounted, onBeforeUnmount } from 'vue'

// 全窗口文件拖入：从桌面拖文件进页面时 dragging 变 true（页面据此渲染提示遮罩），
// 在窗口任意位置松手回调 onDrop({ file, reason, name })。
// - exts 限定扩展名，不符时 file 为 null 且 reason='ext'
// - 页面若需要多个落点（如普通导入/运输导入两个区域），自设 @drop.stop.prevent
//   截获即可（stop 阻断冒泡，窗口级 onDrop 不再触发），并用返回的 pick/reset 取件与收尾。
// - 不传 onDrop 时仅提供 dragging 状态并拦掉浏览器默认的「打开文件」行为。
export function useFileDrop(onDrop, { exts = [] } = {}) {
  const dragging = ref(false)
  let depth = 0
  const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes('Files')

  function pick(e) {
    const f = Array.from(e.dataTransfer?.files || [])[0] || null
    if (!f) return { file: null, reason: 'empty', name: '' }
    if (exts.length && !exts.some((x) => f.name.toLowerCase().endsWith(x))) {
      return { file: null, reason: 'ext', name: f.name }
    }
    return { file: f, reason: '', name: f.name }
  }
  function reset() { depth = 0; dragging.value = false }

  function onEnter(e) { if (!hasFiles(e)) return; e.preventDefault(); depth += 1; dragging.value = true }
  function onOver(e) { if (!hasFiles(e)) return; e.preventDefault() }
  function onLeave(e) { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) dragging.value = false }
  function onWinDrop(e) {
    if (!hasFiles(e)) return
    e.preventDefault()
    const wasDragging = dragging.value
    reset()
    if (onDrop && wasDragging) onDrop(pick(e), e)
  }

  onMounted(() => {
    window.addEventListener('dragenter', onEnter)
    window.addEventListener('dragover', onOver)
    window.addEventListener('dragleave', onLeave)
    window.addEventListener('drop', onWinDrop)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('dragenter', onEnter)
    window.removeEventListener('dragover', onOver)
    window.removeEventListener('dragleave', onLeave)
    window.removeEventListener('drop', onWinDrop)
  })
  return { dragging, pick, reset }
}
