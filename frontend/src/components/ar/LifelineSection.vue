<script setup>
/*
 * 生命线阶段区块 —— 工作台的一个可折叠"里程碑"。
 * 共享外壳：标题栏（图标/状态/计数/折叠）+ 关键字段插槽 + 附件 + 阶段内动态时间线。
 * 仅负责呈现与本地交互（折叠、行内编辑缓冲、拖拽态）；所有写操作通过 emit 上抛父级走 API。
 */
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  stage: { type: String, required: true },     // reconciliation | invoice | collection | dunning
  title: { type: String, required: true },
  icon: { type: String, default: '•' },         // emoji
  accent: { type: String, default: '#c96342' }, // 主色
  state: { type: String, default: 'pending' },  // done | active | partial | urgent | pending
  stateLabel: { type: String, default: '' },
  summary: { type: String, default: '' },        // 折叠时单行摘要
  activities: { type: Array, default: () => [] },
  attachments: { type: Array, default: () => [] },
  canWrite: { type: Boolean, default: false },
  defaultOpen: { type: Boolean, default: true },
})
const emit = defineEmits([
  'save-edit', 'delete-act', 'toggle-status',
  'upload', 'delete-att', 'compose', 'register',
])

const rootEl = ref(null)
const open = ref(props.defaultOpen)
function toggle() { open.value = !open.value }

// ── 阶段内动态行内编辑 ───────────────────────────────────────────────────────
const STATUSES = [
  { v: 'in_progress', l: '跟进中' },
  { v: 'pending', l: '待回复' },
  { v: 'resolved', l: '已解决' },
  { v: 'no_response', l: '无响应' },
]
const editingId = ref(null)
const editBuf = ref({ note: '', status: '', follow_up_date: '' })
function startEdit(act) {
  editingId.value = act.id
  editBuf.value = { note: act.note, status: act.status, follow_up_date: act.follow_up_date || '' }
}
function cancelEdit() { editingId.value = null }
function commitEdit(act) {
  if (!editBuf.value.note.trim()) return
  emit('save-edit', { act, ...editBuf.value })
  editingId.value = null
}

// ── 附件 ────────────────────────────────────────────────────────────────────
const imageAtts = computed(() => props.attachments.filter(a => a.is_image))
const fileAtts = computed(() => props.attachments.filter(a => !a.is_image))
const dragOver = ref(false)
const fileInp = ref(null)
function onDrop(e) { dragOver.value = false; const f = e.dataTransfer?.files?.[0]; if (f) emit('upload', f) }
function onPick(e) { const f = e.target.files[0]; if (f) emit('upload', f); e.target.value = '' }

// ── 工具 ────────────────────────────────────────────────────────────────────
const STATUS_COLOR = { in_progress: '#1565c0', pending: '#e8830c', resolved: '#2e7d32', no_response: '#9e9e9e' }
function statusColor(s) { return STATUS_COLOR[s] || '#888' }
function actIcon(t) { return { call: '📞', email: '📧', visit: '🚶', meeting: '💬', system: '⚙️', note: '📝', other: '💡' }[t] || '💬' }
function fmtTime(iso) { return iso ? iso.replace('T', ' ').slice(0, 16) : '' }
function fmtSize(b) {
  if (b == null) return ''
  if (b < 1024) return b + 'B'
  if (b < 1048576) return (b / 1024).toFixed(1) + 'KB'
  return (b / 1048576).toFixed(1) + 'MB'
}
function fileIcon(att) {
  const ext = (att.file_name || '').split('.').pop().toLowerCase()
  if (ext === 'pdf') return '📄'
  if (['xlsx', 'xls', 'csv'].includes(ext)) return '📊'
  if (['docx', 'doc'].includes(ext)) return '📝'
  return '📎'
}

onMounted(() => { emit('register', props.stage, rootEl.value, () => { open.value = true }) })
onBeforeUnmount(() => { emit('register', props.stage, null) })
</script>

<template>
  <section ref="rootEl" class="ls" :class="`ls-${state}`" :style="{ '--ac': accent }">
    <!-- 标题栏 -->
    <header class="ls-head" @click="toggle">
      <span class="ls-node" :class="`ls-node-${state}`">{{ icon }}</span>
      <span class="ls-title">{{ title }}</span>
      <span v-if="stateLabel" class="ls-state">{{ stateLabel }}</span>
      <span v-if="activities.length || attachments.length" class="ls-meta">
        <span v-if="activities.length" title="跟进动态">💬{{ activities.length }}</span>
        <span v-if="attachments.length" title="附件">📎{{ attachments.length }}</span>
      </span>
      <span v-if="!open && summary" class="ls-summary">{{ summary }}</span>
      <span class="ls-caret" :class="{ 'ls-caret-open': open }">⌃</span>
    </header>

    <!-- 展开内容 -->
    <transition name="ls-collapse">
      <div v-show="open" class="ls-body">
        <!-- 关键字段（父级提供）-->
        <div v-if="$slots.fields" class="ls-fields">
          <slot name="fields" />
        </div>

        <!-- 附件 -->
        <div v-if="attachments.length || canWrite" class="ls-atts">
          <div v-if="imageAtts.length" class="ls-img-grid">
            <div v-for="att in imageAtts" :key="att.id" class="ls-img-cell" :title="att.file_name">
              <a :href="att.download_url" target="_blank"><img :src="att.thumb_url || att.download_url" class="ls-img" :alt="att.file_name" /></a>
              <button v-if="canWrite" class="ls-img-del" title="删除" @click="emit('delete-att', att)">✕</button>
            </div>
          </div>
          <div v-for="att in fileAtts" :key="att.id" class="ls-file">
            <span class="ls-file-ico">{{ fileIcon(att) }}</span>
            <a :href="att.download_url" target="_blank" class="ls-file-name" :title="att.file_name">{{ att.file_name }}</a>
            <span class="ls-file-meta">{{ fmtSize(att.file_size) }}</span>
            <button v-if="canWrite" class="ls-file-del" title="删除" @click="emit('delete-att', att)">✕</button>
          </div>
          <div v-if="canWrite" class="ls-dz" :class="{ 'ls-dz-over': dragOver }"
            @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop.prevent="onDrop" @click="fileInp?.click()">
            {{ dragOver ? '松手上传' : '⬆ 上传附件' }}
            <input ref="fileInp" type="file" class="ls-dz-input"
              accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.xlsx,.xls,.docx,.doc,.txt,.csv" @change="onPick" />
          </div>
        </div>

        <!-- 阶段内动态 -->
        <div v-if="activities.length" class="ls-acts">
          <div v-for="act in activities" :key="act.id" class="ls-act" :style="{ '--sc': statusColor(act.status) }">
            <span class="ls-act-dot">{{ actIcon(act.act_type) }}</span>
            <div class="ls-act-main">
              <div class="ls-act-top">
                <span class="ls-act-who">{{ act.created_by_name || '—' }}</span>
                <button class="ls-act-status" @click="act.can_edit && emit('toggle-status', act)" :title="act.can_edit ? '点击切换状态' : ''">{{ act.status_display }}</button>
                <span class="ls-act-time">{{ fmtTime(act.created_at) }}</span>
                <template v-if="act.can_edit && editingId !== act.id">
                  <button class="ls-ico" title="编辑" @click="startEdit(act)">✏️</button>
                  <button class="ls-ico ls-ico-del" title="删除" @click="emit('delete-act', act)">🗑</button>
                </template>
              </div>
              <template v-if="editingId === act.id">
                <textarea v-model="editBuf.note" class="ls-edit-ta" rows="2"></textarea>
                <div class="ls-edit-foot">
                  <select v-model="editBuf.status" class="ls-sel">
                    <option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option>
                  </select>
                  <input v-model="editBuf.follow_up_date" type="date" class="ls-sel" />
                  <button class="ls-save" @click="commitEdit(act)">保存</button>
                  <button class="ls-cancel" @click="cancelEdit">取消</button>
                </div>
              </template>
              <template v-else>
                <div class="ls-act-note">{{ act.note }}</div>
                <div v-if="act.follow_up_date" class="ls-act-fu">📅 计划跟进 {{ act.follow_up_date }}</div>
              </template>
            </div>
          </div>
        </div>

        <!-- 在此阶段记录 -->
        <button v-if="canWrite" class="ls-compose" @click="emit('compose', stage)">＋ 在此阶段记录跟进</button>
      </div>
    </transition>
  </section>
</template>

<style scoped>
.ls { border: 1px solid rgba(180,140,110,.2); border-radius: 12px; background: #fff; overflow: hidden; transition: box-shadow .15s; }
.ls:hover { box-shadow: 0 2px 10px rgba(60,30,10,.06); }
.ls-urgent { border-color: rgba(198,40,40,.35); }

/* 标题栏 */
.ls-head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; cursor: pointer; user-select: none; }
.ls-head:hover { background: rgba(201,99,66,.03); }
.ls-node {
  width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; font-size: 13px;
  background: #f0e6dc; color: #a8917e;
}
.ls-node-done { background: linear-gradient(145deg, #66bb6a, #2e7d32); color: #fff; }
.ls-node-active { background: linear-gradient(145deg, #e07848, #c96342); color: #fff; }
.ls-node-partial { background: linear-gradient(145deg, #ffb74d, #f57c00); color: #fff; }
.ls-node-urgent { background: linear-gradient(145deg, #ef5350, #c62828); color: #fff; }
.ls-title { font-size: 13.5px; font-weight: 800; color: #5a4636; flex-shrink: 0; }
.ls-state {
  font-size: 10.5px; font-weight: 700; padding: 1px 8px; border-radius: 8px;
  color: var(--ac); background: color-mix(in srgb, var(--ac) 12%, transparent); flex-shrink: 0;
}
.ls-meta { display: flex; gap: 7px; font-size: 10.5px; color: #a8917e; flex-shrink: 0; }
.ls-summary { font-size: 11.5px; color: #b0987e; margin-left: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ls-caret { margin-left: auto; font-size: 13px; color: #c0ad9d; transition: transform .2s; transform: rotate(180deg); flex-shrink: 0; }
.ls-caret-open { transform: rotate(0deg); }

/* 折叠动画 */
.ls-collapse-enter-active, .ls-collapse-leave-active { transition: all .2s ease; overflow: hidden; }
.ls-collapse-enter-from, .ls-collapse-leave-to { opacity: 0; max-height: 0; }
.ls-collapse-enter-to, .ls-collapse-leave-from { opacity: 1; max-height: 1200px; }

.ls-body { padding: 0 12px 12px; display: flex; flex-direction: column; gap: 10px; }

/* 关键字段区 */
.ls-fields { display: flex; flex-direction: column; gap: 8px; padding: 10px 11px; background: #fbf7f1; border-radius: 9px; border: 1px solid rgba(180,140,110,.14); }

/* 附件 */
.ls-atts { display: flex; flex-direction: column; gap: 6px; }
.ls-img-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.ls-img-cell { position: relative; aspect-ratio: 1; border-radius: 7px; overflow: hidden; border: 1px solid rgba(180,140,110,.2); }
.ls-img { width: 100%; height: 100%; object-fit: cover; display: block; cursor: zoom-in; }
.ls-img-del { position: absolute; top: 2px; right: 2px; width: 17px; height: 17px; border: none; border-radius: 50%; background: rgba(0,0,0,.5); color: #fff; font-size: 9px; cursor: pointer; opacity: 0; transition: opacity .12s; line-height: 17px; padding: 0; }
.ls-img-cell:hover .ls-img-del { opacity: 1; }
.ls-file { display: flex; align-items: center; gap: 8px; background: #fbf7f1; border: 1px solid rgba(180,140,110,.16); border-radius: 8px; padding: 6px 10px; }
.ls-file-ico { font-size: 15px; flex-shrink: 0; }
.ls-file-name { flex: 1; min-width: 0; font-size: 12px; color: #1565c0; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ls-file-name:hover { text-decoration: underline; }
.ls-file-meta { font-size: 10px; color: #a8917e; flex-shrink: 0; }
.ls-file-del { border: none; background: none; color: #c0ad9d; font-size: 11px; cursor: pointer; flex-shrink: 0; }
.ls-file-del:hover { color: #c62828; }
.ls-dz { border: 1.5px dashed rgba(180,140,110,.35); border-radius: 8px; padding: 8px; text-align: center; font-size: 11px; color: #a8917e; cursor: pointer; transition: all .15s; position: relative; }
.ls-dz:hover, .ls-dz-over { background: rgba(201,99,66,.05); border-color: var(--ac); color: var(--ac); }
.ls-dz-input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }

/* 阶段内动态 */
.ls-acts { display: flex; flex-direction: column; gap: 7px; }
.ls-act { display: flex; gap: 9px; }
.ls-act-dot {
  width: 24px; height: 24px; flex-shrink: 0; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 12px;
  background: #fff; border: 2px solid var(--sc); box-shadow: 0 0 0 2px #fff, 0 1px 3px rgba(60,30,10,.1);
}
.ls-act-main { flex: 1; min-width: 0; background: #fbf7f1; border: 1px solid rgba(180,140,110,.15); border-left: 3px solid var(--sc); border-radius: 8px; padding: 6px 10px; }
.ls-act-top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ls-act-who { font-size: 11.5px; font-weight: 700; color: #5a4636; }
.ls-act-status { border: none; font-size: 10px; font-weight: 700; cursor: pointer; padding: 1px 7px; border-radius: 7px; color: var(--sc); background: color-mix(in srgb, var(--sc) 12%, transparent); }
.ls-act-time { font-size: 10px; color: #bda797; margin-left: auto; font-variant-numeric: tabular-nums; }
.ls-ico { border: none; background: none; font-size: 11px; cursor: pointer; padding: 1px 2px; border-radius: 4px; opacity: .7; }
.ls-ico:hover { opacity: 1; background: rgba(0,0,0,.05); }
.ls-act-note { font-size: 12.5px; color: #4a3a2c; white-space: pre-wrap; word-break: break-word; line-height: 1.5; margin-top: 2px; }
.ls-act-fu { font-size: 10.5px; color: #a8917e; margin-top: 2px; }
.ls-edit-ta { width: 100%; border: 1px solid rgba(201,99,66,.4); border-radius: 6px; padding: 5px 8px; font-size: 12.5px; color: #5a4636; resize: vertical; font-family: inherit; box-sizing: border-box; outline: none; margin-top: 4px; }
.ls-edit-foot { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; margin-top: 5px; }
.ls-sel { border: 1px solid rgba(180,140,110,.28); border-radius: 6px; font-size: 11.5px; padding: 3px 6px; color: #5a4636; background: #fff; outline: none; font-family: inherit; }
.ls-save { padding: 3px 12px; border: none; border-radius: 6px; background: var(--ac); color: #fff; font-size: 11.5px; font-weight: 700; cursor: pointer; margin-left: auto; }
.ls-cancel { padding: 3px 10px; border: 1px solid rgba(180,140,110,.3); border-radius: 6px; background: #fff; font-size: 11.5px; cursor: pointer; color: #8a7665; }

.ls-compose { border: 1px dashed rgba(201,99,66,.4); background: none; color: var(--ac); font-size: 11.5px; padding: 6px; border-radius: 8px; cursor: pointer; font-weight: 600; transition: background .12s; }
.ls-compose:hover { background: rgba(201,99,66,.05); }
</style>
