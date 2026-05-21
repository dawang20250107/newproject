// 全局手指点击特效：在触点处生成一圈涟漪光斑
// 用法：页面 JS 中合并 data 与 onTapFx，根节点加 capture-bind:touchstart="onTapFx"
let _seq = 0

module.exports = {
  data: { tapSparks: [] },

  onTapFx(e) {
    const t = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0])
    if (!t) return
    const id = ++_seq
    this.setData({ tapSparks: this.data.tapSparks.concat({ id, x: t.clientX, y: t.clientY }) })
    setTimeout(() => {
      this.setData({ tapSparks: this.data.tapSparks.filter(s => s.id !== id) })
    }, 600)
  },
}
