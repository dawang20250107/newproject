<template>
  <Teleport to="body">
    <template v-if="ctx.menu.show">
      <div class="ctxm-backdrop" @click="ctx.close" @contextmenu.prevent="ctx.close" @wheel="ctx.close"></div>
      <div ref="menuEl" class="ctxm" :style="{ left: pos.x + 'px', top: pos.y + 'px' }">
        <template v-for="(it, i) in visibleItems" :key="it.key || ('d' + i)">
          <div v-if="it.divider" class="ctxm-divider"></div>
          <div
            v-else-if="it.children && it.children.length"
            class="ctxm-item ctxm-has-sub"
            :class="{ disabled: it.disabled }"
            @mouseenter="onSubEnter($event, it.key)"
            @mouseleave="onSubLeave"
          >
            <span class="ctxm-ico" v-html="iconSvg(it.icon)"></span>
            <span class="ctxm-label">{{ it.label }}</span>
            <svg class="ctxm-caret" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><polyline points="9 6 15 12 9 18"/></svg>
            <div
              v-if="openSub === it.key"
              class="ctxm ctxm-sub"
              :style="subStyle"
              @mouseenter="keepSub"
              @mouseleave="onSubLeave"
            >
              <template v-for="(c, j) in (it.children || [])" :key="c.key || ('s' + j)">
                <div v-if="c.divider" class="ctxm-divider"></div>
                <button
                  v-else
                  class="ctxm-item"
                  :class="{ 'ctxm-danger': c.danger, disabled: c.disabled, active: c.active }"
                  :disabled="c.disabled"
                  @click="run(c)"
                >
                  <span class="ctxm-ico" v-html="iconSvg(c.icon)"></span>
                  <span class="ctxm-label">{{ c.label }}</span>
                  <svg v-if="c.active" class="ctxm-check" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                  <span v-else-if="c.shortcut" class="ctxm-kbd">{{ c.shortcut }}</span>
                </button>
              </template>
            </div>
          </div>
          <button
            v-else
            class="ctxm-item"
            :class="{ 'ctxm-danger': it.danger, disabled: it.disabled, active: it.active }"
            :disabled="it.disabled"
            @click="run(it)"
          >
            <span class="ctxm-ico" v-html="iconSvg(it.icon)"></span>
            <span class="ctxm-label">{{ it.label }}</span>
            <svg v-if="it.active" class="ctxm-check" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            <span v-else-if="it.shortcut" class="ctxm-kbd">{{ it.shortcut }}</span>
          </button>
        </template>
      </div>
    </template>
  </Teleport>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onBeforeUnmount } from 'vue'

const props = defineProps({
  ctx: { type: Object, required: true },
  items: { type: Array, default: () => [] },
})

const menuEl = ref(null)
const pos = reactive({ x: 0, y: 0 })
const openSub = ref(null)
const subStyle = ref({})
let subTimer = null

// 过滤掉 hidden 项，并收敛分隔线（去掉首尾分隔线、合并连续分隔线）。
const visibleItems = computed(() => {
  const src = (props.items || []).filter(it => it && !it.hidden)
  const out = []
  for (const it of src) {
    if (it.divider) {
      if (!out.length || out[out.length - 1].divider) continue
      out.push(it)
    } else {
      out.push(it)
    }
  }
  while (out.length && out[out.length - 1].divider) out.pop()
  return out
})

function run(it) {
  if (!it || it.disabled) return
  const payload = props.ctx.menu.payload
  props.ctx.close()
  if (typeof it.action === 'function') it.action(payload)
}

function onSubEnter(e, key) {
  clearTimeout(subTimer)
  openSub.value = key
  // 默认向右展开，空间不足时翻向左侧。
  nextTick(() => {
    const host = e.currentTarget
    if (!host) return
    const r = host.getBoundingClientRect()
    const wRight = window.innerWidth - r.right
    subStyle.value = wRight < 190
      ? { right: '100%', left: 'auto', top: '-5px' }
      : { left: '100%', right: 'auto', top: '-5px' }
  })
}
function keepSub() { clearTimeout(subTimer) }
function onSubLeave() {
  subTimer = setTimeout(() => { openSub.value = null }, 160)
}

function onKey(e) { if (e.key === 'Escape') props.ctx.close() }

watch(() => props.ctx.menu.show, (show) => {
  if (show) {
    openSub.value = null
    pos.x = props.ctx.menu.x
    pos.y = props.ctx.menu.y
    document.addEventListener('keydown', onKey)
    nextTick(() => {
      const el = menuEl.value
      if (!el) return
      const r = el.getBoundingClientRect()
      const pad = 8
      if (props.ctx.menu.x + r.width > window.innerWidth - pad)
        pos.x = Math.max(pad, window.innerWidth - r.width - pad)
      if (props.ctx.menu.y + r.height > window.innerHeight - pad)
        pos.y = Math.max(pad, window.innerHeight - r.height - pad)
    })
  } else {
    document.removeEventListener('keydown', onKey)
  }
})

onBeforeUnmount(() => {
  clearTimeout(subTimer)
  document.removeEventListener('keydown', onKey)
})

// ── 图标库（内联 SVG，按名取用）─────────────────────────────────────
const ICONS = {
  log:      '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  edit:     '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4z"/>',
  payment:  '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>',
  trash:    '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/>',
  copy:     '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  cell:     '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="9" x2="9" y2="21"/>',
  export:   '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  link:     '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  history:  '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><polyline points="12 7 12 12 15 15"/>',
  flag:     '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>',
  status:   '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  refresh:  '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  customer: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  plus:     '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  eye:      '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/>',
  bell:     '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  project:  '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  chart:    '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
  invoice:  '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/>',
  ban:      '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>',
}
function iconSvg(name) {
  const inner = ICONS[name]
  if (!inner) return ''
  return `<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}
</script>

<style scoped>
.ctxm-backdrop { position: fixed; inset: 0; z-index: 600; }
.ctxm {
  position: fixed; z-index: 601;
  background: #fff; border: 1px solid var(--border); border-radius: 10px;
  box-shadow: 0 10px 32px rgba(0,0,0,0.18); min-width: 168px; padding: 5px 0;
  user-select: none;
}
.ctxm-sub { position: absolute; }
.ctxm-item {
  display: flex; align-items: center; gap: 9px;
  width: 100%; padding: 7px 13px; border: none; background: none;
  font-size: 13px; color: var(--text); cursor: pointer; text-align: left;
  transition: background .1s; position: relative;
}
.ctxm-item:hover { background: rgba(201,99,66,0.07); }
.ctxm-item.disabled { color: var(--muted); opacity: .55; cursor: default; pointer-events: none; }
.ctxm-item.active { font-weight: 600; }
.ctxm-ico { flex-shrink: 0; display: inline-flex; color: var(--muted); width: 13px; }
.ctxm-label { flex: 1; white-space: nowrap; }
.ctxm-kbd {
  flex-shrink: 0; margin-left: 14px; font-size: 11px; color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .3px;
  border: 1px solid var(--border); border-radius: 4px; padding: 0 5px; line-height: 16px;
}
.ctxm-check { flex-shrink: 0; margin-left: 12px; color: var(--primary); }
.ctxm-caret { flex-shrink: 0; margin-left: 8px; color: var(--muted); }
.ctxm-danger { color: #c62828; }
.ctxm-danger .ctxm-ico { color: #c62828; }
.ctxm-danger:hover { background: rgba(198,40,40,0.08); }
.ctxm-divider { height: 1px; background: var(--border); margin: 4px 0; }
.ctxm-has-sub { cursor: default; }
.ctxm-has-sub:hover { background: rgba(201,99,66,0.07); }
</style>
