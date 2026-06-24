<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import ar from '../../api/ar.js'
import { useToast } from '../../composables/useToast.js'

const props = defineProps({
  rec: { type: Object, required: true },   // AR record object
})
const emit = defineEmits(['close', 'field-saved'])

const toast = useToast()

// ── 数据 ──────────────────────────────────────────────────────────────────
const loading = ref(false)
const activities = ref([])
const attachments = ref([])
const activeStage = ref('')  // '' = all stages

const STAGES = [
  { v: '', l: '全部' },
  { v: 'reconciliation', l: '对账' },
  { v: 'invoice', l: '开票' },
  { v: 'collection', l: '回款' },
  { v: 'dunning', l: '催款' },
]

async function load() {
  loading.value = true
  try {
    const res = await ar.listActivity(props.rec.id, activeStage.value ? { stage: activeStage.value } : {})
    activities.value = res.data.activities || []
    attachments.value = res.data.attachments || []
  } catch (e) {
    toast.error('加载失败')
  } finally {
    loading.value = false
  }
}

watch(() => props.rec?.id, (id) => { if (id) load() }, { immediate: true })
watch(activeStage, load)

// ── 快速编辑 ──────────────────────────────────────────────────────────────
const editCollector = ref(false)
const editTargetDate = ref(false)
const editNotes = ref(false)
const quickFields = reactive({
  collector: '',
  target_collection_date: '',
  notes: '',
})

watch(() => props.rec, (r) => {
  if (r) {
    quickFields.collector = r.collector || ''
    quickFields.target_collection_date = r.target_collection_date || ''
    quickFields.notes = r.notes || ''
  }
}, { immediate: true })

async function saveQuickField(field) {
  try {
    await ar.quickEdit(props.rec.id, { [field]: quickFields[field] })
    emit('field-saved', { id: props.rec.id, [field]: quickFields[field] })
    toast.success('已保存')
  } catch (e) {
    toast.error('保存失败')
  }
  editCollector.value = false
  editTargetDate.value = false
  editNotes.value = false
}

// ── 新增动态 ──────────────────────────────────────────────────────────────
const ACT_TYPES = [
  { v: 'call', l: '📞', title: '电话' },
  { v: 'email', l: '📧', title: '邮件' },
  { v: 'visit', l: '🚶', title: '拜访' },
  { v: 'meeting', l: '💬', title: '会议' },
  { v: 'note', l: '📝', title: '备注' },
]
const STATUSES = [
  { v: 'in_progress', l: '跟进中' },
  { v: 'pending', l: '待回复' },
  { v: 'resolved', l: '已解决' },
  { v: 'no_response', l: '无响应' },
]
const addForm = reactive({
  act_type: 'call',
  stage: 'dunning',
  contact_person: '',
  note: '',
  status: 'in_progress',
  follow_up_date: '',
})
const adding = ref(false)
const noteRef = ref(null)

async function submitAdd() {
  if (!addForm.note.trim()) { toast.error('请填写内容'); return }
  adding.value = true
  try {
    const res = await ar.addActivity(props.rec.id, { ...addForm })
    activities.value.unshift(res.data)
    emit('field-saved', { id: props.rec.id, activity_count: (props.rec.activity_count || 0) + 1 })
    addForm.note = ''
    addForm.contact_person = ''
    addForm.follow_up_date = ''
    toast.success('已记录')
  } catch (e) {
    toast.error(e?.response?.data?.msg || '提交失败')
  } finally {
    adding.value = false
  }
}

// ── 编辑 / 删除动态 ────────────────────────────────────────────────────────
const editingId = ref(null)
const editBuf = reactive({ note: '', status: '', follow_up_date: '' })

function startEdit(act) {
  editingId.value = act.id
  editBuf.note = act.note
  editBuf.status = act.status
  editBuf.follow_up_date = act.follow_up_date || ''
}
function cancelEdit() { editingId.value = null }

async function saveEdit(act) {
  if (!editBuf.note.trim()) { toast.error('内容不能为空'); return }
  try {
    const res = await ar.updateActivity(props.rec.id, act.id, {
      note: editBuf.note,
      status: editBuf.status,
      follow_up_date: editBuf.follow_up_date || null,
    })
    const idx = activities.value.findIndex(a => a.id === act.id)
    if (idx !== -1) activities.value[idx] = res.data
    editingId.value = null
    toast.success('已更新')
  } catch (e) {
    toast.error('更新失败')
  }
}

async function deleteAct(act) {
  if (!confirm(`删除这条${act.act_type_display}记录？`)) return
  try {
    await ar.deleteActivity(props.rec.id, act.id)
    activities.value = activities.value.filter(a => a.id !== act.id)
    emit('field-saved', { id: props.rec.id, activity_count: Math.max(0, (props.rec.activity_count || 1) - 1) })
    toast.success('已删除')
  } catch (e) {
    toast.error('删除失败')
  }
}

// ── 状态原地切换 ────────────────────────────────────────────────────────────
async function toggleStatus(act) {
  const order = ['in_progress', 'pending', 'resolved', 'no_response']
  const cur = order.indexOf(act.status)
  const next = order[(cur + 1) % order.length]
  try {
    const res = await ar.updateActivity(props.rec.id, act.id, { note: act.note, status: next })
    const idx = activities.value.findIndex(a => a.id === act.id)
    if (idx !== -1) activities.value[idx] = res.data
  } catch (e) {
    toast.error('状态切换失败')
  }
}

// ── 附件上传 ──────────────────────────────────────────────────────────────
const uploading = ref(false)
const dragOver = ref(false)
const fileInputRef = ref(null)
const uploadStage = ref('general')

async function uploadFile(file) {
  if (!file) return
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  const allowed = ['.jpg','.jpeg','.png','.gif','.webp','.pdf','.xlsx','.xls','.docx','.doc','.txt','.csv']
  if (!allowed.includes(ext)) {
    toast.error(`不支持 ${ext} 格式。支持：图片/PDF/Excel/Word/CSV/TXT`)
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    toast.error('文件不能超过 20MB')
    return
  }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('stage', uploadStage.value)
    const res = await ar.uploadAttachment(props.rec.id, fd)
    attachments.value.unshift(res.data)
    emit('field-saved', { id: props.rec.id, attachment_count: (props.rec.attachment_count || 0) + 1 })
    toast.success(`已上传：${file.name}`)
  } catch (e) {
    toast.error(e?.response?.data?.msg || '上传失败')
  } finally {
    uploading.value = false
  }
}

function onFileInput(e) { uploadFile(e.target.files[0]); e.target.value = '' }
function onDrop(e) {
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) uploadFile(f)
}

// Ctrl+V paste image
function onPaste(e) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) {
        const name = `clipboard-${Date.now()}.png`
        uploadFile(new File([f], name, { type: f.type }))
        e.preventDefault()
        break
      }
    }
  }
}

async function deleteAtt(att) {
  if (!confirm(`删除附件「${att.file_name}」？`)) return
  try {
    await ar.deleteAttachment(props.rec.id, att.id)
    attachments.value = attachments.value.filter(a => a.id !== att.id)
    emit('field-saved', { id: props.rec.id, attachment_count: Math.max(0, (props.rec.attachment_count || 1) - 1) })
    toast.success('已删除')
  } catch (e) {
    toast.error('删除失败')
  }
}

// ── 工具函数 ──────────────────────────────────────────────────────────────
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + 'KB'
  return (bytes / 1048576).toFixed(1) + 'MB'
}
function fmtTime(iso) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 16)
}
function fileIcon(att) {
  if (att.is_image) return '🖼'
  const ext = att.file_name.split('.').pop().toLowerCase()
  if (ext === 'pdf') return '📄'
  if (['xlsx','xls'].includes(ext)) return '📊'
  if (['docx','doc'].includes(ext)) return '📝'
  return '📎'
}
function statusColor(s) {
  return { in_progress: '#1565c0', pending: '#f9a825', resolved: '#2e7d32', no_response: '#9e9e9e' }[s] || '#666'
}
function actIcon(type) {
  return { call: '📞', email: '📧', visit: '🚶', meeting: '💬', system: '⚙', note: '📝', other: '💡' }[type] || '💬'
}

onMounted(() => document.addEventListener('paste', onPaste))
onBeforeUnmount(() => document.removeEventListener('paste', onPaste))
</script>

<template>
  <Teleport to="body">
    <div class="ap-backdrop" @click.self="emit('close')"></div>
    <div class="ap-panel">
      <!-- 头部 -->
      <div class="ap-header">
        <div class="ap-title">
          <span class="ap-proj">{{ rec.short_name || rec.customer_name }}</span>
          <span class="ap-sub">{{ rec.customer_name }}</span>
        </div>
        <button class="ap-close" @click="emit('close')">✕</button>
      </div>

      <!-- 快速编辑 -->
      <div class="ap-quick">
        <div class="ap-qrow">
          <span class="ap-qlabel">催收人</span>
          <template v-if="editCollector">
            <input v-model="quickFields.collector" class="ap-qinput" placeholder="姓名"
              @blur="saveQuickField('collector')" @keyup.enter="saveQuickField('collector')" @keyup.escape="editCollector=false" autofocus />
          </template>
          <span v-else class="ap-qval" :class="{ 'ap-qval--empty': !quickFields.collector }" @click="editCollector=true">
            {{ quickFields.collector || '点击设置' }}
          </span>
        </div>
        <div class="ap-qrow">
          <span class="ap-qlabel">目标回款</span>
          <template v-if="editTargetDate">
            <input v-model="quickFields.target_collection_date" type="date" class="ap-qinput"
              @blur="saveQuickField('target_collection_date')" @keyup.enter="saveQuickField('target_collection_date')" @keyup.escape="editTargetDate=false" autofocus />
          </template>
          <span v-else class="ap-qval" :class="{ 'ap-qval--empty': !quickFields.target_collection_date }" @click="editTargetDate=true">
            {{ quickFields.target_collection_date || '点击设置' }}
          </span>
        </div>
        <div class="ap-qrow ap-qrow--notes">
          <span class="ap-qlabel">备注</span>
          <template v-if="editNotes">
            <textarea v-model="quickFields.notes" class="ap-qta" rows="2"
              @blur="saveQuickField('notes')" @keyup.escape="editNotes=false" autofocus></textarea>
          </template>
          <span v-else class="ap-qval ap-qval--notes" :class="{ 'ap-qval--empty': !quickFields.notes }" @click="editNotes=true">
            {{ quickFields.notes || '点击添加备注' }}
          </span>
        </div>
      </div>

      <!-- 阶段筛选 tabs -->
      <div class="ap-tabs">
        <button v-for="s in STAGES" :key="s.v" class="ap-tab" :class="{ on: activeStage === s.v }" @click="activeStage = s.v">
          {{ s.l }}
        </button>
      </div>

      <div class="ap-body" v-if="!loading">

        <!-- 快速录入动态 -->
        <div class="ap-add-form">
          <div class="ap-type-chips">
            <button v-for="t in ACT_TYPES" :key="t.v" class="ap-type-chip"
              :class="{ on: addForm.act_type === t.v }" :title="t.title" @click="addForm.act_type = t.v">
              {{ t.l }}
            </button>
            <select v-model="addForm.stage" class="ap-stage-sel">
              <option v-for="s in STAGES.slice(1)" :key="s.v" :value="s.v">{{ s.l }}</option>
            </select>
          </div>
          <textarea ref="noteRef" v-model="addForm.note" class="ap-add-ta" rows="2"
            placeholder="跟进内容…（Ctrl+Enter 保存）"
            @keydown.ctrl.enter.prevent="submitAdd"></textarea>
          <div class="ap-add-foot">
            <select v-model="addForm.status" class="ap-status-sel">
              <option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option>
            </select>
            <input v-model="addForm.follow_up_date" type="date" class="ap-date-inp" title="计划跟进日期" />
            <button class="ap-add-btn" :disabled="adding" @click="submitAdd">
              {{ adding ? '保存…' : '记录' }}
            </button>
          </div>
        </div>

        <!-- 动态时间线 -->
        <div class="ap-section-title">跟进记录 <span class="ap-cnt">{{ activities.length }}</span></div>
        <div v-if="!activities.length" class="ap-empty">暂无跟进记录</div>
        <div v-for="act in activities" :key="act.id" class="ap-act">
          <div class="ap-act-head">
            <span class="ap-act-icon">{{ actIcon(act.act_type) }}</span>
            <span class="ap-act-who">{{ act.created_by_name }}</span>
            <span class="ap-act-time">{{ fmtTime(act.created_at) }}</span>
            <button class="ap-status-chip" :style="{ color: statusColor(act.status) }" @click="toggleStatus(act)" title="点击切换状态">
              {{ act.status_display }}
            </button>
            <template v-if="act.can_edit && editingId !== act.id">
              <button class="ap-act-btn" @click="startEdit(act)">编辑</button>
              <button class="ap-act-btn ap-act-del" @click="deleteAct(act)">删除</button>
            </template>
          </div>
          <template v-if="editingId === act.id">
            <textarea v-model="editBuf.note" class="ap-edit-ta" rows="3"></textarea>
            <div class="ap-edit-foot">
              <select v-model="editBuf.status" class="ap-status-sel">
                <option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option>
              </select>
              <input v-model="editBuf.follow_up_date" type="date" class="ap-date-inp" />
              <button class="ap-save-btn" @click="saveEdit(act)">保存</button>
              <button class="ap-cancel-btn" @click="cancelEdit">取消</button>
            </div>
          </template>
          <div v-else class="ap-act-note">{{ act.note }}</div>
          <div v-if="act.follow_up_date && editingId !== act.id" class="ap-act-followup">
            计划跟进：{{ act.follow_up_date }}
          </div>
        </div>

        <!-- 附件区 -->
        <div class="ap-section-title">附件 <span class="ap-cnt">{{ attachments.length }}</span>
          <select v-model="uploadStage" class="ap-up-stage-sel">
            <option v-for="s in STAGES.slice(1)" :key="s.v" :value="s.v">{{ s.l }}</option>
            <option value="general">通用</option>
          </select>
        </div>

        <!-- 附件列表 -->
        <div v-for="att in attachments" :key="att.id" class="ap-att">
          <span class="ap-att-icon">{{ fileIcon(att) }}</span>
          <div class="ap-att-info">
            <a :href="att.download_url" target="_blank" class="ap-att-name" :title="att.file_name">{{ att.file_name }}</a>
            <span class="ap-att-meta">{{ fmtSize(att.file_size) }} · {{ att.stage_display }} · {{ att.uploaded_by_name }}</span>
          </div>
          <img v-if="att.has_thumb && att.thumb_url" :src="att.thumb_url" class="ap-att-thumb" />
          <button class="ap-att-del" @click="deleteAtt(att)" title="删除附件">✕</button>
        </div>

        <!-- 拖拽上传区 -->
        <div class="ap-dropzone"
          :class="{ 'ap-dropzone--over': dragOver, 'ap-dropzone--uploading': uploading }"
          @dragover.prevent="dragOver=true"
          @dragleave="dragOver=false"
          @drop.prevent="onDrop"
          @click="fileInputRef?.click()">
          <span v-if="uploading">上传中…</span>
          <span v-else>{{ dragOver ? '松手上传' : '拖拽或点击上传 · Ctrl+V 粘贴截图' }}</span>
          <input ref="fileInputRef" type="file" class="ap-file-input"
            accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.xlsx,.xls,.docx,.doc,.txt,.csv"
            @change="onFileInput" />
        </div>

      </div>
      <div v-else class="ap-loading">加载中…</div>
    </div>
  </Teleport>
</template>

<style scoped>
.ap-backdrop {
  position: fixed; inset: 0; z-index: 700;
  background: rgba(0,0,0,0.18);
}
.ap-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: 360px;
  z-index: 701; background: #fdfaf6;
  border-left: 1px solid var(--border, rgba(180,140,110,.28));
  box-shadow: -8px 0 32px rgba(0,0,0,0.12);
  display: flex; flex-direction: column; overflow: hidden;
}
.ap-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 14px 16px 10px; border-bottom: 1px solid var(--border, rgba(180,140,110,.2));
  background: linear-gradient(135deg, #fdf6ee, #fdfaf6); flex-shrink: 0;
}
.ap-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.ap-proj { font-size: 15px; font-weight: 800; color: #5f4d3d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-sub { font-size: 11.5px; color: #9b8070; }
.ap-close { border: none; background: none; font-size: 16px; color: #b3a08f; cursor: pointer; padding: 2px 6px; flex-shrink: 0; }
.ap-close:hover { color: #5f4d3d; }

.ap-quick { padding: 10px 14px; border-bottom: 1px solid var(--border, rgba(180,140,110,.15)); flex-shrink: 0; display: flex; flex-direction: column; gap: 6px; }
.ap-qrow { display: flex; align-items: flex-start; gap: 8px; }
.ap-qlabel { font-size: 11.5px; color: #9b8070; width: 52px; flex-shrink: 0; margin-top: 2px; }
.ap-qval { font-size: 13px; color: #5f4d3d; cursor: text; flex: 1; padding: 1px 4px; border-radius: 4px; }
.ap-qval:hover { background: rgba(201,99,66,0.07); }
.ap-qval--empty { color: #b3a08f; font-style: italic; }
.ap-qval--notes { white-space: pre-wrap; word-break: break-all; font-size: 12.5px; }
.ap-qinput, .ap-qta { flex: 1; border: 1px solid rgba(201,99,66,.4); border-radius: 6px; padding: 3px 7px; font-size: 13px; color: #5f4d3d; background: #fff; outline: none; font-family: inherit; }
.ap-qta { resize: vertical; min-height: 38px; }

.ap-tabs { display: flex; gap: 2px; padding: 6px 12px; border-bottom: 1px solid var(--border, rgba(180,140,110,.15)); flex-shrink: 0; }
.ap-tab { border: none; background: none; font-size: 12px; padding: 4px 10px; border-radius: 8px; cursor: pointer; color: #8a7665; }
.ap-tab:hover { background: rgba(201,99,66,.07); }
.ap-tab.on { background: rgba(201,99,66,.12); color: #c96342; font-weight: 700; }

.ap-body { flex: 1; overflow-y: auto; padding: 10px 14px; display: flex; flex-direction: column; gap: 10px; }
.ap-loading { flex: 1; display: flex; align-items: center; justify-content: center; color: #9b8070; font-size: 13px; }

/* 快速录入 */
.ap-add-form { background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.2); border-radius: 12px; padding: 10px 12px; display: flex; flex-direction: column; gap: 7px; }
.ap-type-chips { display: flex; gap: 5px; align-items: center; }
.ap-type-chip { border: 1px solid rgba(180,140,110,.25); background: #fff; border-radius: 8px; padding: 3px 9px; font-size: 14px; cursor: pointer; }
.ap-type-chip.on { border-color: #c96342; background: rgba(201,99,66,.08); }
.ap-stage-sel { margin-left: auto; border: 1px solid rgba(180,140,110,.25); border-radius: 6px; font-size: 12px; padding: 2px 6px; color: #5f4d3d; background: #fff; }
.ap-add-ta { width: 100%; border: 1px solid rgba(180,140,110,.25); border-radius: 8px; padding: 7px 9px; font-size: 13px; color: #5f4d3d; resize: none; font-family: inherit; background: #fff; outline: none; box-sizing: border-box; }
.ap-add-ta:focus { border-color: rgba(201,99,66,.5); }
.ap-add-foot { display: flex; gap: 6px; align-items: center; }
.ap-status-sel, .ap-date-inp { border: 1px solid rgba(180,140,110,.25); border-radius: 6px; font-size: 12px; padding: 4px 7px; color: #5f4d3d; background: #fff; }
.ap-add-btn { margin-left: auto; padding: 5px 16px; border: none; border-radius: 8px; background: linear-gradient(120deg, #c96342, #b5532f); color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; }
.ap-add-btn:disabled { opacity: .5; cursor: default; }

/* 动态 */
.ap-section-title { font-size: 12.5px; font-weight: 700; color: #9b8070; display: flex; align-items: center; gap: 6px; padding: 2px 0; }
.ap-cnt { font-size: 11px; background: rgba(180,140,110,.15); color: #9b8070; padding: 1px 7px; border-radius: 10px; }
.ap-up-stage-sel { margin-left: auto; border: 1px solid rgba(180,140,110,.25); border-radius: 6px; font-size: 11.5px; padding: 2px 5px; color: #5f4d3d; background: #fff; }
.ap-empty { font-size: 12.5px; color: #b3a08f; text-align: center; padding: 12px 0; }
.ap-act { background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.15); border-radius: 10px; padding: 9px 11px; display: flex; flex-direction: column; gap: 5px; }
.ap-act-head { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.ap-act-icon { font-size: 14px; }
.ap-act-who { font-size: 12px; font-weight: 700; color: #5f4d3d; }
.ap-act-time { font-size: 11px; color: #b3a08f; }
.ap-status-chip { border: none; background: none; font-size: 11px; font-weight: 600; cursor: pointer; padding: 1px 6px; border-radius: 8px; background: rgba(0,0,0,.04); }
.ap-act-btn { border: none; background: none; font-size: 11.5px; color: #9b8070; cursor: pointer; padding: 1px 5px; }
.ap-act-btn:hover { color: #5f4d3d; }
.ap-act-del:hover { color: #c62828; }
.ap-act-note { font-size: 13px; color: #5f4d3d; white-space: pre-wrap; word-break: break-all; line-height: 1.5; }
.ap-act-followup { font-size: 11.5px; color: #9b8070; }
.ap-edit-ta { width: 100%; border: 1px solid rgba(201,99,66,.4); border-radius: 7px; padding: 6px 8px; font-size: 13px; color: #5f4d3d; resize: none; font-family: inherit; box-sizing: border-box; }
.ap-edit-foot { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; }
.ap-save-btn { padding: 4px 12px; border: none; border-radius: 6px; background: #c96342; color: #fff; font-size: 12px; cursor: pointer; margin-left: auto; }
.ap-cancel-btn { padding: 4px 10px; border: 1px solid var(--border, rgba(180,140,110,.3)); border-radius: 6px; background: #fff; font-size: 12px; cursor: pointer; }

/* 附件 */
.ap-att { display: flex; align-items: center; gap: 8px; background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.15); border-radius: 9px; padding: 8px 10px; }
.ap-att-icon { font-size: 18px; flex-shrink: 0; }
.ap-att-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.ap-att-name { font-size: 12.5px; color: #1565c0; text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
.ap-att-name:hover { text-decoration: underline; }
.ap-att-meta { font-size: 11px; color: #9b8070; }
.ap-att-thumb { width: 40px; height: 40px; object-fit: cover; border-radius: 5px; flex-shrink: 0; }
.ap-att-del { border: none; background: none; color: #b3a08f; font-size: 13px; cursor: pointer; flex-shrink: 0; padding: 2px 4px; }
.ap-att-del:hover { color: #c62828; }

/* 上传区 */
.ap-dropzone {
  border: 2px dashed rgba(180,140,110,.35); border-radius: 10px;
  padding: 16px; text-align: center; font-size: 12.5px; color: #9b8070;
  cursor: pointer; transition: background .15s, border-color .15s;
  position: relative;
}
.ap-dropzone:hover, .ap-dropzone--over { background: rgba(201,99,66,.05); border-color: #c96342; color: #c96342; }
.ap-dropzone--uploading { opacity: .6; pointer-events: none; }
.ap-file-input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
</style>
