<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api/index.js'

const router = useRouter()
const open = ref(false)
const loading = ref(false)
const items = ref([])
const unread = ref(0)
let pollTimer = null

const LEVEL_ICON = { info: 'ℹ', warn: '⚠', danger: '🔔' }

async function fetchUnread() {
  try {
    const r = await api.get('/notifications/unread-count')
    unread.value = r.data?.unread || 0
  } catch { /* 静默：徽标轮询失败不打扰用户 */ }
}

async function fetchList() {
  loading.value = true
  try {
    const r = await api.get('/notifications', { params: { size: 30 } })
    items.value = r.data?.items || []
    unread.value = r.data?.unread || 0
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function toggle() {
  open.value = !open.value
  if (open.value) fetchList()
}

async function markAllRead() {
  try {
    await api.post('/notifications/read', { all: true })
    items.value = items.value.map(n => ({ ...n, is_read: true }))
    unread.value = 0
  } catch { /* ignore */ }
}

async function onClickItem(n) {
  if (!n.is_read) {
    try {
      await api.post('/notifications/read', { ids: [n.id] })
      n.is_read = true
      unread.value = Math.max(0, unread.value - 1)
    } catch { /* ignore */ }
  }
  open.value = false
  if (n.link) router.push(n.link)
}

function onDocClick(e) {
  if (!open.value) return
  const root = document.querySelector('.nbell-anchor')
  if (root && !root.contains(e.target)) open.value = false
}

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400 && d.getDate() === now.getDate()) return `今天 ${d.toTimeString().slice(0, 5)}`
  return `${d.getMonth() + 1}/${d.getDate()} ${d.toTimeString().slice(0, 5)}`
}

onMounted(() => {
  fetchUnread()
  pollTimer = setInterval(fetchUnread, 60000)
  document.addEventListener('mousedown', onDocClick)
})
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  document.removeEventListener('mousedown', onDocClick)
})
</script>

<template>
  <div class="nbell-anchor">
    <button class="nbell-btn" :class="{ 'has-unread': unread > 0 }" @click="toggle" title="通知中心">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
      </svg>
      <span v-if="unread > 0" class="nbell-badge">{{ unread > 99 ? '99+' : unread }}</span>
    </button>

    <Transition name="nbell-pop">
      <div v-if="open" class="nbell-panel">
        <div class="nbell-head">
          <span class="nbell-title">通知中心</span>
          <button v-if="unread > 0" class="nbell-readall" @click="markAllRead">全部已读</button>
        </div>
        <div class="nbell-body">
          <div v-if="loading" class="nbell-empty">加载中…</div>
          <div v-else-if="!items.length" class="nbell-empty">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" style="color:var(--muted-light);margin-bottom:8px">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
            </svg>
            <div>暂无通知，待办都处理完啦</div>
          </div>
          <ul v-else class="nbell-list">
            <li v-for="n in items" :key="n.id" class="nbell-item" :class="[`lv-${n.level}`, { unread: !n.is_read }]"
                @click="onClickItem(n)">
              <span class="nbell-dot"></span>
              <div class="nbell-main">
                <div class="nbell-itop">
                  <span class="nbell-itag" :class="`tag-${n.level}`">{{ n.kind_label }}</span>
                  <span class="nbell-itime">{{ fmtTime(n.created_at) }}</span>
                </div>
                <div class="nbell-ititle">{{ n.title }}</div>
                <div class="nbell-ibody">{{ n.body }}</div>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.nbell-anchor { position: fixed; top: 14px; right: 18px; z-index: 240; }
.nbell-btn {
  position: relative; width: 42px; height: 42px; border-radius: 12px;
  background: rgba(255,253,250,0.92); border: 1px solid var(--border);
  color: var(--text-2); display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: all 0.16s; box-shadow: var(--shadow-sm);
  backdrop-filter: blur(8px);
}
.nbell-btn:hover { color: var(--primary); border-color: var(--primary); transform: translateY(-1px); }
.nbell-btn.has-unread { color: var(--primary); }
.nbell-badge {
  position: absolute; top: -5px; right: -5px; min-width: 18px; height: 18px;
  padding: 0 5px; border-radius: 9px; background: var(--c-danger); color: #fff;
  font-size: 11px; font-weight: 700; line-height: 18px; text-align: center;
  box-shadow: 0 1px 4px rgba(198,40,40,0.4); border: 1.5px solid #fff;
}

.nbell-panel {
  position: absolute; top: 50px; right: 0; width: 360px; max-width: 92vw;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 14px; box-shadow: var(--shadow-lg); overflow: hidden;
  backdrop-filter: blur(20px);
}
.nbell-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border-soft);
}
.nbell-title { font-size: 14px; font-weight: 700; color: var(--text); }
.nbell-readall { border: none; background: none; color: var(--primary); font-size: 12.5px; cursor: pointer; }
.nbell-readall:hover { text-decoration: underline; }
.nbell-body { max-height: min(60vh, 460px); overflow-y: auto; }
.nbell-empty { text-align: center; padding: 40px 20px; color: var(--muted); font-size: 13px;
  display: flex; flex-direction: column; align-items: center; }
.nbell-list { list-style: none; margin: 0; padding: 0; }
.nbell-item {
  display: flex; gap: 10px; padding: 11px 16px; cursor: pointer;
  border-bottom: 1px solid var(--border-soft); transition: background 0.13s;
}
.nbell-item:hover { background: rgba(201,99,66,0.04); }
.nbell-item:last-child { border-bottom: none; }
.nbell-dot { width: 7px; height: 7px; border-radius: 50%; margin-top: 6px; flex-shrink: 0; background: transparent; }
.nbell-item.unread .nbell-dot { background: var(--primary); }
.nbell-item.unread { background: rgba(201,99,66,0.028); }
.nbell-main { flex: 1; min-width: 0; }
.nbell-itop { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 3px; }
.nbell-itag { font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: 6px; }
.tag-info { color: var(--c-info); background: var(--c-info-bg); }
.tag-warn { color: var(--c-warn); background: var(--c-warn-bg); }
.tag-danger { color: var(--c-danger); background: var(--c-danger-bg); }
.nbell-itime { font-size: 11px; color: var(--muted); white-space: nowrap; }
.nbell-ititle { font-size: 13px; font-weight: 600; color: var(--text); line-height: 1.4; }
.nbell-ibody { font-size: 12px; color: var(--text-2); line-height: 1.5; margin-top: 1px; }

.nbell-pop-enter-active, .nbell-pop-leave-active { transition: opacity 0.16s, transform 0.16s; }
.nbell-pop-enter-from, .nbell-pop-leave-to { opacity: 0; transform: translateY(-8px); }

@media (max-width: 768px) {
  .nbell-anchor { top: 12px; right: 12px; }
  .nbell-btn { width: 40px; height: 40px; }
  /* 避让移动端右上角，但左上角是汉堡菜单，铃铛在右上不冲突 */
}
</style>
