<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import ar from '../../api/ar.js'
import { useToast } from '../../composables/useToast.js'

const props = defineProps({
  rec: { type: Object, required: true },   // AR record object
})
const emit = defineEmits(['close', 'field-saved'])

const toast = useToast()
const errMsg = e => e?.msg || e?.error || '操作失败'

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
const REAL_STAGES = STAGES.slice(1)

async function load() {
  loading.value = true
  try {
    const res = await ar.listActivity(props.rec.id, activeStage.value ? { stage: activeStage.value } : {})
    activities.value = res.data.activities || []
    attachments.value = res.data.attachments || []
  } catch (e) {
    toast.error(errMsg(e))
  } finally {
    loading.value = false
  }
}

watch(() => props.rec?.id, (id) => { if (id) load() }, { immediate: true })
// 切换阶段：重载，并让"新增动态/上传附件"默认归入当前阶段（全部时回落催款/通用）
watch(activeStage, (s) => {
  load()
  addForm.stage = s || 'dunning'
  uploadStage.value = s || 'general'
})

const imageAtts = computed(() => attachments.value.filter(a => a.is_image))
const fileAtts = computed(() => attachments.value.filter(a => !a.is_image))

// ── 滑入 / 滑出动画 ─────────────────────────────────────────────────────────
const visible = ref(false)
function close() { visible.value = false; setTimeout(() => emit('close'), 220) }

// ── 快速编辑（行内）─────────────────────────────────────────────────────────
const editField = ref('')   // '' | 'collector' | 'target' | 'notes'
const quickFields = reactive({ collector: '', target_collection_date: '', notes: '' })
const collectorInp = ref(null), dateInp = ref(null), notesTa = ref(null)

watch(() => props.rec, (r) => {
  if (r) {
    quickFields.collector = r.collector || ''
    quickFields.target_collection_date = r.target_collection_date || ''
    quickFields.notes = r.notes || ''
  }
}, { immediate: true })

function beginEdit(field) {
  editField.value = field
  nextTick(() => {
    ({ collector: collectorInp, target: dateInp, notes: notesTa }[field])?.value?.focus()
  })
}
async function saveQuickField(field, key) {
  try {
    await ar.quickEdit(props.rec.id, { [key]: quickFields[key] })
    emit('field-saved', { id: props.rec.id, [key]: quickFields[key] })
    toast.success('已保存')
  } catch (e) {
    toast.error(errMsg(e))
  }
  editField.value = ''
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
  act_type: 'call', stage: 'dunning', contact_person: '',
  note: '', status: 'in_progress', follow_up_date: '',
})
const adding = ref(false)

async function submitAdd() {
  if (!addForm.note.trim()) { toast.error('请填写跟进内容'); return }
  adding.value = true
  try {
    const res = await ar.addActivity(props.rec.id, { ...addForm })
    // 只有当该动态属于当前筛选阶段（或正看全部）时才插入列表
    if (!activeStage.value || res.data.stage === activeStage.value) activities.value.unshift(res.data)
    emit('field-saved', { id: props.rec.id, activity_count: (props.rec.activity_count || 0) + 1 })
    addForm.note = ''; addForm.contact_person = ''; addForm.follow_up_date = ''
    toast.success('已记录')
  } catch (e) {
    toast.error(errMsg(e))
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
      note: editBuf.note, status: editBuf.status,
      follow_up_date: editBuf.follow_up_date || null,
    })
    const idx = activities.value.findIndex(a => a.id === act.id)
    if (idx !== -1) activities.value[idx] = res.data
    editingId.value = null
    toast.success('已更新')
  } catch (e) {
    toast.error(errMsg(e))
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
    toast.error(errMsg(e))
  }
}

async function toggleStatus(act) {
  const order = ['in_progress', 'pending', 'resolved', 'no_response']
  const next = order[(order.indexOf(act.status) + 1) % order.length]
  try {
    const res = await ar.updateActivity(props.rec.id, act.id, { note: act.note, status: next })
    const idx = activities.value.findIndex(a => a.id === act.id)
    if (idx !== -1) activities.value[idx] = res.data
  } catch (e) {
    toast.error(errMsg(e))
  }
}

// ── 附件上传 ──────────────────────────────────────────────────────────────
const uploading = ref(false)
const dragOver = ref(false)
const fileInputRef = ref(null)
const uploadStage = ref('general')
const ALLOWED = ['.jpg','.jpeg','.png','.gif','.webp','.pdf','.xlsx','.xls','.docx','.doc','.txt','.csv']

async function uploadFile(file) {
  if (!file) return
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  if (!ALLOWED.includes(ext)) { toast.error(`不支持 ${ext} 格式。支持：图片/PDF/Excel/Word/CSV/TXT`); return }
  if (file.size > 20 * 1024 * 1024) { toast.error('文件不能超过 20MB'); return }
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
    toast.error(errMsg(e))
  } finally {
    uploading.value = false
  }
}

function onFileInput(e) { uploadFile(e.target.files[0]); e.target.value = '' }
function onDrop(e) { dragOver.value = false; const f = e.dataTransfer?.files?.[0]; if (f) uploadFile(f) }

function onPaste(e) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) {
        uploadFile(new File([f], `clipboard-${new Date().toISOString().slice(0,19).replace(/[:T]/g,'')}.png`, { type: f.type }))
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
    toast.error(errMsg(e))
  }
}

// ── 工具 ──────────────────────────────────────────────────────────────────
function fmtSize(b) {
  if (b < 1024) return b + 'B'
  if (b < 1048576) return (b / 1024).toFixed(1) + 'KB'
  return (b / 1048576).toFixed(1) + 'MB'
}
function fmtTime(iso) { return iso ? iso.replace('T', ' ').slice(0, 16) : '' }
function fileIcon(att) {
  const ext = att.file_name.split('.').pop().toLowerCase()
  if (ext === 'pdf') return '📄'
  if (['xlsx','xls','csv'].includes(ext)) return '📊'
  if (['docx','doc'].includes(ext)) return '📝'
  return '📎'
}
const STATUS_COLOR = { in_progress: '#1565c0', pending: '#e8830c', resolved: '#2e7d32', no_response: '#9e9e9e' }
function statusColor(s) { return STATUS_COLOR[s] || '#888' }
function actIcon(t) { return { call: '📞', email: '📧', visit: '🚶', meeting: '💬', system: '⚙️', note: '📝', other: '💡' }[t] || '💬' }
const STAGE_LABEL = Object.fromEntries(REAL_STAGES.map(s => [s.v, s.l]))

// ── 生命周期进度条 ─────────────────────────────────────────────────────────────
function fmtAmt(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(1) + '亿'
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(1) + '万'
  return Math.round(n).toLocaleString()
}

// Internal constant — no user input, safe to use with v-html
const LC_ICONS = {
  contract: `<svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3.5 2h6.8L13 4.7V14a.5.5 0 01-.5.5h-9A.5.5 0 013 14V2.5A.5.5 0 013.5 2z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M10.3 2v2.7H13" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M5.5 7.5h5M5.5 10h5M5.5 12h3" stroke="currentColor" stroke-width="1" stroke-linecap="round"/></svg>`,
  reconciliation: `<svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M2.5 5.5l2.5 2.5 5-5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M2.5 11l2.5 2.5 5-5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M13 4.5v7" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" opacity=".5"/></svg>`,
  invoice: `<svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 2.5h10v12l-1.5-1.2-1.5 1.2-1.5-1.2-1.5 1.2-1.5-1.2-1.5 1.2V2.5z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M5.5 6.5h5M5.5 9h5M5.5 11h3.5" stroke="currentColor" stroke-width="1" stroke-linecap="round"/></svg>`,
  collection: `<svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.2"/><path d="M8 4.5v1M8 10.5v1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><path d="M6.2 6.9c0-.77.8-1.4 1.8-1.4s1.8.63 1.8 1.4c0 1.73-3.6 1.73-3.6 3.2 0 .77.8 1.4 1.8 1.4s1.8-.63 1.8-1.4" stroke="currentColor" stroke-width="1" stroke-linecap="round"/></svg>`,
  dunning: `<svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 2a4.5 4.5 0 00-4.5 4.5C3.5 9 4.5 10.5 5 12h6c.5-1.5 1.5-3 1.5-5.5A4.5 4.5 0 008 2z" stroke="currentColor" stroke-width="1.2"/><path d="M6.5 12a1.5 1.5 0 003 0" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>`,
}

const lifecycleSteps = computed(() => {
  const r = props.rec
  const total = Number(r.estimated_amount || 0)
  const outstanding = Number(r.outstanding_amount || 0)
  const paid = Math.max(0, total - outstanding)
  const pct = total > 0 ? Math.min(1, paid / total) : 0
  const byStage = {}
  for (const a of activities.value) byStage[a.stage] = (byStage[a.stage] || 0) + 1

  const reconDone = !!r.reconciliation_date
  const invoiceDone = !!(r.invoice_date || Number(r.actual_invoice_amount) > 0)
  const collDone = total > 0 && outstanding === 0
  const overdue = Number(r.overdue_days || 0)

  return [
    { key: 'contract', label: '合同', sub: '已签订', state: 'done', icon: 'contract' },
    {
      key: 'reconciliation', label: '对账',
      sub: r.reconciliation_date || (byStage.reconciliation ? `${byStage.reconciliation}条` : ''),
      state: reconDone ? 'done' : (byStage.reconciliation ? 'active' : 'pending'),
      icon: 'reconciliation',
    },
    {
      key: 'invoice', label: '开票',
      sub: r.invoice_date || (Number(r.actual_invoice_amount) > 0 ? fmtAmt(r.actual_invoice_amount) : ''),
      state: invoiceDone ? 'done' : (byStage.invoice ? 'active' : 'pending'),
      icon: 'invoice',
    },
    {
      key: 'collection', label: '回款',
      sub: collDone ? '完成' : (pct > 0 ? `${Math.round(pct * 100)}%` : ''),
      state: collDone ? 'done' : (pct > 0 ? 'partial' : (byStage.collection ? 'active' : 'pending')),
      pct,
      icon: 'collection',
    },
    {
      key: 'dunning', label: '催款',
      sub: overdue > 0 ? `逾期${overdue}天` : (byStage.dunning ? `${byStage.dunning}次` : ''),
      state: overdue > 0 ? 'urgent' : (byStage.dunning ? 'active' : 'pending'),
      icon: 'dunning',
    },
  ]
})

function lcLineState(cur, next) {
  if (cur.state === 'done' && next.state === 'done') return 'done'
  if (cur.state === 'done') return 'progress'
  return 'pending'
}

// ── 键盘 ──────────────────────────────────────────────────────────────────
function onKey(e) {
  if (e.key !== 'Escape') return
  if (editField.value) { editField.value = ''; return }
  if (editingId.value !== null) { cancelEdit(); return }
  close()
}

onMounted(() => {
  requestAnimationFrame(() => { visible.value = true })
  document.addEventListener('paste', onPaste)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('paste', onPaste)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <div class="ap-backdrop" :class="{ 'ap-open': visible }" @click.self="close"></div>
    <div class="ap-panel" :class="{ 'ap-open': visible }">
      <!-- 头部 -->
      <div class="ap-header">
        <div class="ap-title">
          <span class="ap-proj" :title="rec.short_name || rec.customer_name">{{ rec.short_name || rec.customer_name }}</span>
          <span v-if="rec.customer_name && rec.customer_name !== rec.short_name" class="ap-sub">{{ rec.customer_name }}</span>
        </div>
        <button class="ap-close" title="关闭 (Esc)" @click="close">✕</button>
      </div>

      <!-- 生命周期进度条 -->
      <div class="ap-lifecycle">
        <div class="ap-lc-track">
          <template v-for="(step, i) in lifecycleSteps" :key="step.key">
            <div class="ap-lc-step">
              <div class="ap-lc-node" :class="`lc-${step.state}`"
                :style="step.state === 'partial' ? { '--pct': step.pct } : {}">
                <!-- svg injected via v-html from internal LC_ICONS constant -->
                <span class="ap-lc-icon-wrap" v-html="LC_ICONS[step.icon]"></span>
              </div>
              <div class="ap-lc-labels">
                <span class="ap-lc-name">{{ step.label }}</span>
                <span v-if="step.sub" class="ap-lc-sub" :class="`lc-sub-${step.state}`">{{ step.sub }}</span>
              </div>
            </div>
            <div v-if="i < lifecycleSteps.length - 1" class="ap-lc-conn"
              :class="`lc-conn-${lcLineState(step, lifecycleSteps[i + 1])}`"></div>
          </template>
        </div>
        <!-- 关键指标 -->
        <div class="ap-lc-metrics">
          <div class="ap-lc-metric">
            <span class="ap-lc-mv">¥{{ fmtAmt(rec.estimated_amount) }}</span>
            <span class="ap-lc-mk">应收</span>
          </div>
          <div class="ap-lc-mdiv"></div>
          <div class="ap-lc-metric">
            <span class="ap-lc-mv ap-lc-mv--good">
              ¥{{ fmtAmt(Math.max(0, Number(rec.estimated_amount || 0) - Number(rec.outstanding_amount || 0))) }}
            </span>
            <span class="ap-lc-mk">已收</span>
          </div>
          <div class="ap-lc-mdiv"></div>
          <div class="ap-lc-metric">
            <span class="ap-lc-mv" :class="Number(rec.outstanding_amount) > 0 ? 'ap-lc-mv--warn' : 'ap-lc-mv--good'">
              ¥{{ fmtAmt(rec.outstanding_amount) }}
            </span>
            <span class="ap-lc-mk">欠款</span>
          </div>
          <template v-if="Number(rec.overdue_days) > 0">
            <div class="ap-lc-mdiv"></div>
            <div class="ap-lc-metric">
              <span class="ap-lc-mv ap-lc-mv--danger">{{ rec.overdue_days }}天</span>
              <span class="ap-lc-mk">逾期</span>
            </div>
          </template>
          <template v-else-if="rec.target_collection_date">
            <div class="ap-lc-mdiv"></div>
            <div class="ap-lc-metric">
              <span class="ap-lc-mv ap-lc-mv--target">{{ rec.target_collection_date }}</span>
              <span class="ap-lc-mk">目标</span>
            </div>
          </template>
        </div>
      </div>

      <!-- 快速编辑信息条 -->
      <div class="ap-quick">
        <div class="ap-qcell">
          <span class="ap-qlabel">催收人</span>
          <input v-if="editField==='collector'" ref="collectorInp" v-model="quickFields.collector" class="ap-qinput" placeholder="姓名"
            @blur="saveQuickField('collector','collector')" @keyup.enter="saveQuickField('collector','collector')" @keyup.escape="editField=''" />
          <span v-else class="ap-qval" :class="{ 'ap-qval--empty': !quickFields.collector }" @click="beginEdit('collector')">
            {{ quickFields.collector || '＋ 设置' }}
          </span>
        </div>
        <div class="ap-qcell">
          <span class="ap-qlabel">目标回款</span>
          <input v-if="editField==='target'" ref="dateInp" v-model="quickFields.target_collection_date" type="date" class="ap-qinput"
            @blur="saveQuickField('target','target_collection_date')" @keyup.enter="saveQuickField('target','target_collection_date')" @keyup.escape="editField=''" />
          <span v-else class="ap-qval" :class="{ 'ap-qval--empty': !quickFields.target_collection_date }" @click="beginEdit('target')">
            {{ quickFields.target_collection_date || '＋ 设置' }}
          </span>
        </div>
        <div class="ap-qcell ap-qcell--wide">
          <span class="ap-qlabel">备注</span>
          <textarea v-if="editField==='notes'" ref="notesTa" v-model="quickFields.notes" class="ap-qta" rows="2"
            @blur="saveQuickField('notes','notes')" @keyup.escape="editField=''"></textarea>
          <span v-else class="ap-qval ap-qval--notes" :class="{ 'ap-qval--empty': !quickFields.notes }" @click="beginEdit('notes')">
            {{ quickFields.notes || '＋ 添加备注' }}
          </span>
        </div>
      </div>

      <!-- 阶段筛选 -->
      <div class="ap-tabs">
        <button v-for="s in STAGES" :key="s.v" class="ap-tab" :class="{ on: activeStage === s.v }" @click="activeStage = s.v">{{ s.l }}</button>
      </div>

      <!-- 快速录入 -->
      <div class="ap-add">
        <div class="ap-add-row1">
          <button v-for="t in ACT_TYPES" :key="t.v" class="ap-type-chip" :class="{ on: addForm.act_type === t.v }" :title="t.title" @click="addForm.act_type = t.v">{{ t.l }}</button>
          <select v-model="addForm.stage" class="ap-mini-sel" title="归入阶段">
            <option v-for="s in REAL_STAGES" :key="s.v" :value="s.v">{{ s.l }}</option>
          </select>
        </div>
        <textarea v-model="addForm.note" class="ap-add-ta" rows="2" placeholder="跟进内容…（Ctrl+Enter 保存）" @keydown.ctrl.enter.prevent="submitAdd"></textarea>
        <div class="ap-add-row2">
          <select v-model="addForm.status" class="ap-mini-sel">
            <option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option>
          </select>
          <input v-model="addForm.follow_up_date" type="date" class="ap-mini-sel" title="计划跟进日期" />
          <button class="ap-add-btn" :disabled="adding || !addForm.note.trim()" @click="submitAdd">{{ adding ? '保存…' : '记录' }}</button>
        </div>
      </div>

      <div class="ap-body">
        <template v-if="loading">
          <div class="ap-skeleton" v-for="n in 3" :key="n"></div>
        </template>
        <template v-else>
          <!-- 跟进时间线 -->
          <div class="ap-sec">
            <span class="ap-sec-t">跟进记录</span><span class="ap-cnt">{{ activities.length }}</span>
          </div>
          <div v-if="!activities.length" class="ap-empty">暂无跟进记录，在上方记录第一条</div>
          <div v-else class="ap-timeline">
            <div v-for="act in activities" :key="act.id" class="ap-act" :style="{ '--sc': statusColor(act.status) }">
              <div class="ap-act-head">
                <span class="ap-act-icon">{{ actIcon(act.act_type) }}</span>
                <span class="ap-act-who">{{ act.created_by_name || '—' }}</span>
                <span v-if="!activeStage" class="ap-stage-tag">{{ STAGE_LABEL[act.stage] || act.stage_display }}</span>
                <button class="ap-status-chip" @click="act.can_edit && toggleStatus(act)" :title="act.can_edit ? '点击切换状态' : ''">{{ act.status_display }}</button>
                <span class="ap-act-time">{{ fmtTime(act.created_at) }}</span>
                <template v-if="act.can_edit && editingId !== act.id">
                  <button class="ap-ico-btn" title="编辑" @click="startEdit(act)">✏️</button>
                  <button class="ap-ico-btn ap-ico-del" title="删除" @click="deleteAct(act)">🗑</button>
                </template>
              </div>
              <template v-if="editingId === act.id">
                <textarea v-model="editBuf.note" class="ap-edit-ta" rows="3"></textarea>
                <div class="ap-edit-foot">
                  <select v-model="editBuf.status" class="ap-mini-sel">
                    <option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option>
                  </select>
                  <input v-model="editBuf.follow_up_date" type="date" class="ap-mini-sel" />
                  <button class="ap-save-btn" @click="saveEdit(act)">保存</button>
                  <button class="ap-cancel-btn" @click="cancelEdit">取消</button>
                </div>
              </template>
              <template v-else>
                <div class="ap-act-note">{{ act.note }}</div>
                <div v-if="act.follow_up_date" class="ap-act-followup">📅 计划跟进 {{ act.follow_up_date }}</div>
              </template>
            </div>
          </div>

          <!-- 附件 -->
          <div class="ap-sec">
            <span class="ap-sec-t">附件</span><span class="ap-cnt">{{ attachments.length }}</span>
            <select v-model="uploadStage" class="ap-mini-sel ap-sec-sel" title="上传归入阶段">
              <option v-for="s in REAL_STAGES" :key="s.v" :value="s.v">{{ s.l }}</option>
              <option value="general">通用</option>
            </select>
          </div>

          <!-- 图片：缩略图网格 -->
          <div v-if="imageAtts.length" class="ap-img-grid">
            <div v-for="att in imageAtts" :key="att.id" class="ap-img-cell" :title="att.file_name">
              <a :href="att.download_url" target="_blank">
                <img :src="att.thumb_url || att.download_url" class="ap-img" :alt="att.file_name" />
              </a>
              <button class="ap-img-del" title="删除" @click="deleteAtt(att)">✕</button>
              <span class="ap-img-cap">{{ att.stage_display }}</span>
            </div>
          </div>

          <!-- 文件：紧凑列表 -->
          <div v-for="att in fileAtts" :key="att.id" class="ap-file">
            <span class="ap-file-icon">{{ fileIcon(att) }}</span>
            <div class="ap-file-info">
              <a :href="att.download_url" target="_blank" class="ap-file-name" :title="att.file_name">{{ att.file_name }}</a>
              <span class="ap-file-meta">{{ fmtSize(att.file_size) }} · {{ att.stage_display }} · {{ att.uploaded_by_name }}</span>
            </div>
            <button class="ap-file-del" title="删除" @click="deleteAtt(att)">✕</button>
          </div>

          <!-- 上传区 -->
          <div class="ap-dropzone" :class="{ 'ap-dz-over': dragOver, 'ap-dz-up': uploading }"
            @dragover.prevent="dragOver=true" @dragleave="dragOver=false" @drop.prevent="onDrop" @click="fileInputRef?.click()">
            <span v-if="uploading">⏳ 上传中…</span>
            <span v-else>{{ dragOver ? '松手上传' : '⬆ 拖拽 / 点击上传 · Ctrl+V 粘贴截图' }}</span>
            <input ref="fileInputRef" type="file" class="ap-file-input"
              accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.xlsx,.xls,.docx,.doc,.txt,.csv" @change="onFileInput" />
          </div>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.ap-backdrop { position: fixed; inset: 0; z-index: 700; background: rgba(40,24,12,0.22); opacity: 0; transition: opacity .22s ease; }
.ap-backdrop.ap-open { opacity: 1; }
.ap-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: 392px; max-width: 94vw;
  z-index: 701; background: #fbf7f1;
  border-left: 1px solid rgba(180,140,110,.28);
  box-shadow: -10px 0 40px rgba(60,30,10,0.16);
  display: flex; flex-direction: column; overflow: hidden;
  transform: translateX(100%); transition: transform .24s cubic-bezier(.4,0,.2,1);
}
.ap-panel.ap-open { transform: translateX(0); }

/* 头部 */
.ap-header {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding: 13px 16px; border-bottom: 1px solid rgba(180,140,110,.2);
  background: linear-gradient(135deg, #fceede, #fbf7f1); flex-shrink: 0;
}
.ap-title { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.ap-proj { font-size: 15px; font-weight: 800; color: #5a4636; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-sub { font-size: 11.5px; color: #9b8070; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-close { border: none; background: rgba(0,0,0,.04); width: 26px; height: 26px; border-radius: 50%; font-size: 13px; color: #9b8070; cursor: pointer; flex-shrink: 0; transition: all .12s; }
.ap-close:hover { background: rgba(201,99,66,.12); color: #c96342; }

/* 快速编辑信息条 */
.ap-quick { display: flex; flex-wrap: wrap; gap: 6px 14px; padding: 10px 16px; border-bottom: 1px solid rgba(180,140,110,.15); flex-shrink: 0; }
.ap-qcell { display: flex; align-items: center; gap: 7px; min-width: 0; }
.ap-qcell--wide { flex-basis: 100%; }
.ap-qlabel { font-size: 11px; color: #a8917e; flex-shrink: 0; }
.ap-qval { font-size: 12.5px; color: #5a4636; cursor: pointer; padding: 2px 7px; border-radius: 6px; border: 1px solid transparent; transition: all .1s; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ap-qcell--wide .ap-qval { max-width: none; flex: 1; white-space: pre-wrap; word-break: break-word; }
.ap-qval:hover { background: #fff; border-color: rgba(201,99,66,.25); }
.ap-qval--empty { color: #c0ad9d; }
.ap-qinput, .ap-qta { border: 1px solid rgba(201,99,66,.45); border-radius: 6px; padding: 3px 7px; font-size: 12.5px; color: #5a4636; background: #fff; outline: none; font-family: inherit; }
.ap-qcell--wide .ap-qta { flex: 1; resize: vertical; min-height: 40px; }

/* 阶段 tabs */
.ap-tabs { display: flex; gap: 3px; padding: 8px 12px; border-bottom: 1px solid rgba(180,140,110,.15); flex-shrink: 0; }
.ap-tab { flex: 1; border: none; background: none; font-size: 12px; padding: 5px 0; border-radius: 8px; cursor: pointer; color: #8a7665; transition: all .12s; }
.ap-tab:hover { background: rgba(201,99,66,.07); }
.ap-tab.on { background: rgba(201,99,66,.13); color: #c96342; font-weight: 700; }

/* 快速录入 */
.ap-add { padding: 10px 14px; border-bottom: 1px solid rgba(180,140,110,.15); display: flex; flex-direction: column; gap: 7px; flex-shrink: 0; background: rgba(255,253,250,.6); }
.ap-add-row1 { display: flex; gap: 5px; align-items: center; }
.ap-type-chip { border: 1px solid rgba(180,140,110,.25); background: #fff; border-radius: 8px; padding: 3px 8px; font-size: 14px; cursor: pointer; line-height: 1; transition: all .12s; }
.ap-type-chip:hover { border-color: rgba(201,99,66,.5); }
.ap-type-chip.on { border-color: #c96342; background: rgba(201,99,66,.1); transform: translateY(-1px); }
.ap-add-ta { width: 100%; border: 1px solid rgba(180,140,110,.25); border-radius: 9px; padding: 8px 10px; font-size: 13px; color: #5a4636; resize: vertical; min-height: 42px; font-family: inherit; background: #fff; outline: none; box-sizing: border-box; transition: border-color .12s; }
.ap-add-ta:focus { border-color: rgba(201,99,66,.55); }
.ap-add-row2 { display: flex; gap: 6px; align-items: center; }
.ap-mini-sel { border: 1px solid rgba(180,140,110,.28); border-radius: 7px; font-size: 12px; padding: 4px 7px; color: #5a4636; background: #fff; outline: none; font-family: inherit; }
.ap-add-row1 .ap-mini-sel { margin-left: auto; }
.ap-add-btn { margin-left: auto; padding: 6px 18px; border: none; border-radius: 8px; background: linear-gradient(120deg, #c96342, #b5532f); color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; transition: filter .12s; }
.ap-add-btn:hover:not(:disabled) { filter: brightness(1.06); }
.ap-add-btn:disabled { opacity: .45; cursor: default; }

/* 滚动区 */
.ap-body { flex: 1; overflow-y: auto; padding: 12px 14px; display: flex; flex-direction: column; gap: 9px; }
.ap-skeleton { height: 56px; border-radius: 10px; background: linear-gradient(90deg, rgba(180,140,110,.08), rgba(180,140,110,.16), rgba(180,140,110,.08)); background-size: 200% 100%; animation: ap-sk 1.3s ease infinite; }
@keyframes ap-sk { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

.ap-sec { display: flex; align-items: center; gap: 7px; margin-top: 2px; }
.ap-sec-t { font-size: 12.5px; font-weight: 800; color: #8a7665; letter-spacing: .02em; }
.ap-cnt { font-size: 11px; background: rgba(201,99,66,.12); color: #c96342; padding: 0 7px; border-radius: 10px; font-weight: 700; line-height: 17px; }
.ap-sec-sel { margin-left: auto; }
.ap-empty { font-size: 12.5px; color: #bda797; text-align: center; padding: 14px 0; }

/* 时间线 */
.ap-timeline { display: flex; flex-direction: column; gap: 8px; }
.ap-act { background: #fff; border: 1px solid rgba(180,140,110,.18); border-left: 3px solid var(--sc); border-radius: 9px; padding: 9px 11px; display: flex; flex-direction: column; gap: 5px; }
.ap-act-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ap-act-icon { font-size: 14px; line-height: 1; }
.ap-act-who { font-size: 12px; font-weight: 700; color: #5a4636; }
.ap-stage-tag { font-size: 10px; color: #8a7665; background: rgba(180,140,110,.14); padding: 0 6px; border-radius: 7px; line-height: 16px; }
.ap-status-chip { border: none; font-size: 10.5px; font-weight: 700; cursor: pointer; padding: 1px 8px; border-radius: 8px; color: var(--sc); background: color-mix(in srgb, var(--sc) 12%, transparent); }
.ap-act-time { font-size: 10.5px; color: #bda797; margin-left: auto; }
.ap-ico-btn { border: none; background: none; font-size: 12px; cursor: pointer; padding: 1px 3px; border-radius: 5px; opacity: .7; }
.ap-ico-btn:hover { opacity: 1; background: rgba(0,0,0,.05); }
.ap-act-note { font-size: 13px; color: #4a3a2c; white-space: pre-wrap; word-break: break-word; line-height: 1.55; }
.ap-act-followup { font-size: 11px; color: #a8917e; }
.ap-edit-ta { width: 100%; border: 1px solid rgba(201,99,66,.45); border-radius: 7px; padding: 6px 9px; font-size: 13px; color: #5a4636; resize: vertical; font-family: inherit; box-sizing: border-box; outline: none; }
.ap-edit-foot { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; }
.ap-save-btn { padding: 4px 14px; border: none; border-radius: 6px; background: #c96342; color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; margin-left: auto; }
.ap-cancel-btn { padding: 4px 11px; border: 1px solid rgba(180,140,110,.3); border-radius: 6px; background: #fff; font-size: 12px; cursor: pointer; color: #8a7665; }

/* 图片网格 */
.ap-img-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }
.ap-img-cell { position: relative; aspect-ratio: 1; border-radius: 8px; overflow: hidden; border: 1px solid rgba(180,140,110,.2); }
.ap-img { width: 100%; height: 100%; object-fit: cover; display: block; cursor: zoom-in; }
.ap-img-del { position: absolute; top: 3px; right: 3px; width: 18px; height: 18px; border: none; border-radius: 50%; background: rgba(0,0,0,.5); color: #fff; font-size: 10px; cursor: pointer; line-height: 18px; padding: 0; opacity: 0; transition: opacity .12s; }
.ap-img-cell:hover .ap-img-del { opacity: 1; }
.ap-img-cap { position: absolute; left: 0; bottom: 0; right: 0; font-size: 9px; color: #fff; background: rgba(0,0,0,.4); padding: 1px 5px; text-align: center; }

/* 文件列表 */
.ap-file { display: flex; align-items: center; gap: 9px; background: #fff; border: 1px solid rgba(180,140,110,.18); border-radius: 9px; padding: 8px 11px; }
.ap-file-icon { font-size: 18px; flex-shrink: 0; }
.ap-file-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.ap-file-name { font-size: 12.5px; color: #1565c0; text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-file-name:hover { text-decoration: underline; }
.ap-file-meta { font-size: 10.5px; color: #a8917e; }
.ap-file-del { border: none; background: none; color: #c0ad9d; font-size: 12px; cursor: pointer; flex-shrink: 0; padding: 2px 5px; border-radius: 5px; }
.ap-file-del:hover { color: #c62828; background: rgba(198,40,40,.07); }

/* 上传区 */
.ap-dropzone { border: 2px dashed rgba(180,140,110,.35); border-radius: 10px; padding: 14px; text-align: center; font-size: 12px; color: #a8917e; cursor: pointer; transition: all .15s; position: relative; }
.ap-dropzone:hover, .ap-dz-over { background: rgba(201,99,66,.05); border-color: #c96342; color: #c96342; }
.ap-dz-up { opacity: .6; pointer-events: none; }
.ap-file-input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }

/* ══════════════════════════════════════════════════════
   生命周期进度条
   ══════════════════════════════════════════════════════ */
.ap-lifecycle {
  padding: 14px 16px 12px;
  border-bottom: 1px solid rgba(180,140,110,.18);
  background: linear-gradient(180deg, #fdf4ea 0%, #fbf7f1 100%);
  flex-shrink: 0;
}

/* ── Track ── */
.ap-lc-track {
  display: flex; align-items: flex-start;
}
.ap-lc-step {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  width: 56px; flex-shrink: 0;
}
.ap-lc-conn {
  flex: 1; height: 2px; margin-top: 18px; border-radius: 2px;
  min-width: 6px; transition: background .35s ease;
}
.lc-conn-done    { background: linear-gradient(90deg, #43a047, #2e7d32); }
.lc-conn-progress{ background: linear-gradient(90deg, #66bb6a, #c96342); }
.lc-conn-pending { background: rgba(180,140,110,.22); }

/* ── Step node ── */
.ap-lc-node {
  width: 38px; height: 38px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  position: relative; flex-shrink: 0;
  transition: box-shadow .2s, transform .15s;
}
.ap-lc-node:hover { transform: translateY(-1px); }

/* done: green gradient + white icon */
.lc-done {
  background: linear-gradient(145deg, #66bb6a, #2e7d32);
  color: #fff;
  box-shadow: 0 3px 10px rgba(46,125,50,.32), 0 1px 3px rgba(0,0,0,.12);
}
/* partial: conic-gradient ring + white inner disc */
.lc-partial {
  background: conic-gradient(#c96342 calc(var(--pct, 0) * 1turn), #e8d9ce 0);
  color: #c96342;
  box-shadow: 0 2px 8px rgba(201,99,66,.22);
}
.lc-partial::after {
  content: ''; position: absolute; inset: 6px; border-radius: 50%;
  background: #fff; box-shadow: inset 0 0 0 1px rgba(201,99,66,.1);
}
/* active: primary gradient + pulse ring */
.lc-active {
  background: linear-gradient(145deg, #e07848, #c96342);
  color: #fff;
  box-shadow: 0 3px 10px rgba(201,99,66,.38), 0 1px 3px rgba(0,0,0,.1);
}
.lc-active::before {
  content: ''; position: absolute; inset: -6px; border-radius: 50%;
  border: 2px solid #c96342; opacity: 0;
  animation: lc-pulse 1.9s ease-out infinite;
}
/* urgent: red + fast pulse */
.lc-urgent {
  background: linear-gradient(145deg, #ef5350, #c62828);
  color: #fff;
  box-shadow: 0 3px 10px rgba(198,40,40,.38), 0 1px 3px rgba(0,0,0,.1);
}
.lc-urgent::before {
  content: ''; position: absolute; inset: -6px; border-radius: 50%;
  border: 2px solid #ef5350; opacity: 0;
  animation: lc-pulse 1.1s ease-out infinite;
}
/* pending: white + soft border */
.lc-pending {
  background: #fff;
  border: 2px solid #ddd0c4;
  color: #c0ad9d;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
}

@keyframes lc-pulse {
  0%   { transform: scale(.72); opacity: .65; }
  100% { transform: scale(1.55); opacity: 0; }
}

/* ── Icon wrap (sits above ::after in partial) ── */
.ap-lc-icon-wrap {
  width: 16px; height: 16px;
  display: flex; align-items: center; justify-content: center;
  position: relative; z-index: 1; flex-shrink: 0;
  line-height: 0;
}
.ap-lc-icon-wrap svg { width: 16px; height: 16px; display: block; }

/* ── Labels ── */
.ap-lc-labels {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
}
.ap-lc-name {
  font-size: 11.5px; font-weight: 700; color: #5a4636;
  white-space: nowrap; letter-spacing: .01em;
}
.ap-lc-sub {
  font-size: 10px; white-space: nowrap;
  max-width: 56px; overflow: hidden; text-overflow: ellipsis;
  color: #b0987e;
}
.lc-sub-done    { color: #2e7d32; font-weight: 600; }
.lc-sub-partial { color: #c96342; font-weight: 700; }
.lc-sub-active  { color: #c96342; }
.lc-sub-urgent  { color: #c62828; font-weight: 700; }

/* ── Metrics row ── */
.ap-lc-metrics {
  display: flex; align-items: center;
  margin-top: 13px; padding: 8px 12px;
  background: rgba(255,255,255,.78);
  border-radius: 10px;
  border: 1px solid rgba(180,140,110,.16);
  box-shadow: 0 1px 4px rgba(60,30,10,.05);
}
.ap-lc-metric {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px;
}
.ap-lc-mdiv {
  width: 1px; height: 28px; flex-shrink: 0;
  background: rgba(180,140,110,.2);
  margin: 0 2px;
}
.ap-lc-mv {
  font-size: 13px; font-weight: 800; color: #5a4636;
  font-variant-numeric: tabular-nums; line-height: 1.2;
  white-space: nowrap;
}
.ap-lc-mv--good   { color: #2e7d32; }
.ap-lc-mv--warn   { color: #c96342; }
.ap-lc-mv--danger { color: #c62828; }
.ap-lc-mv--target { color: #1565c0; font-size: 11px; font-weight: 700; }
.ap-lc-mk {
  font-size: 10px; color: #a8917e; line-height: 1;
}
</style>
