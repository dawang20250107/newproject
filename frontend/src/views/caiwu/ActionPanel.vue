<script setup>
import { ref, computed, onMounted } from 'vue'
import ar from '../../api/ar.js'

const props = defineProps({
  embedded: Boolean,
  selectedBu: { type: String, default: '' },
})
const emit = defineEmits(['count-change'])

const items = ref([])
const counts = ref({ open: 0, in_progress: 0, done: 0, dismissed: 0 })
const loading = ref(false)
const err = ref('')
const filterStatus = ref('')
const filterBu = ref('')
const toast = ref('')
let toastTimer = null

const editItem = ref(null)   // item being edited in modal
const editForm = ref({})
const showForm = ref(false)  // new-item form

const newForm = ref({ title: '', description: '', bu: '', priority: 'medium', assignee: '', due_date: '' })

function showToast(msg) {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2200)
}

async function load() {
  loading.value = true; err.value = ''
  try {
    const p = {}
    if (filterStatus.value) p.status = filterStatus.value
    if (filterBu.value) p.bu = filterBu.value
    else if (props.selectedBu) p.bu = props.selectedBu
    const res = await ar.listActions(p)
    items.value = res.data.items
    counts.value = res.data.counts
    emit('count-change', counts.value)
  } catch (e) {
    err.value = e?.error || '加载失败'
  } finally {
    loading.value = false }
}

async function createItem() {
  const t = newForm.value.title.trim()
  if (!t) return showToast('标题不能为空')
  try {
    await ar.createAction({ ...newForm.value, bu: newForm.value.bu || props.selectedBu })
    showForm.value = false
    newForm.value = { title: '', description: '', bu: '', priority: 'medium', assignee: '', due_date: '' }
    await load()
    showToast('✓ 已创建')
  } catch (e) { showToast(e?.error || '创建失败') }
}

function startEdit(item) {
  editItem.value = item
  editForm.value = { ...item }
}

async function saveEdit() {
  try {
    await ar.updateAction(editItem.value.id, editForm.value)
    editItem.value = null
    await load()
    showToast('✓ 已保存')
  } catch (e) { showToast(e?.error || '保存失败') }
}

async function setStatus(item, status) {
  try {
    await ar.updateAction(item.id, { status })
    item.status = status
    await load()
  } catch (e) { showToast(e?.error || '更新失败') }
}

async function deleteItem(item) {
  if (!confirm(`确认删除「${item.title}」？`)) return
  try {
    await ar.deleteAction(item.id)
    await load()
    showToast('已删除')
  } catch (e) { showToast(e?.error || '删除失败') }
}

const PRIORITY_LABEL = { high: '高', medium: '中', low: '低' }
const PRIORITY_COLOR = { high: '#c62828', medium: '#e65100', low: '#2e7d32' }
const STATUS_LABEL = { open: '待处理', in_progress: '处理中', done: '已完成', dismissed: '已忽略' }
const STATUS_ICON = { open: '🔴', in_progress: '🟡', done: '✅', dismissed: '⬜' }

const columns = computed(() => [
  { key: 'open', label: '待处理', icon: '🔴', items: items.value.filter(i => i.status === 'open') },
  { key: 'in_progress', label: '处理中', icon: '🟡', items: items.value.filter(i => i.status === 'in_progress') },
  { key: 'done', label: '已完成', icon: '✅', items: items.value.filter(i => i.status === 'done') },
])

function nextStatus(item) {
  const map = { open: 'in_progress', in_progress: 'done', done: 'open', dismissed: 'open' }
  return map[item.status] || 'open'
}
function nextStatusLabel(item) {
  const map = { open: '→开始处理', in_progress: '→标记完成', done: '→重新打开', dismissed: '→重新打开' }
  return map[item.status] || '→待处理'
}

onMounted(load)
</script>

<template>
  <div class="action-panel">
    <div class="ap-head">
      <div class="ap-title">📋 行动项看板</div>
      <div class="ap-controls">
        <select v-model="filterStatus" class="ap-sel" @change="load">
          <option value="">全部状态</option>
          <option v-for="(l, k) in STATUS_LABEL" :key="k" :value="k">{{ l }}</option>
        </select>
        <button class="ap-btn-add" @click="showForm = !showForm">+ 新建行动项</button>
      </div>
    </div>

    <!-- counts chips -->
    <div class="ap-count-row">
      <span v-for="(label, key) in STATUS_LABEL" :key="key" class="ap-chip" :class="`ap-chip-${key}`">
        {{ label }} <b>{{ counts[key] || 0 }}</b>
      </span>
    </div>

    <!-- new item form -->
    <div v-if="showForm" class="ap-form card">
      <div class="af-row">
        <input v-model="newForm.title" class="af-input" placeholder="行动标题（必填）" />
        <select v-model="newForm.priority" class="ap-sel">
          <option value="high">高优</option>
          <option value="medium">中优</option>
          <option value="low">低优</option>
        </select>
      </div>
      <div class="af-row">
        <input v-model="newForm.assignee" class="af-input" placeholder="负责人" />
        <input v-model="newForm.due_date" type="date" class="af-input" />
      </div>
      <textarea v-model="newForm.description" class="af-textarea" rows="2" placeholder="描述（可选）" />
      <div class="af-actions">
        <button class="ap-btn-add" @click="createItem">保存</button>
        <button class="ap-btn-cancel" @click="showForm = false">取消</button>
      </div>
    </div>

    <div v-if="loading" class="ap-empty">加载中…</div>
    <div v-else-if="err" class="ap-empty err">{{ err }}</div>

    <!-- kanban columns -->
    <div v-else class="ap-kanban">
      <div v-for="col in columns" :key="col.key" class="ap-col">
        <div class="ap-col-head">{{ col.icon }} {{ col.label }} <span class="ap-col-count">{{ col.items.length }}</span></div>
        <div v-if="!col.items.length" class="ap-col-empty">暂无</div>
        <div v-for="item in col.items" :key="item.id" class="ap-card">
          <div class="apc-top">
            <span class="apc-priority" :style="`color:${PRIORITY_COLOR[item.priority]}`">{{ PRIORITY_LABEL[item.priority] }}优</span>
            <span v-if="item.bu" class="apc-bu">{{ item.bu }}</span>
            <span class="apc-cat muted">{{ item.category || '' }}</span>
          </div>
          <div class="apc-title">{{ item.title }}</div>
          <div v-if="item.description" class="apc-desc">{{ item.description }}</div>
          <div class="apc-meta">
            <span v-if="item.assignee">👤 {{ item.assignee }}</span>
            <span v-if="item.due_date" :class="{ overdue: new Date(item.due_date) < new Date() && item.status !== 'done' }">
              📅 {{ item.due_date }}
            </span>
          </div>
          <div class="apc-actions">
            <button class="apc-btn-status" @click="setStatus(item, nextStatus(item))">{{ nextStatusLabel(item) }}</button>
            <button class="apc-btn-edit" @click="startEdit(item)">编辑</button>
            <button class="apc-btn-del" @click="deleteItem(item)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- dismissed items collapsed -->
    <details v-if="items.filter(i=>i.status==='dismissed').length" class="ap-dismissed">
      <summary>已忽略 {{ items.filter(i=>i.status==='dismissed').length }} 条</summary>
      <div v-for="item in items.filter(i=>i.status==='dismissed')" :key="item.id" class="ap-card ap-card-dim">
        <span class="apc-title">{{ item.title }}</span>
        <button class="apc-btn-status" @click="setStatus(item, 'open')">→重新打开</button>
      </div>
    </details>

    <!-- edit modal -->
    <Teleport to="body">
      <div v-if="editItem" class="ap-modal-mask" @click.self="editItem = null">
        <div class="ap-modal">
          <div class="ap-modal-title">编辑行动项</div>
          <div class="af-row">
            <input v-model="editForm.title" class="af-input" placeholder="标题" />
            <select v-model="editForm.priority" class="ap-sel">
              <option value="high">高优</option>
              <option value="medium">中优</option>
              <option value="low">低优</option>
            </select>
          </div>
          <div class="af-row">
            <input v-model="editForm.assignee" class="af-input" placeholder="负责人" />
            <input v-model="editForm.due_date" type="date" class="af-input" />
          </div>
          <div class="af-row">
            <select v-model="editForm.status" class="ap-sel">
              <option v-for="(l, k) in STATUS_LABEL" :key="k" :value="k">{{ l }}</option>
            </select>
          </div>
          <textarea v-model="editForm.description" class="af-textarea" rows="3" />
          <div class="af-actions">
            <button class="ap-btn-add" @click="saveEdit">保存</button>
            <button class="ap-btn-cancel" @click="editItem = null">取消</button>
          </div>
        </div>
      </div>
    </Teleport>

    <div v-if="toast" class="ap-toast">{{ toast }}</div>
  </div>
</template>

<style scoped>
.action-panel { padding: 16px 0; }
.ap-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.ap-title { font-size: 16px; font-weight: 700; color: #4a3728; }
.ap-controls { display: flex; gap: 8px; align-items: center; }
.ap-sel { padding: 4px 8px; border: 1px solid #d4b896; border-radius: 6px; background: #faf8f5; font-size: 13px; color: #4a3728; }
.ap-btn-add { padding: 5px 14px; background: #2e7d32; color: #fff; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }
.ap-btn-add:hover { background: #1b5e20; }
.ap-btn-cancel { padding: 5px 14px; background: #e8e0d8; color: #4a3728; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; }

.ap-count-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.ap-chip { padding: 3px 10px; border-radius: 12px; font-size: 12px; }
.ap-chip-open { background: #fce4e4; color: #c62828; }
.ap-chip-in_progress { background: #fff3e0; color: #e65100; }
.ap-chip-done { background: #e8f5e9; color: #2e7d32; }
.ap-chip-dismissed { background: #f3f3f3; color: #9e9e9e; }

.ap-form { padding: 14px; margin-bottom: 14px; background: #fefcf9; border: 1px solid #e2d5c3; border-radius: 10px; }
.af-row { display: flex; gap: 8px; margin-bottom: 8px; }
.af-input { flex: 1; padding: 6px 10px; border: 1px solid #d4b896; border-radius: 6px; font-size: 13px; }
.af-textarea { width: 100%; padding: 6px 10px; border: 1px solid #d4b896; border-radius: 6px; font-size: 13px; box-sizing: border-box; resize: vertical; }
.af-actions { display: flex; gap: 8px; margin-top: 8px; }

.ap-kanban { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.ap-col { background: #f7f3ef; border-radius: 10px; padding: 10px; min-height: 200px; }
.ap-col-head { font-weight: 700; font-size: 13px; color: #4a3728; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
.ap-col-count { background: #e2d5c3; border-radius: 10px; padding: 0 7px; font-size: 11px; }
.ap-col-empty { color: #9e9e9e; font-size: 13px; text-align: center; padding: 20px 0; }

.ap-card { background: #fff; border-radius: 8px; padding: 10px; margin-bottom: 8px; border: 1px solid #e8ddd0; box-shadow: 0 1px 3px rgba(0,0,0,.05); }
.ap-card-dim { opacity: 0.6; }
.apc-top { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
.apc-priority { font-size: 11px; font-weight: 700; }
.apc-bu { font-size: 11px; background: #e3f2fd; color: #1565c0; border-radius: 4px; padding: 0 6px; }
.apc-cat { font-size: 11px; }
.apc-title { font-size: 13px; font-weight: 600; color: #2d2010; margin-bottom: 4px; line-height: 1.4; }
.apc-desc { font-size: 12px; color: #6b5a4a; margin-bottom: 6px; }
.apc-meta { font-size: 11px; color: #8a7060; display: flex; gap: 10px; margin-bottom: 6px; }
.overdue { color: #c62828 !important; font-weight: 700; }
.apc-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.apc-btn-status { font-size: 11px; padding: 2px 8px; background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; border-radius: 4px; cursor: pointer; white-space: nowrap; }
.apc-btn-edit { font-size: 11px; padding: 2px 8px; background: #e3f2fd; color: #1565c0; border: 1px solid #90caf9; border-radius: 4px; cursor: pointer; }
.apc-btn-del { font-size: 11px; padding: 2px 8px; background: #fce4e4; color: #c62828; border: 1px solid #ef9a9a; border-radius: 4px; cursor: pointer; }

.ap-dismissed { margin-top: 16px; color: #9e9e9e; font-size: 13px; }
.ap-dismissed summary { cursor: pointer; margin-bottom: 6px; }

.ap-empty { text-align: center; padding: 40px; color: #9e9e9e; }
.ap-empty.err { color: #c62828; }

.ap-modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 4000; display: flex; align-items: center; justify-content: center; }
.ap-modal { background: #fff; border-radius: 14px; padding: 24px; width: 440px; max-width: 95vw; box-shadow: 0 20px 60px rgba(0,0,0,.25); }
.ap-modal-title { font-size: 16px; font-weight: 700; color: #4a3728; margin-bottom: 16px; }

.ap-toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: #2e7d32; color: #fff; padding: 8px 20px; border-radius: 20px; font-size: 13px; z-index: 5000; pointer-events: none; }

.muted { color: #9b8070; }
@media (max-width: 768px) {
  .ap-kanban { grid-template-columns: 1fr; }
}
</style>
