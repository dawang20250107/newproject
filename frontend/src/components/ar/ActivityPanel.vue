<script setup>
/*
 * AR 生命线工作台 —— 3节点时间线版
 * 对账 → 开票（可跳过）→ 回款
 * 点击节点直接展开数据录入；催款跟进独立展示在下方
 */
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import ar from '../../api/ar.js'
import { useToast } from '../../composables/useToast.js'
import { todayCST, DEPARTMENTS } from '../../constants.js'
import { copyText } from '../../utils/clipboard.js'

const props = defineProps({
  rec:        { type: Object, required: true },
  canWrite:   { type: Boolean, default: false },
  canCollect: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'field-saved'])

const toast = useToast()
const errMsg = e => e?.msg || e?.error || '操作失败'

// ── 数据加载 ─────────────────────────────────────────────────────────────────
const loading       = ref(false)
const allActivities = ref([])
const attachments   = ref([])
const payments      = ref([])

async function load() {
  loading.value = true
  try {
    const [actRes, payRes] = await Promise.all([
      ar.listActivity(props.rec.id, {}),
      ar.listPayments(props.rec.id).catch(() => ({ data: [] })),
    ])
    allActivities.value = actRes.data.activities || []
    attachments.value   = actRes.data.attachments || []
    payments.value      = Array.isArray(payRes.data) ? payRes.data : []
  } catch (e) { toast.error(errMsg(e)) }
  finally { loading.value = false }
}
watch(() => props.rec?.id, id => { if (id) load() }, { immediate: true })

const actsByStage = computed(() => {
  const m = { reconciliation: [], invoice: [], collection: [], dunning: [] }
  for (const a of allActivities.value) (m[a.stage] || m.dunning).push(a)
  return m
})
const attsByStage = computed(() => {
  const m = { reconciliation: [], invoice: [], collection: [], dunning: [] }
  for (const a of attachments.value) (m[a.stage] || m.dunning).push(a)
  return m
})

// ── 金额 / 进度 ──────────────────────────────────────────────────────────────
function fmtAmt(v) {
  if (v == null || v === '') return '0'
  const n = Number(v)
  if (isNaN(n)) return '0'
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(1) + '万'
  return Math.round(n).toLocaleString()
}
const estimated   = computed(() => Number(props.rec.estimated_amount || 0))
const outstanding = computed(() => Number(props.rec.outstanding_amount || 0))
const paid        = computed(() => Math.max(0, estimated.value - outstanding.value))
const paidPct     = computed(() => estimated.value > 0 ? Math.min(1, paid.value / estimated.value) : 0)
const overdueDays = computed(() => Number(props.rec.overdue_days || 0))

// ── 节点状态推断 ──────────────────────────────────────────────────────────────
const invoiceSkipped = computed(() => props.rec.invoice_mode === '不开票')

const nodeStates = computed(() => {
  const r = props.rec
  const a = actsByStage.value
  const reconDone = !!r.reconciliation_date
  const invDone   = !!(r.invoice_date || Number(r.actual_invoice_amount) > 0)
  const collDone  = estimated.value > 0 && outstanding.value === 0
  return {
    reconciliation: {
      state:   reconDone ? 'done' : (a.reconciliation.length ? 'active' : 'pending'),
      label:   reconDone ? '已对账' : '待对账',
      summary: reconDone ? r.reconciliation_date : (a.reconciliation.length ? `${a.reconciliation.length} 条跟进` : null),
    },
    invoice: {
      state:   invoiceSkipped.value ? 'skipped' : (invDone ? 'done' : (a.invoice.length ? 'active' : 'pending')),
      label:   invoiceSkipped.value ? '无需开票' : (invDone ? '已开票' : '待开票'),
      summary: (!invoiceSkipped.value && invDone) ? `¥${fmtAmt(r.actual_invoice_amount)}` : null,
    },
    collection: {
      state:   collDone ? 'done' : (paid.value > 0 ? 'partial' : (a.collection.length ? 'active' : 'pending')),
      label:   collDone ? '已收齐' : (paid.value > 0 ? `已收 ${Math.round(paidPct.value * 100)}%` : '待回款'),
      summary: estimated.value > 0 ? `¥${fmtAmt(paid.value)} / ¥${fmtAmt(estimated.value)}` : null,
    },
  }
})

// ── 3节点定义 ─────────────────────────────────────────────────────────────────
const NODES = [
  { stage: 'reconciliation', label: '对账', icon: '✓',  accent: '#1976d2' },
  { stage: 'invoice',        label: '开票', icon: '🧾', accent: '#8e63c5' },
  { stage: 'collection',     label: '回款', icon: '💰', accent: '#2e9e5b' },
]
const NODE_ACCENT = { reconciliation: '#1976d2', invoice: '#8e63c5', collection: '#2e9e5b', dunning: '#c96342' }

// ── 节点点击展开 ──────────────────────────────────────────────────────────────
const activeNode = ref(null)

function getDefaultNode() {
  const r = props.rec
  if (!r.reconciliation_date) return 'reconciliation'
  const invDone = !!(r.invoice_date || Number(r.actual_invoice_amount) > 0)
  if (!invoiceSkipped.value && !invDone) return 'invoice'
  return 'collection'
}

function clickNode(stage) {
  const next = activeNode.value === stage ? null : stage
  activeNode.value = next
  if (next) composeStage.value = next
}

// ── 面板动画 ─────────────────────────────────────────────────────────────────
const visible = ref(false)
function close() { visible.value = false; setTimeout(() => emit('close'), 220) }

// ── 概要信息条 ────────────────────────────────────────────────────────────────
const infoOpen = ref(false)

// ── 催收跟进折叠 ──────────────────────────────────────────────────────────────
const dunningOpen = ref(true)

// ── 操作轨迹 ─────────────────────────────────────────────────────────────────
const auditOpen    = ref(false)
const auditLoaded  = ref(false)
const auditLoading = ref(false)
const auditLog     = ref([])

async function toggleAudit() {
  auditOpen.value = !auditOpen.value
  if (auditOpen.value && !auditLoaded.value) {
    auditLoading.value = true
    try {
      const res = await ar.recordAudit(props.rec.id)
      auditLog.value = res.data || []
      auditLoaded.value = true
    } catch (e) { toast.error(errMsg(e)) }
    finally { auditLoading.value = false }
  }
}
function fmtAuditTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d)) return iso.slice(0, 16).replace('T', ' ')
  const today = todayCST()
  const ds = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
  const hm  = `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
  return ds === today ? `今天 ${hm}` : `${ds.slice(5)} ${hm}`
}

// ── 字段行内编辑 ──────────────────────────────────────────────────────────────
const editingField = ref('')
const fieldBuf     = ref('')
const fieldInp     = ref(null)

function beginField(field, cur) {
  if (!props.canWrite) return
  editingField.value = field
  fieldBuf.value     = cur ?? ''
  nextTick(() => fieldInp.value?.focus())
}
async function saveField() {
  const field = editingField.value
  if (!field) return
  editingField.value = ''
  const val = fieldBuf.value === '' ? null : fieldBuf.value
  if ((props.rec[field] ?? null) === val) return
  await saveFieldValue(field, val)
}
async function saveFieldValue(field, val) {
  try {
    const res = await ar.updateRecord(props.rec.id, { [field]: val })
    Object.assign(props.rec, res.data)
    emit('field-saved', { id: props.rec.id, ...res.data })
    toast.success('已保存')
  } catch (e) { toast.error(errMsg(e)) }
}
function setToday(field) { if (props.canWrite) saveFieldValue(field, todayCST()) }

// ── 回款 ─────────────────────────────────────────────────────────────────────
const DEPT_OPTS = computed(() => DEPARTMENTS.filter(d => d !== props.rec.delivery_dept))
const payForm   = reactive({ amount: '', payment_date: '', source: '回款', counterparty_dept: '', notes: '' })
const addingPay = ref(false)

async function submitPayment() {
  if (!(Number(payForm.amount) > 0))                                   { toast.error('请填写金额'); return }
  if (!payForm.payment_date)                                            { toast.error('请选择日期'); return }
  if (payForm.source === '内部往来' && !payForm.counterparty_dept)     { toast.error('请选择往来事业部'); return }
  addingPay.value = true
  try {
    await ar.addPayment(props.rec.id, {
      amount: payForm.amount, payment_date: payForm.payment_date, source: payForm.source,
      counterparty_dept: payForm.source === '内部往来' ? payForm.counterparty_dept : '',
      notes: payForm.notes,
    })
    await refreshRecordAndPayments()
    payForm.amount = ''; payForm.notes = ''; payForm.counterparty_dept = ''
    toast.success(payForm.source === '内部往来' ? '已登记内部往来核销' : '已登记回款')
  } catch (e) { toast.error(errMsg(e)) }
  finally { addingPay.value = false }
}
async function settleRemaining() {
  if (!(outstanding.value > 0)) return
  if (!confirm(`登记一笔 ¥${fmtAmt(outstanding.value)} 的回款，结清全部余款？`)) return
  addingPay.value = true
  try {
    await ar.addPayment(props.rec.id, { amount: outstanding.value, payment_date: todayCST(), source: '回款', notes: '结清余款' })
    await refreshRecordAndPayments()
    toast.success('已结清余款')
  } catch (e) { toast.error(errMsg(e)) }
  finally { addingPay.value = false }
}
async function deletePayment(p) {
  if (!confirm(`删除第 ${p.payment_no} 笔回款（¥${p.amount}）？`)) return
  try {
    await ar.deletePayment(props.rec.id, p.id)
    await refreshRecordAndPayments()
    toast.success('已删除')
  } catch (e) { toast.error(errMsg(e)) }
}
async function refreshRecordAndPayments() {
  const [recRes, payRes] = await Promise.all([ar.getRecord(props.rec.id), ar.listPayments(props.rec.id)])
  Object.assign(props.rec, recRes.data)
  emit('field-saved', { id: props.rec.id, ...recRes.data })
  payments.value = Array.isArray(payRes.data) ? payRes.data : []
}

// ── 活动管理 ─────────────────────────────────────────────────────────────────
const ACT_ICON = { call: '📞', email: '📧', visit: '🚶', meeting: '💬', system: '⚙️', note: '📝', other: '💡' }
const STATUS_COLOR = { in_progress: '#1565c0', pending: '#e8830c', resolved: '#2e7d32', no_response: '#9e9e9e' }
const STATUSES = [
  { v: 'in_progress', l: '跟进中' }, { v: 'pending', l: '待回复' },
  { v: 'resolved',    l: '已解决' }, { v: 'no_response', l: '无响应' },
]

const editActId  = ref(null)
const editActBuf = reactive({ note: '', status: 'in_progress', follow_up_date: '' })

function startActEdit(act) {
  editActId.value  = act.id
  editActBuf.note  = act.note || ''
  editActBuf.status = act.status || 'in_progress'
  editActBuf.follow_up_date = act.follow_up_date || ''
}
async function commitActEdit(act) {
  if (!editActBuf.note.trim()) return
  try {
    const res = await ar.updateActivity(props.rec.id, act.id, {
      note: editActBuf.note, status: editActBuf.status,
      follow_up_date: editActBuf.follow_up_date || null,
    })
    const i = allActivities.value.findIndex(a => a.id === act.id)
    if (i !== -1) allActivities.value[i] = res.data
    editActId.value = null
    toast.success('已更新')
  } catch (e) { toast.error(errMsg(e)) }
}
async function deleteAct(act) {
  if (!confirm(`删除这条${act.act_type_display || ''}记录？`)) return
  try {
    await ar.deleteActivity(props.rec.id, act.id)
    allActivities.value = allActivities.value.filter(a => a.id !== act.id)
    emit('field-saved', { id: props.rec.id, activity_count: Math.max(0, (props.rec.activity_count || 1) - 1) })
    toast.success('已删除')
  } catch (e) { toast.error(errMsg(e)) }
}
async function toggleActStatus(act) {
  const order = ['in_progress', 'pending', 'resolved', 'no_response']
  const next  = order[(order.indexOf(act.status) + 1) % order.length]
  try {
    const res = await ar.updateActivity(props.rec.id, act.id, { note: act.note, status: next })
    const i   = allActivities.value.findIndex(a => a.id === act.id)
    if (i !== -1) allActivities.value[i] = res.data
  } catch (e) { toast.error(errMsg(e)) }
}
function fmtActTime(iso) { return iso ? iso.replace('T', ' ').slice(0, 16) : '' }

// ── 附件 ─────────────────────────────────────────────────────────────────────
function fileIcon(att) {
  const ext = (att.file_name || '').split('.').pop().toLowerCase()
  if (ext === 'pdf') return '📄'
  if (['xlsx','xls','csv'].includes(ext)) return '📊'
  if (['docx','doc'].includes(ext)) return '📝'
  return '📎'
}
function fmtSize(b) {
  if (b == null) return ''
  if (b < 1024)    return b + 'B'
  if (b < 1048576) return (b / 1024).toFixed(1) + 'KB'
  return (b / 1048576).toFixed(1) + 'MB'
}
const dragOverStage = ref('')

async function uploadTo(file, stage) {
  if (!file) return
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  const ALLOWED = ['.jpg','.jpeg','.png','.gif','.webp','.pdf','.xlsx','.xls','.docx','.doc','.txt','.csv']
  if (!ALLOWED.includes(ext)) { toast.error(`不支持 ${ext} 格式`); return }
  if (file.size > 20 * 1024 * 1024) { toast.error('文件不能超过 20MB'); return }
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('stage', stage)
    const res = await ar.uploadAttachment(props.rec.id, fd)
    attachments.value.unshift(res.data)
    emit('field-saved', { id: props.rec.id, attachment_count: (props.rec.attachment_count || 0) + 1 })
    toast.success(`已上传：${file.name}`)
  } catch (e) { toast.error(errMsg(e)) }
}
async function deleteAtt(att) {
  if (!confirm(`删除附件「${att.file_name}」？`)) return
  try {
    await ar.deleteAttachment(props.rec.id, att.id)
    attachments.value = attachments.value.filter(a => a.id !== att.id)
    emit('field-saved', { id: props.rec.id, attachment_count: Math.max(0, (props.rec.attachment_count || 1) - 1) })
    toast.success('已删除')
  } catch (e) { toast.error(errMsg(e)) }
}

// ── 录入条 ───────────────────────────────────────────────────────────────────
const ACT_TYPES = [
  { v: 'call', l: '📞', t: '电话' }, { v: 'email', l: '📧', t: '邮件' },
  { v: 'visit', l: '🚶', t: '拜访' }, { v: 'meeting', l: '💬', t: '会议' }, { v: 'note', l: '📝', t: '备注' },
]
const composeStage = ref('dunning')
const compose      = reactive({ act_type: 'call', note: '', status: 'in_progress', follow_up_date: '' })
const adding       = ref(false)
const composeTa    = ref(null)
const STAGE_LABEL  = { reconciliation: '对账', invoice: '开票', collection: '回款', dunning: '催款' }

const QUICK_PHRASES = ['已电话联系，承诺近期付款', '对方财务已确认，走流程中', '已发送对账单/催款函', '客户资金紧张，申请延期', '多次联系暂无回复']
function insertPhrase(p) {
  compose.note = compose.note.trim() ? compose.note.trim() + '；' + p : p
  nextTick(() => composeTa.value?.focus())
}
function focusCompose(stage) {
  composeStage.value = stage
  nextTick(() => composeTa.value?.focus())
}

async function submitCompose() {
  if (!compose.note.trim()) { toast.error('请填写跟进内容'); return }
  adding.value = true
  try {
    const res = await ar.addActivity(props.rec.id, {
      stage: composeStage.value, act_type: compose.act_type,
      note: compose.note, status: compose.status,
      follow_up_date: compose.follow_up_date || null,
    })
    allActivities.value.unshift(res.data)
    emit('field-saved', { id: props.rec.id, activity_count: (props.rec.activity_count || 0) + 1 })
    compose.note = ''; compose.follow_up_date = ''
    toast.success(`已记录到「${STAGE_LABEL[composeStage.value]}」`)
  } catch (e) { toast.error(errMsg(e)) }
  finally { adding.value = false }
}

// ── 催款信息 ─────────────────────────────────────────────────────────────────
const daysSinceLastDun = computed(() => {
  const last = actsByStage.value.dunning[0]
  if (!last?.created_at) return null
  const d = new Date(last.created_at.replace(' ', 'T'))
  if (isNaN(d)) return null
  return Math.floor((Date.now() - d.getTime()) / 86400000)
})

// ── 催款函 ───────────────────────────────────────────────────────────────────
const showLetter = ref(false)
const letterText = ref('')
function fmtFull(v) {
  const n = Number(v || 0)
  return isNaN(n) ? '0.00' : n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function genDunningLetter() {
  const r = props.rec
  const today = todayCST()
  const overdueLine = overdueDays.value > 0
    ? `该款项已逾期 ${overdueDays.value} 天，敬请贵司高度重视。`
    : (r.due_date ? `上述款项应于 ${r.due_date} 前结清。` : '')
  letterText.value = [
    '催 款 函', '',
    `致：${r.customer_name || '贵单位'}`, '',
    `贵司与我司业务往来中，截至 ${today}，下列款项尚未结清：`, '',
    `　项目名称：${r.short_name || r.customer_name || '—'}`,
    `　应收金额：¥${fmtFull(estimated.value)}`,
    `　已收金额：¥${fmtFull(paid.value)}`,
    `　未收金额：¥${fmtFull(outstanding.value)}`,
    r.invoice_date ? `　开票日期：${r.invoice_date}` : '',
    r.due_date     ? `　应收到期：${r.due_date}` : '',
    '', overdueLine,
    '请贵司在收到本函后尽快安排付款。如款项已付，请忽略本函并提供付款凭证，以便我司核对。',
    '', '特此函告。', '',
    r.collector ? `经办人：${r.collector}` : '',
    today,
  ].filter(l => l !== '').join('\n')
  showLetter.value = true
}
async function copyLetter() {
  const ok = await copyText(letterText.value)
  ok ? toast.success('催款函已复制') : toast.error('复制失败')
}

async function copySummary() {
  const r = props.rec
  const invDone = !!(r.invoice_date || Number(r.actual_invoice_amount) > 0)
  const lastDun = actsByStage.value.dunning[0]
  const lines = [
    `【${r.short_name || r.customer_name}】应收摘要`,
    `客户：${r.customer_name || '—'}　交付部门：${r.delivery_dept || '—'}`,
    `应收 ¥${fmtAmt(estimated.value)}　已收 ¥${fmtAmt(paid.value)}　欠款 ¥${fmtAmt(outstanding.value)}`,
    overdueDays.value > 0 ? `⚠️ 已逾期 ${overdueDays.value} 天` : `应收到期：${r.due_date || '—'}`,
    `对账：${r.reconciliation_date || '未对账'}　开票：${invDone ? '¥' + fmtAmt(r.actual_invoice_amount) + (r.invoice_date ? ' / ' + r.invoice_date : '') : '未开票'}`,
    r.collector ? `催收负责人：${r.collector}` : '',
    r.target_collection_date ? `目标回款日：${r.target_collection_date}` : '',
    lastDun ? `最近跟进（${(lastDun.created_at || '').slice(0, 10)}）：${lastDun.note}` : '',
  ].filter(Boolean)
  const ok = await copyText(lines.join('\n'))
  ok ? toast.success('已复制催收摘要') : toast.error('复制失败')
}

// ── 生命周期钩子 ──────────────────────────────────────────────────────────────
onMounted(() => {
  requestAnimationFrame(() => { visible.value = true })
  activeNode.value = getDefaultNode()
  document.addEventListener('paste', onPaste)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('paste', onPaste)
  document.removeEventListener('keydown', onKey)
})

function onPaste(e) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) { uploadTo(new File([f], `clipboard-${Date.now()}.png`, { type: f.type }), composeStage.value); e.preventDefault(); break }
    }
  }
}
function onKey(e) {
  if (e.key !== 'Escape') return
  if (showLetter.value)   { showLetter.value = false; return }
  if (editingField.value) { editingField.value = ''; return }
  if (editActId.value)    { editActId.value = null; return }
  close()
}
</script>

<template>
  <Teleport to="body">
    <div class="ap-backdrop" :class="{ 'ap-open': visible }" @click.self="close"></div>
    <div class="ap-panel" :class="{ 'ap-open': visible }">

      <!-- ═══ 头部 ═══ -->
      <div class="ap-header">
        <div class="ap-htop">
          <div class="ap-title">
            <span class="ap-proj" :title="rec.short_name || rec.customer_name">{{ rec.short_name || rec.customer_name }}</span>
            <span v-if="rec.customer_name && rec.customer_name !== rec.short_name" class="ap-sub">{{ rec.customer_name }}</span>
          </div>
          <div class="ap-hbtns">
            <button class="ap-icobtn" :class="{ on: infoOpen }" title="概要信息" @click="infoOpen = !infoOpen">ℹ</button>
            <button class="ap-icobtn" title="复制催收摘要" @click="copySummary">📋</button>
            <button class="ap-close" title="关闭 (Esc)" @click="close">✕</button>
          </div>
        </div>
        <div class="ap-money">
          <div class="ap-money-row">
            <span class="ap-m-est">应收 ¥{{ fmtAmt(estimated) }}</span>
            <span class="ap-m-pct">{{ Math.round(paidPct * 100) }}%</span>
          </div>
          <div class="ap-bar"><div class="ap-bar-fill" :style="{ width: paidPct * 100 + '%' }"></div></div>
          <div class="ap-money-foot">
            <span class="ap-m-paid">已收 ¥{{ fmtAmt(paid) }}</span>
            <span class="ap-m-out" :class="{ 'ap-m-danger': overdueDays > 0 }">
              欠款 ¥{{ fmtAmt(outstanding) }}
              <em v-if="overdueDays > 0" class="ap-m-od">逾期{{ overdueDays }}天</em>
            </span>
          </div>
        </div>
      </div>

      <!-- ═══ 概要信息条（可折叠）═══ -->
      <transition name="info-drop">
        <div v-if="infoOpen" class="ap-info">
          <div class="ap-info-grid">
            <span class="ai-cell"><i>客户</i><b>{{ rec.customer_name || '—' }}</b></span>
            <span class="ai-cell"><i>部门</i><b>{{ rec.delivery_dept || '—' }}</b></span>
            <span class="ai-cell"><i>到期</i><b :class="{ 'ai-danger': overdueDays > 0 }">{{ rec.due_date || '—' }}</b></span>
            <span class="ai-cell"><i>PM</i><b>{{ rec.project_manager || '—' }}</b></span>
            <span class="ai-cell"><i>开票方式</i><b>{{ rec.invoice_mode || '—' }}</b></span>
          </div>
          <div class="ap-info-note">
            <span class="ai-note-lab">备注</span>
            <textarea v-if="editingField === 'notes'" ref="fieldInp" v-model="fieldBuf" class="ai-note-ta" rows="2"
              @blur="saveField" @keyup.escape="editingField = ''"></textarea>
            <span v-else class="ai-note-val" :class="{ empty: !rec.notes, ro: !canWrite }" @click="beginField('notes', rec.notes)">
              {{ rec.notes || (canWrite ? '＋ 添加备注' : '—') }}
            </span>
          </div>
        </div>
      </transition>

      <!-- ═══ 主体 ═══ -->
      <div class="ap-body">
        <template v-if="loading">
          <div v-for="n in 3" :key="n" class="ap-skeleton"></div>
        </template>
        <template v-else>

          <!-- ──── 3节点生命线 ──── -->
          <div class="lc-track">
            <template v-for="(node, idx) in NODES" :key="node.stage">
              <!-- 连接线 -->
              <div v-if="idx > 0" class="lc-line"
                :class="{ 'lc-line-done': nodeStates[NODES[idx-1].stage].state === 'done' || (NODES[idx-1].stage === 'invoice' && invoiceSkipped) }"></div>

              <!-- 节点 -->
              <button class="lc-node"
                :class="[`lc-ns-${nodeStates[node.stage].state}`, { 'lc-active': activeNode === node.stage }]"
                :style="activeNode === node.stage ? `--ac:${node.accent}` : ''"
                @click="clickNode(node.stage)">
                <span class="lc-dot" :class="`lc-dot-${nodeStates[node.stage].state}`"
                  :style="activeNode === node.stage ? `background:${node.accent};color:#fff;box-shadow:0 0 0 4px ${node.accent}22` : ''">
                  {{ nodeStates[node.stage].state === 'done' ? '✓' : (nodeStates[node.stage].state === 'skipped' ? '⏭' : node.icon) }}
                </span>
                <span class="lc-label">{{ node.label }}</span>
                <span class="lc-badge" :class="`lc-bg-${nodeStates[node.stage].state}`"
                  :style="activeNode === node.stage && nodeStates[node.stage].state === 'pending' ? `color:${node.accent};background:${node.accent}18` : ''">
                  {{ nodeStates[node.stage].label }}
                </span>
                <span v-if="nodeStates[node.stage].summary" class="lc-sum">{{ nodeStates[node.stage].summary }}</span>
                <span class="lc-caret" :class="{ open: activeNode === node.stage }">▾</span>
              </button>
            </template>
          </div>

          <!-- ──── 节点详情面板 ──── -->
          <transition name="nd">
            <div v-if="activeNode" :key="activeNode" class="lc-detail"
              :style="`--ac:${NODE_ACCENT[activeNode]}`">

              <!-- ── 对账节点 ── -->
              <template v-if="activeNode === 'reconciliation'">
                <div class="nd-title"><span class="nd-title-dot" style="background:#1976d2"></span>对账信息</div>
                <div class="nd-fields">
                  <div class="kf">
                    <span class="kf-lab">对账日期</span>
                    <input v-if="editingField === 'reconciliation_date'" ref="fieldInp" v-model="fieldBuf" type="date" class="kf-inp"
                      @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                    <span v-else class="kf-val" :class="{ empty: !rec.reconciliation_date, ro: !canWrite }"
                      @click="beginField('reconciliation_date', rec.reconciliation_date)">
                      {{ rec.reconciliation_date || (canWrite ? '＋ 标记对账日' : '—') }}
                    </span>
                    <button v-if="canWrite && !rec.reconciliation_date && editingField !== 'reconciliation_date'" class="kf-today" @click="setToday('reconciliation_date')">今天</button>
                  </div>
                </div>
                <!-- 活动列表 -->
                <div v-if="actsByStage.reconciliation.length" class="nd-acts">
                  <div v-for="act in actsByStage.reconciliation" :key="act.id" class="act-item"
                    :style="`--sc:${STATUS_COLOR[act.status] || '#888'}`">
                    <span class="act-dot">{{ ACT_ICON[act.act_type] || '💬' }}</span>
                    <div class="act-main">
                      <div class="act-top">
                        <span class="act-who">{{ act.created_by_name || '—' }}</span>
                        <button class="act-st" @click="act.can_edit && toggleActStatus(act)">{{ act.status_display }}</button>
                        <span class="act-time">{{ fmtActTime(act.created_at) }}</span>
                        <template v-if="act.can_edit && editActId !== act.id">
                          <button class="act-ico" @click="startActEdit(act)">✏️</button>
                          <button class="act-ico act-ico-del" @click="deleteAct(act)">🗑</button>
                        </template>
                      </div>
                      <template v-if="editActId === act.id">
                        <textarea v-model="editActBuf.note" class="act-edit-ta" rows="2"></textarea>
                        <div class="act-edit-foot">
                          <select v-model="editActBuf.status" class="act-sel"><option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option></select>
                          <input v-model="editActBuf.follow_up_date" type="date" class="act-sel" />
                          <button class="act-save" @click="commitActEdit(act)">保存</button>
                          <button class="act-cancel" @click="editActId = null">取消</button>
                        </div>
                      </template>
                      <template v-else>
                        <div class="act-note">{{ act.note }}</div>
                        <div v-if="act.follow_up_date" class="act-fu">📅 计划跟进 {{ act.follow_up_date }}</div>
                      </template>
                    </div>
                  </div>
                </div>
                <!-- 附件 -->
                <div v-if="attsByStage.reconciliation.length || canWrite" class="nd-atts">
                  <div v-for="att in attsByStage.reconciliation.filter(a => !a.is_image)" :key="att.id" class="att-file">
                    <span>{{ fileIcon(att) }}</span>
                    <a :href="att.download_url" target="_blank" class="att-fname">{{ att.file_name }}</a>
                    <span class="att-meta">{{ fmtSize(att.file_size) }}</span>
                    <button v-if="canWrite" class="att-del" @click="deleteAtt(att)">✕</button>
                  </div>
                  <div v-if="canWrite" class="att-dz" :class="{ over: dragOverStage === 'reconciliation' }"
                    @dragover.prevent="dragOverStage = 'reconciliation'" @dragleave="dragOverStage = ''"
                    @drop.prevent="e => { dragOverStage = ''; uploadTo(e.dataTransfer?.files?.[0], 'reconciliation') }">
                    ⬆ 上传附件
                    <input type="file" class="att-dz-inp" accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.xlsx,.xls,.docx,.doc,.txt,.csv"
                      @change="e => { uploadTo(e.target.files[0], 'reconciliation'); e.target.value = '' }" />
                  </div>
                </div>
                <button v-if="canWrite" class="nd-compose-btn" @click="focusCompose('reconciliation')">＋ 记录对账跟进</button>
              </template>

              <!-- ── 开票节点 ── -->
              <template v-else-if="activeNode === 'invoice'">
                <!-- 已跳过 -->
                <div v-if="invoiceSkipped" class="nd-skip-card">
                  <span class="nd-skip-icon">⏭</span>
                  <div class="nd-skip-body">
                    <b>此笔应收标记为「无需开票」，开票环节已跳过</b>
                    <span>款项将直接进入回款流程</span>
                  </div>
                  <button v-if="canWrite" class="nd-skip-undo" @click="saveFieldValue('invoice_mode', null)">撤销跳过</button>
                </div>
                <template v-else>
                  <div class="nd-title"><span class="nd-title-dot" style="background:#8e63c5"></span>开票信息</div>
                  <div class="nd-fields nd-fields-2">
                    <div class="kf">
                      <span class="kf-lab">实际开票金额</span>
                      <input v-if="editingField === 'actual_invoice_amount'" ref="fieldInp" v-model="fieldBuf" type="number" step="0.01" class="kf-inp" :placeholder="`预估 ${estimated}`"
                        @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                      <span v-else class="kf-val" :class="{ empty: rec.actual_invoice_amount == null, ro: !canWrite }"
                        @click="beginField('actual_invoice_amount', rec.actual_invoice_amount)">
                        {{ rec.actual_invoice_amount != null ? '¥' + fmtAmt(rec.actual_invoice_amount) : (canWrite ? '＋ 填写' : '—') }}
                      </span>
                    </div>
                    <div class="kf">
                      <span class="kf-lab">开票日期</span>
                      <input v-if="editingField === 'invoice_date'" ref="fieldInp" v-model="fieldBuf" type="date" class="kf-inp"
                        @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                      <span v-else class="kf-val" :class="{ empty: !rec.invoice_date, ro: !canWrite }" @click="beginField('invoice_date', rec.invoice_date)">
                        {{ rec.invoice_date || (canWrite ? '＋ 选择' : '—') }}
                      </span>
                      <button v-if="canWrite && !rec.invoice_date && editingField !== 'invoice_date'" class="kf-today" @click="setToday('invoice_date')">今天</button>
                    </div>
                    <div class="kf">
                      <span class="kf-lab">税额</span>
                      <input v-if="editingField === 'tax_amount'" ref="fieldInp" v-model="fieldBuf" type="number" step="0.01" class="kf-inp" placeholder="0.00"
                        @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                      <span v-else class="kf-val" :class="{ empty: rec.tax_amount == null, ro: !canWrite }" @click="beginField('tax_amount', rec.tax_amount)">
                        {{ rec.tax_amount != null ? '¥' + fmtAmt(rec.tax_amount) : (canWrite ? '＋ 填写' : '—') }}
                      </span>
                    </div>
                    <div class="kf">
                      <span class="kf-lab">开票批次号</span>
                      <input v-if="editingField === 'invoice_batch_no'" ref="fieldInp" v-model="fieldBuf" type="text" class="kf-inp" placeholder="批次号"
                        @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                      <span v-else class="kf-val" :class="{ empty: !rec.invoice_batch_no, ro: !canWrite }" @click="beginField('invoice_batch_no', rec.invoice_batch_no)">
                        {{ rec.invoice_batch_no || (canWrite ? '＋ 关联批次' : '—') }}
                      </span>
                    </div>
                  </div>
                  <div v-if="rec.invoice_batch_no" class="kf-batch-hint">🔗 已并入批次 <b>{{ rec.invoice_batch_no }}</b></div>
                  <button v-if="canWrite" class="nd-skip-toggle" @click="saveFieldValue('invoice_mode', '不开票')">⏭ 标记为无需开票，跳过此步</button>
                </template>
                <!-- 活动列表 -->
                <div v-if="!invoiceSkipped && actsByStage.invoice.length" class="nd-acts">
                  <div v-for="act in actsByStage.invoice" :key="act.id" class="act-item" :style="`--sc:${STATUS_COLOR[act.status] || '#888'}`">
                    <span class="act-dot">{{ ACT_ICON[act.act_type] || '💬' }}</span>
                    <div class="act-main">
                      <div class="act-top">
                        <span class="act-who">{{ act.created_by_name || '—' }}</span>
                        <button class="act-st" @click="act.can_edit && toggleActStatus(act)">{{ act.status_display }}</button>
                        <span class="act-time">{{ fmtActTime(act.created_at) }}</span>
                        <template v-if="act.can_edit && editActId !== act.id">
                          <button class="act-ico" @click="startActEdit(act)">✏️</button>
                          <button class="act-ico act-ico-del" @click="deleteAct(act)">🗑</button>
                        </template>
                      </div>
                      <template v-if="editActId === act.id">
                        <textarea v-model="editActBuf.note" class="act-edit-ta" rows="2"></textarea>
                        <div class="act-edit-foot">
                          <select v-model="editActBuf.status" class="act-sel"><option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option></select>
                          <input v-model="editActBuf.follow_up_date" type="date" class="act-sel" />
                          <button class="act-save" @click="commitActEdit(act)">保存</button>
                          <button class="act-cancel" @click="editActId = null">取消</button>
                        </div>
                      </template>
                      <template v-else>
                        <div class="act-note">{{ act.note }}</div>
                        <div v-if="act.follow_up_date" class="act-fu">📅 计划跟进 {{ act.follow_up_date }}</div>
                      </template>
                    </div>
                  </div>
                </div>
                <!-- 附件 -->
                <div v-if="!invoiceSkipped && (attsByStage.invoice.length || canWrite)" class="nd-atts">
                  <div v-for="att in attsByStage.invoice.filter(a => !a.is_image)" :key="att.id" class="att-file">
                    <span>{{ fileIcon(att) }}</span>
                    <a :href="att.download_url" target="_blank" class="att-fname">{{ att.file_name }}</a>
                    <span class="att-meta">{{ fmtSize(att.file_size) }}</span>
                    <button v-if="canWrite" class="att-del" @click="deleteAtt(att)">✕</button>
                  </div>
                  <div v-if="canWrite" class="att-dz" :class="{ over: dragOverStage === 'invoice' }"
                    @dragover.prevent="dragOverStage = 'invoice'" @dragleave="dragOverStage = ''"
                    @drop.prevent="e => { dragOverStage = ''; uploadTo(e.dataTransfer?.files?.[0], 'invoice') }">
                    ⬆ 上传发票附件
                    <input type="file" class="att-dz-inp" accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.xlsx,.xls,.docx,.doc,.txt,.csv"
                      @change="e => { uploadTo(e.target.files[0], 'invoice'); e.target.value = '' }" />
                  </div>
                </div>
                <button v-if="canWrite && !invoiceSkipped" class="nd-compose-btn" @click="focusCompose('invoice')">＋ 记录开票跟进</button>
              </template>

              <!-- ── 回款节点 ── -->
              <template v-else-if="activeNode === 'collection'">
                <div class="nd-title"><span class="nd-title-dot" style="background:#2e9e5b"></span>回款记录</div>
                <!-- 进度 -->
                <div class="pay-prog">
                  <div class="pay-prog-bar"><div class="pay-prog-fill" :style="{ width: paidPct * 100 + '%' }"></div></div>
                  <div class="pay-prog-txt"><span>已收 ¥{{ fmtAmt(paid) }}</span><span>待收 ¥{{ fmtAmt(outstanding) }}</span></div>
                </div>
                <!-- 明细 -->
                <div v-if="payments.length" class="pay-list">
                  <div v-for="p in payments" :key="p.id" class="pay-item">
                    <span class="pay-no">#{{ p.payment_no }}</span>
                    <span class="pay-amt">¥{{ fmtAmt(p.amount) }}</span>
                    <span class="pay-date">{{ p.payment_date }}</span>
                    <span class="pay-src" :class="{ 'pay-src-other': p.source !== '回款' }">{{ p.source }}</span>
                    <span v-if="p.counterparty_dept" class="pay-cp">↔ {{ p.counterparty_dept }}</span>
                    <button v-if="canCollect && p.source !== '预收抵扣'" class="pay-del" @click="deletePayment(p)">🗑</button>
                  </div>
                </div>
                <div v-else class="pay-empty">暂无回款记录</div>
                <!-- 登记表单 -->
                <div v-if="canCollect && outstanding > 0" class="pay-form">
                  <div class="pay-srcs">
                    <button class="pay-src-tab" :class="{ on: payForm.source === '回款' }" @click="payForm.source = '回款'">💵 现金回款</button>
                    <button class="pay-src-tab" :class="{ on: payForm.source === '内部往来' }" @click="payForm.source = '内部往来'">↔ 内部往来</button>
                  </div>
                  <div class="pay-add">
                    <input v-model="payForm.amount" type="number" step="0.01" class="pay-inp pay-inp-amt" :placeholder="payForm.source === '内部往来' ? '核销金额' : '回款金额'" />
                    <input v-model="payForm.payment_date" type="date" class="pay-inp" />
                    <select v-if="payForm.source === '内部往来'" v-model="payForm.counterparty_dept" class="pay-inp pay-inp-dept">
                      <option value="" disabled>往来事业部</option>
                      <option v-for="d in DEPT_OPTS" :key="d" :value="d">{{ d }}</option>
                    </select>
                    <button class="pay-btn" :disabled="addingPay" @click="submitPayment">{{ addingPay ? '…' : '登记' }}</button>
                  </div>
                </div>
                <button v-if="canCollect && outstanding > 0" class="pay-settle" :disabled="addingPay" @click="settleRemaining">
                  ✓ 一键结清余款 ¥{{ fmtAmt(outstanding) }}
                </button>
                <!-- 活动列表 -->
                <div v-if="actsByStage.collection.length" class="nd-acts">
                  <div v-for="act in actsByStage.collection" :key="act.id" class="act-item" :style="`--sc:${STATUS_COLOR[act.status] || '#888'}`">
                    <span class="act-dot">{{ ACT_ICON[act.act_type] || '💬' }}</span>
                    <div class="act-main">
                      <div class="act-top">
                        <span class="act-who">{{ act.created_by_name || '—' }}</span>
                        <button class="act-st" @click="act.can_edit && toggleActStatus(act)">{{ act.status_display }}</button>
                        <span class="act-time">{{ fmtActTime(act.created_at) }}</span>
                        <template v-if="act.can_edit && editActId !== act.id">
                          <button class="act-ico" @click="startActEdit(act)">✏️</button>
                          <button class="act-ico act-ico-del" @click="deleteAct(act)">🗑</button>
                        </template>
                      </div>
                      <template v-if="editActId === act.id">
                        <textarea v-model="editActBuf.note" class="act-edit-ta" rows="2"></textarea>
                        <div class="act-edit-foot">
                          <select v-model="editActBuf.status" class="act-sel"><option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option></select>
                          <input v-model="editActBuf.follow_up_date" type="date" class="act-sel" />
                          <button class="act-save" @click="commitActEdit(act)">保存</button>
                          <button class="act-cancel" @click="editActId = null">取消</button>
                        </div>
                      </template>
                      <template v-else>
                        <div class="act-note">{{ act.note }}</div>
                        <div v-if="act.follow_up_date" class="act-fu">📅 计划跟进 {{ act.follow_up_date }}</div>
                      </template>
                    </div>
                  </div>
                </div>
                <!-- 附件 -->
                <div v-if="attsByStage.collection.length || canWrite" class="nd-atts">
                  <div v-for="att in attsByStage.collection.filter(a => !a.is_image)" :key="att.id" class="att-file">
                    <span>{{ fileIcon(att) }}</span>
                    <a :href="att.download_url" target="_blank" class="att-fname">{{ att.file_name }}</a>
                    <span class="att-meta">{{ fmtSize(att.file_size) }}</span>
                    <button v-if="canWrite" class="att-del" @click="deleteAtt(att)">✕</button>
                  </div>
                  <div v-if="canWrite" class="att-dz" :class="{ over: dragOverStage === 'collection' }"
                    @dragover.prevent="dragOverStage = 'collection'" @dragleave="dragOverStage = ''"
                    @drop.prevent="e => { dragOverStage = ''; uploadTo(e.dataTransfer?.files?.[0], 'collection') }">
                    ⬆ 上传回款凭证
                    <input type="file" class="att-dz-inp" accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.xlsx,.xls,.docx,.doc,.txt,.csv"
                      @change="e => { uploadTo(e.target.files[0], 'collection'); e.target.value = '' }" />
                  </div>
                </div>
                <button v-if="canWrite" class="nd-compose-btn" @click="focusCompose('collection')">＋ 记录回款跟进</button>
              </template>
            </div>
          </transition>

          <!-- ──── 催收跟进 ──── -->
          <section class="dun-section">
            <button class="dun-head" @click="dunningOpen = !dunningOpen">
              <span class="dun-icon" :class="{ 'dun-urgent': overdueDays > 0 }">🔔</span>
              <span class="dun-title">催收跟进</span>
              <span v-if="overdueDays > 0" class="dun-od">逾期 {{ overdueDays }} 天</span>
              <span v-if="actsByStage.dunning.length" class="dun-cnt">{{ actsByStage.dunning.length }} 条记录</span>
              <span class="dun-caret" :class="{ open: dunningOpen }">⌃</span>
            </button>
            <div v-show="dunningOpen" class="dun-body">
              <!-- 催收字段 -->
              <div class="dun-kf-row">
                <div class="kf">
                  <span class="kf-lab">催收负责人</span>
                  <input v-if="editingField === 'collector'" ref="fieldInp" v-model="fieldBuf" type="text" class="kf-inp" placeholder="姓名"
                    @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                  <span v-else class="kf-val" :class="{ empty: !rec.collector, ro: !canWrite }" @click="beginField('collector', rec.collector)">
                    {{ rec.collector || (canWrite ? '＋ 指定' : '—') }}
                  </span>
                </div>
                <div class="kf">
                  <span class="kf-lab">目标回款日</span>
                  <input v-if="editingField === 'target_collection_date'" ref="fieldInp" v-model="fieldBuf" type="date" class="kf-inp"
                    @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                  <span v-else class="kf-val" :class="{ empty: !rec.target_collection_date, ro: !canWrite }" @click="beginField('target_collection_date', rec.target_collection_date)">
                    {{ rec.target_collection_date || (canWrite ? '＋ 设定' : '—') }}
                  </span>
                </div>
              </div>
              <!-- 冷热度 + 催款函 -->
              <div class="dun-meta">
                <span v-if="daysSinceLastDun != null" class="dun-last" :class="{ cold: daysSinceLastDun >= 7 }">
                  <template v-if="daysSinceLastDun === 0">🔥 今天已跟进</template>
                  <template v-else>{{ daysSinceLastDun >= 7 ? '🥶' : '🕓' }} 上次跟进 {{ daysSinceLastDun }} 天前{{ daysSinceLastDun >= 7 ? ' · 建议再跟进' : '' }}</template>
                </span>
                <button class="dun-letter-btn" @click="genDunningLetter">📄 生成催款函</button>
              </div>
              <!-- 催款动态 -->
              <div v-if="actsByStage.dunning.length" class="nd-acts">
                <div v-for="act in actsByStage.dunning" :key="act.id" class="act-item" :style="`--sc:${STATUS_COLOR[act.status] || '#888'}`">
                  <span class="act-dot">{{ ACT_ICON[act.act_type] || '💬' }}</span>
                  <div class="act-main">
                    <div class="act-top">
                      <span class="act-who">{{ act.created_by_name || '—' }}</span>
                      <button class="act-st" @click="act.can_edit && toggleActStatus(act)">{{ act.status_display }}</button>
                      <span class="act-time">{{ fmtActTime(act.created_at) }}</span>
                      <template v-if="act.can_edit && editActId !== act.id">
                        <button class="act-ico" @click="startActEdit(act)">✏️</button>
                        <button class="act-ico act-ico-del" @click="deleteAct(act)">🗑</button>
                      </template>
                    </div>
                    <template v-if="editActId === act.id">
                      <textarea v-model="editActBuf.note" class="act-edit-ta" rows="2"></textarea>
                      <div class="act-edit-foot">
                        <select v-model="editActBuf.status" class="act-sel"><option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option></select>
                        <input v-model="editActBuf.follow_up_date" type="date" class="act-sel" />
                        <button class="act-save" @click="commitActEdit(act)">保存</button>
                        <button class="act-cancel" @click="editActId = null">取消</button>
                      </div>
                    </template>
                    <template v-else>
                      <div class="act-note">{{ act.note }}</div>
                      <div v-if="act.follow_up_date" class="act-fu">📅 计划跟进 {{ act.follow_up_date }}</div>
                    </template>
                  </div>
                </div>
              </div>
              <div v-else class="dun-empty">暂无催款跟进记录</div>
              <!-- 催款附件 -->
              <div v-if="attsByStage.dunning.length || canWrite" class="nd-atts">
                <div v-for="att in attsByStage.dunning.filter(a => !a.is_image)" :key="att.id" class="att-file">
                  <span>{{ fileIcon(att) }}</span>
                  <a :href="att.download_url" target="_blank" class="att-fname">{{ att.file_name }}</a>
                  <span class="att-meta">{{ fmtSize(att.file_size) }}</span>
                  <button v-if="canWrite" class="att-del" @click="deleteAtt(att)">✕</button>
                </div>
                <div v-if="canWrite" class="att-dz" :class="{ over: dragOverStage === 'dunning' }"
                  @dragover.prevent="dragOverStage = 'dunning'" @dragleave="dragOverStage = ''"
                  @drop.prevent="e => { dragOverStage = ''; uploadTo(e.dataTransfer?.files?.[0], 'dunning') }">
                  ⬆ 上传催款相关附件
                  <input type="file" class="att-dz-inp" accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.xlsx,.xls,.docx,.doc,.txt,.csv"
                    @change="e => { uploadTo(e.target.files[0], 'dunning'); e.target.value = '' }" />
                </div>
              </div>
            </div>
          </section>

          <!-- ──── 操作轨迹 ──── -->
          <section class="ap-audit">
            <button class="ap-audit-head" @click="toggleAudit">
              <span class="ap-audit-ico">📜</span>
              <span class="ap-audit-title">操作轨迹</span>
              <span class="ap-audit-hint">谁 · 何时 · 改了什么</span>
              <span class="ap-audit-caret" :class="{ open: auditOpen }">⌃</span>
            </button>
            <div v-if="auditOpen" class="ap-audit-body">
              <div v-if="auditLoading" class="ap-audit-empty">加载中…</div>
              <div v-else-if="!auditLog.length" class="ap-audit-empty">暂无操作记录</div>
              <div v-else class="ap-audit-list">
                <div v-for="(ev, i) in auditLog" :key="ev.id" class="ap-audit-item" :class="{ last: i === auditLog.length - 1 }">
                  <span class="ap-audit-dot">{{ ev.icon }}</span>
                  <div class="ap-audit-main">
                    <div class="ap-audit-act">{{ ev.action }}<span v-if="ev.detail" class="ap-audit-detail"> {{ ev.detail }}</span></div>
                    <div class="ap-audit-meta">{{ ev.user_name }} · {{ fmtAuditTime(ev.created_at) }}</div>
                  </div>
                </div>
              </div>
            </div>
          </section>

        </template>
      </div><!-- /ap-body -->

      <!-- ═══ 催款函弹层 ═══ -->
      <div v-if="showLetter" class="lt-overlay" @click.self="showLetter = false">
        <div class="lt-modal">
          <div class="lt-head">
            <span class="lt-title">📄 催款函草稿</span>
            <button class="lt-close" @click="showLetter = false">✕</button>
          </div>
          <textarea v-model="letterText" class="lt-ta" rows="16"></textarea>
          <div class="lt-foot">
            <span class="lt-hint">可编辑后复制 · 粘贴到微信/邮件/Word</span>
            <button class="lt-copy" @click="copyLetter">复制全文</button>
          </div>
        </div>
      </div>

      <!-- ═══ 录入条 ═══ -->
      <div v-if="canWrite && !loading" class="ap-compose">
        <div class="ap-cmp-row1">
          <button v-for="t in ACT_TYPES" :key="t.v" class="ap-cmp-type" :class="{ on: compose.act_type === t.v }" :title="t.t" @click="compose.act_type = t.v">{{ t.l }}</button>
          <span class="ap-cmp-target">记入 <b :style="{ color: NODE_ACCENT[composeStage] || '#c96342' }">{{ STAGE_LABEL[composeStage] }}</b></span>
        </div>
        <div class="ap-cmp-phrases">
          <button v-for="p in QUICK_PHRASES" :key="p" class="ap-cmp-phrase" @click="insertPhrase(p)">{{ p }}</button>
        </div>
        <textarea v-model="compose.note" ref="composeTa" class="ap-cmp-ta" rows="2"
          :placeholder="`记录${STAGE_LABEL[composeStage]}跟进…（Ctrl+Enter 保存）`"
          @keydown.ctrl.enter.prevent="submitCompose"></textarea>
        <div class="ap-cmp-row2">
          <select v-model="compose.status" class="ap-cmp-sel">
            <option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option>
          </select>
          <input v-model="compose.follow_up_date" type="date" class="ap-cmp-sel" title="计划跟进日期" />
          <button class="ap-cmp-btn" :disabled="adding || !compose.note.trim()" @click="submitCompose">{{ adding ? '保存…' : '记录' }}</button>
        </div>
      </div>

    </div><!-- /ap-panel -->
  </Teleport>
</template>

<style scoped>
/* ── 面板容器 ── */
.ap-backdrop { position: fixed; inset: 0; z-index: 700; background: rgba(40,24,12,.22); opacity: 0; transition: opacity .22s; }
.ap-backdrop.ap-open { opacity: 1; }
.ap-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: 580px; max-width: 97vw;
  z-index: 701; background: #fbf7f1; border-left: 1px solid rgba(180,140,110,.28);
  box-shadow: -10px 0 40px rgba(60,30,10,.16);
  display: flex; flex-direction: column; overflow: hidden;
  transform: translateX(100%); transition: transform .24s cubic-bezier(.4,0,.2,1);
}
.ap-panel.ap-open { transform: translateX(0); }

/* ── 头部 ── */
.ap-header { padding: 13px 16px 11px; border-bottom: 1px solid rgba(180,140,110,.2); background: linear-gradient(135deg,#fceede,#fbf7f1); flex-shrink: 0; }
.ap-htop { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.ap-title { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.ap-proj { font-size: 16px; font-weight: 800; color: #5a4636; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-sub  { font-size: 11.5px; color: #9b8070; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-hbtns { display: flex; align-items: center; gap: 5px; flex-shrink: 0; }
.ap-icobtn { border: none; background: rgba(0,0,0,.04); width: 26px; height: 26px; border-radius: 50%; font-size: 12px; cursor: pointer; transition: all .12s; }
.ap-icobtn:hover, .ap-icobtn.on { background: rgba(201,99,66,.14); }
.ap-close { border: none; background: rgba(0,0,0,.04); width: 26px; height: 26px; border-radius: 50%; font-size: 13px; color: #9b8070; cursor: pointer; flex-shrink: 0; transition: all .12s; }
.ap-close:hover { background: rgba(201,99,66,.14); color: #c96342; }

/* 金额进度 */
.ap-money { margin-top: 9px; }
.ap-money-row { display: flex; justify-content: space-between; align-items: baseline; }
.ap-m-est { font-size: 13px; font-weight: 800; color: #5a4636; }
.ap-m-pct { font-size: 12px; font-weight: 800; color: #2e9e5b; }
.ap-bar { height: 7px; border-radius: 4px; background: rgba(180,140,110,.18); overflow: hidden; margin: 4px 0; }
.ap-bar-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg,#66bb6a,#2e9e5b); transition: width .4s; }
.ap-money-foot { display: flex; justify-content: space-between; font-size: 11.5px; }
.ap-m-paid { color: #2e7d32; font-weight: 600; }
.ap-m-out  { color: #8a7665; font-weight: 600; }
.ap-m-danger { color: #c62828; }
.ap-m-od { font-style: normal; font-size: 10px; background: rgba(198,40,40,.12); color: #c62828; padding: 0 6px; border-radius: 7px; margin-left: 4px; font-weight: 700; }

/* ── 概要信息条 ── */
.info-drop-enter-active, .info-drop-leave-active { transition: all .18s ease; overflow: hidden; }
.info-drop-enter-from, .info-drop-leave-to { max-height: 0; opacity: 0; }
.info-drop-enter-to, .info-drop-leave-from { max-height: 200px; opacity: 1; }
.ap-info { background: rgba(252,238,222,.55); border-bottom: 1px solid rgba(180,140,110,.15); padding: 10px 16px; flex-shrink: 0; }
.ap-info-grid { display: flex; flex-wrap: wrap; gap: 6px 20px; }
.ai-cell { display: flex; flex-direction: column; gap: 1px; }
.ai-cell i { font-size: 10px; color: #a8917e; font-style: normal; }
.ai-cell b { font-size: 12px; color: #5a4636; font-weight: 700; }
.ai-danger { color: #c62828 !important; }
.ap-info-note { display: flex; align-items: flex-start; gap: 8px; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(180,140,110,.14); }
.ai-note-lab { font-size: 10px; color: #a8917e; flex-shrink: 0; padding-top: 3px; }
.ai-note-val { font-size: 12px; color: #5a4636; cursor: pointer; flex: 1; padding: 2px 7px; border-radius: 5px; border: 1px solid transparent; white-space: pre-wrap; word-break: break-word; }
.ai-note-val:hover { background: #fff; border-color: rgba(201,99,66,.22); }
.ai-note-val.empty { color: #c0ad9d; }
.ai-note-val.ro { cursor: default; }
.ai-note-val.ro:hover { background: none; border-color: transparent; }
.ai-note-ta { flex: 1; border: 1px solid rgba(201,99,66,.4); border-radius: 6px; padding: 5px 8px; font-size: 12px; color: #5a4636; resize: vertical; font-family: inherit; outline: none; box-sizing: border-box; }

/* ── 主体 ── */
.ap-body { flex: 1; overflow-y: auto; padding: 14px 14px 8px; display: flex; flex-direction: column; gap: 10px; scroll-behavior: smooth; }
.ap-skeleton { height: 66px; border-radius: 12px; background: linear-gradient(90deg,rgba(180,140,110,.08),rgba(180,140,110,.16),rgba(180,140,110,.08)); background-size: 200% 100%; animation: sk 1.3s ease infinite; }
@keyframes sk { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }

/* ── 3节点生命线轨道 ── */
.lc-track {
  display: flex; align-items: stretch; gap: 0;
  background: #fff; border-radius: 14px; border: 1px solid rgba(180,140,110,.2);
  padding: 14px 12px; flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(60,30,10,.04);
}
.lc-line {
  width: 20px; flex-shrink: 0; height: 2px; background: rgba(180,140,110,.25);
  align-self: center; border-radius: 2px; margin: 0 2px; transition: background .3s;
}
.lc-line-done { background: linear-gradient(90deg,#66bb6a,#2e9e5b); }

.lc-node {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 5px;
  padding: 8px 6px 10px; border: 1.5px solid rgba(180,140,110,.18); border-radius: 11px;
  background: #faf7f4; cursor: pointer; transition: all .18s; position: relative;
  min-width: 0;
}
.lc-node:hover { border-color: rgba(180,140,110,.45); background: #fff; box-shadow: 0 2px 8px rgba(60,30,10,.07); }
.lc-node.lc-active {
  border-color: var(--ac, #c96342); background: #fff;
  box-shadow: 0 3px 14px rgba(0,0,0,.1);
}
.lc-node.lc-active::after {
  content: '▾'; position: absolute; bottom: -18px; left: 50%; transform: translateX(-50%);
  color: var(--ac, #c96342); font-size: 16px; line-height: 1;
}
.lc-ns-skipped { opacity: .6; }

.lc-dot {
  width: 34px; height: 34px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 15px;
  background: #ede8e2; color: #a8917e; transition: all .18s; flex-shrink: 0;
}
.lc-dot-done    { background: linear-gradient(145deg,#66bb6a,#2e7d32); color: #fff; }
.lc-dot-active  { background: linear-gradient(145deg,#e07848,#c96342); color: #fff; }
.lc-dot-partial { background: linear-gradient(145deg,#ffb74d,#f57c00); color: #fff; }
.lc-dot-skipped { background: #ddd; color: #aaa; }

.lc-label { font-size: 12.5px; font-weight: 800; color: #5a4636; }
.lc-node.lc-active .lc-label { color: var(--ac, #c96342); }

.lc-badge { font-size: 9.5px; font-weight: 700; padding: 1px 7px; border-radius: 7px; white-space: nowrap; }
.lc-bg-done    { color: #2e7d32; background: rgba(46,125,50,.1); }
.lc-bg-active  { color: #c96342; background: rgba(201,99,66,.1); }
.lc-bg-partial { color: #f57c00; background: rgba(245,124,0,.1); }
.lc-bg-pending { color: #9e8a78; background: rgba(158,138,120,.1); }
.lc-bg-skipped { color: #9e9e9e; background: rgba(158,158,158,.1); text-decoration: line-through; }

.lc-sum   { font-size: 10px; color: #a8917e; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.lc-caret { font-size: 13px; color: #c0ad9d; transition: transform .18s; }
.lc-caret.open { transform: rotate(180deg); color: var(--ac, #c96342); }

/* ── 节点详情面板 ── */
.nd-enter-active, .nd-leave-active { transition: all .2s ease; overflow: hidden; }
.nd-enter-from, .nd-leave-to { opacity: 0; transform: translateY(-6px); max-height: 0; }
.nd-enter-to, .nd-leave-from { opacity: 1; transform: translateY(0); max-height: 2000px; }

.lc-detail {
  background: #fff; border-radius: 12px; border: 1.5px solid var(--ac, rgba(180,140,110,.3));
  padding: 14px 14px 12px; display: flex; flex-direction: column; gap: 12px;
  box-shadow: 0 3px 12px rgba(0,0,0,.07);
}
.nd-title { display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 800; color: #5a4636; }
.nd-title-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

/* 开票跳过 */
.nd-skip-card {
  display: flex; align-items: center; gap: 12px; background: #f8f5f2; border: 1px solid rgba(180,140,110,.2);
  border-radius: 10px; padding: 12px 14px;
}
.nd-skip-icon { font-size: 22px; flex-shrink: 0; }
.nd-skip-body { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.nd-skip-body b { font-size: 12.5px; color: #5a4636; }
.nd-skip-body span { font-size: 11px; color: #9b8070; }
.nd-skip-undo { border: 1px solid rgba(201,99,66,.4); background: #fff; color: #c96342; font-size: 11px; font-weight: 600; padding: 5px 12px; border-radius: 7px; cursor: pointer; flex-shrink: 0; }
.nd-skip-undo:hover { background: rgba(201,99,66,.06); }
.nd-skip-toggle { border: 1px dashed rgba(158,158,158,.6); background: none; color: #9e9e9e; font-size: 11px; padding: 6px 12px; border-radius: 7px; cursor: pointer; align-self: flex-start; transition: all .12s; }
.nd-skip-toggle:hover { border-color: #8e63c5; color: #8e63c5; background: rgba(142,99,197,.05); }

/* 关键字段 */
.nd-fields { display: flex; flex-direction: column; gap: 8px; background: #faf7f4; border-radius: 9px; padding: 10px 12px; border: 1px solid rgba(180,140,110,.14); }
.nd-fields-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }
.kf { display: flex; align-items: center; gap: 8px; min-width: 0; }
.kf-lab { font-size: 11px; color: #a8917e; flex-shrink: 0; white-space: nowrap; }
.kf-val { font-size: 12.5px; color: #5a4636; cursor: pointer; padding: 2px 8px; border-radius: 6px; border: 1px solid transparent; transition: all .1s; font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kf-val:hover { background: #fff; border-color: rgba(var(--ac-rgb, 201,99,66),.25); }
.kf-val.empty { color: #c0ad9d; font-weight: 400; }
.kf-val.ro { cursor: default; }
.kf-val.ro:hover { background: none; border-color: transparent; }
.kf-inp { border: 1px solid rgba(201,99,66,.45); border-radius: 6px; padding: 3px 7px; font-size: 12.5px; color: #5a4636; background: #fff; outline: none; font-family: inherit; max-width: 140px; }
.kf-today { border: 1px solid rgba(180,140,110,.3); background: #fff; color: #8a7665; font-size: 10px; padding: 2px 7px; border-radius: 6px; cursor: pointer; flex-shrink: 0; transition: all .12s; }
.kf-today:hover { border-color: var(--ac, #c96342); color: var(--ac, #c96342); }
.kf-batch-hint { font-size: 11px; color: #8e63c5; background: rgba(142,99,197,.08); padding: 5px 9px; border-radius: 7px; }
.kf-batch-hint b { font-weight: 800; }

/* 活动列表 */
.nd-acts { display: flex; flex-direction: column; gap: 7px; padding-top: 2px; }
.act-item { display: flex; gap: 9px; }
.act-dot {
  width: 26px; height: 26px; flex-shrink: 0; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 13px;
  background: #fff; border: 2px solid var(--sc, #888);
  box-shadow: 0 0 0 2px #fff, 0 1px 4px rgba(60,30,10,.1);
}
.act-main {
  flex: 1; min-width: 0; background: #fbf7f1; border: 1px solid rgba(180,140,110,.15);
  border-left: 3px solid var(--sc, #888); border-radius: 8px; padding: 7px 10px;
}
.act-top { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.act-who  { font-size: 11.5px; font-weight: 700; color: #5a4636; }
.act-st   { border: none; font-size: 10px; font-weight: 700; cursor: pointer; padding: 1px 7px; border-radius: 7px; color: var(--sc); background: color-mix(in srgb, var(--sc) 12%, transparent); }
.act-time { font-size: 10px; color: #bda797; margin-left: auto; font-variant-numeric: tabular-nums; }
.act-ico  { border: none; background: none; font-size: 11px; cursor: pointer; padding: 1px 2px; border-radius: 4px; opacity: .65; }
.act-ico:hover { opacity: 1; background: rgba(0,0,0,.05); }
.act-ico-del:hover { color: #c62828; }
.act-note { font-size: 12.5px; color: #4a3a2c; white-space: pre-wrap; word-break: break-word; line-height: 1.5; margin-top: 3px; }
.act-fu   { font-size: 10.5px; color: #a8917e; margin-top: 2px; }
.act-edit-ta { width: 100%; border: 1px solid rgba(201,99,66,.4); border-radius: 6px; padding: 5px 8px; font-size: 12.5px; color: #5a4636; resize: vertical; font-family: inherit; box-sizing: border-box; outline: none; margin-top: 4px; }
.act-edit-foot { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; margin-top: 5px; }
.act-sel  { border: 1px solid rgba(180,140,110,.28); border-radius: 6px; font-size: 11.5px; padding: 3px 6px; color: #5a4636; background: #fff; outline: none; font-family: inherit; }
.act-save { padding: 3px 12px; border: none; border-radius: 6px; background: var(--ac, #c96342); color: #fff; font-size: 11.5px; font-weight: 700; cursor: pointer; margin-left: auto; }
.act-cancel { padding: 3px 10px; border: 1px solid rgba(180,140,110,.3); border-radius: 6px; background: #fff; font-size: 11.5px; cursor: pointer; color: #8a7665; }

/* 附件区 */
.nd-atts { display: flex; flex-direction: column; gap: 5px; }
.att-file { display: flex; align-items: center; gap: 7px; background: #faf7f4; border: 1px solid rgba(180,140,110,.15); border-radius: 7px; padding: 5px 9px; }
.att-fname { flex: 1; min-width: 0; font-size: 11.5px; color: #1565c0; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.att-fname:hover { text-decoration: underline; }
.att-meta { font-size: 10px; color: #a8917e; flex-shrink: 0; }
.att-del  { border: none; background: none; color: #c0ad9d; font-size: 11px; cursor: pointer; flex-shrink: 0; }
.att-del:hover { color: #c62828; }
.att-dz {
  border: 1.5px dashed rgba(180,140,110,.35); border-radius: 8px; padding: 7px; text-align: center;
  font-size: 11px; color: #a8917e; cursor: pointer; position: relative; transition: all .15s;
}
.att-dz:hover, .att-dz.over { background: rgba(201,99,66,.05); border-color: var(--ac, #c96342); color: var(--ac, #c96342); }
.att-dz-inp { position: absolute; inset: 0; opacity: 0; cursor: pointer; }

/* "在此阶段记录" 快捷按钮 */
.nd-compose-btn {
  border: 1px dashed rgba(180,140,110,.4); background: none; color: #a8917e; font-size: 11.5px;
  padding: 7px; border-radius: 8px; cursor: pointer; transition: all .12s; font-weight: 600;
  align-self: stretch; text-align: center;
}
.nd-compose-btn:hover { background: rgba(201,99,66,.04); border-color: var(--ac, #c96342); color: var(--ac, #c96342); }

/* 回款 */
.pay-prog { display: flex; flex-direction: column; gap: 4px; }
.pay-prog-bar { height: 8px; border-radius: 5px; background: rgba(180,140,110,.18); overflow: hidden; }
.pay-prog-fill { height: 100%; border-radius: 5px; background: linear-gradient(90deg,#66bb6a,#2e9e5b); transition: width .4s; }
.pay-prog-txt { display: flex; justify-content: space-between; font-size: 11px; color: #8a7665; font-weight: 600; }
.pay-list  { display: flex; flex-direction: column; gap: 4px; }
.pay-item  { display: flex; align-items: center; gap: 7px; background: #fff; border: 1px solid rgba(180,140,110,.16); border-radius: 8px; padding: 6px 10px; }
.pay-no   { font-size: 10px; color: #a8917e; font-weight: 700; flex-shrink: 0; }
.pay-amt  { font-size: 13px; font-weight: 800; color: #2e7d32; }
.pay-date { font-size: 11px; color: #8a7665; }
.pay-src  { font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 7px; color: #2e9e5b; background: rgba(46,158,91,.1); margin-left: auto; }
.pay-src-other { color: #e8830c; background: rgba(232,131,12,.1); }
.pay-cp  { font-size: 10px; color: #8a7665; }
.pay-del { border: none; background: none; font-size: 11px; cursor: pointer; opacity: .6; flex-shrink: 0; }
.pay-del:hover { opacity: 1; }
.pay-empty { font-size: 11.5px; color: #bda797; text-align: center; padding: 6px 0; }
.pay-form  { display: flex; flex-direction: column; gap: 6px; }
.pay-srcs  { display: flex; gap: 5px; }
.pay-src-tab { flex: 1; border: 1px solid rgba(180,140,110,.28); background: #fff; color: #8a7665; font-size: 11.5px; padding: 5px; border-radius: 7px; cursor: pointer; transition: all .12s; }
.pay-src-tab:hover { border-color: rgba(46,158,91,.5); }
.pay-src-tab.on { border-color: #2e9e5b; background: rgba(46,158,91,.1); color: #25844c; font-weight: 700; }
.pay-add { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.pay-inp  { border: 1px solid rgba(180,140,110,.3); border-radius: 7px; padding: 5px 8px; font-size: 12px; color: #5a4636; background: #fff; outline: none; font-family: inherit; min-width: 0; }
.pay-inp:focus { border-color: rgba(46,158,91,.5); }
.pay-inp-amt  { flex: 1; min-width: 90px; }
.pay-inp-dept { flex: 1; min-width: 110px; }
.pay-btn { padding: 6px 14px; border: none; border-radius: 7px; background: linear-gradient(120deg,#2e9e5b,#25844c); color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; flex-shrink: 0; }
.pay-btn:disabled { opacity: .5; cursor: default; }
.pay-settle { border: 1px dashed rgba(46,158,91,.5); background: rgba(46,158,91,.05); color: #25844c; font-size: 11.5px; font-weight: 700; padding: 7px; border-radius: 8px; cursor: pointer; transition: background .12s; }
.pay-settle:hover:not(:disabled) { background: rgba(46,158,91,.12); }
.pay-settle:disabled { opacity: .5; cursor: default; }

/* ── 催收跟进 ── */
.dun-section { border: 1px solid rgba(180,140,110,.2); border-radius: 12px; background: #fff; overflow: hidden; }
.dun-head { width: 100%; display: flex; align-items: center; gap: 8px; padding: 10px 13px; border: none; background: none; cursor: pointer; font-family: inherit; }
.dun-head:hover { background: rgba(201,99,66,.03); }
.dun-icon  { font-size: 15px; transition: transform .15s; }
.dun-icon.dun-urgent { animation: dun-pulse 1.4s ease-out infinite; }
@keyframes dun-pulse { 0% { filter: drop-shadow(0 0 0 rgba(239,83,80,.6)) } 100% { filter: drop-shadow(0 0 4px rgba(239,83,80,0)) } }
.dun-title { font-size: 13px; font-weight: 800; color: #5a4636; }
.dun-od    { font-size: 10px; font-weight: 700; padding: 1px 8px; border-radius: 7px; color: #c62828; background: rgba(198,40,40,.1); }
.dun-cnt   { font-size: 10.5px; color: #a8917e; }
.dun-caret { margin-left: auto; font-size: 13px; color: #c0ad9d; transform: rotate(180deg); transition: transform .2s; flex-shrink: 0; }
.dun-caret.open { transform: rotate(0deg); }
.dun-body  { padding: 0 13px 13px; display: flex; flex-direction: column; gap: 10px; }
.dun-kf-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; background: #faf7f4; border-radius: 9px; padding: 10px 12px; border: 1px solid rgba(180,140,110,.14); }
.dun-meta  { display: flex; align-items: center; gap: 8px; }
.dun-last  { font-size: 11px; color: #8a7665; }
.dun-last.cold { color: #c96342; font-weight: 600; }
.dun-letter-btn { margin-left: auto; border: 1px solid rgba(201,99,66,.35); background: #fff; color: #c96342; font-size: 11px; font-weight: 600; padding: 4px 11px; border-radius: 7px; cursor: pointer; flex-shrink: 0; }
.dun-letter-btn:hover { background: rgba(201,99,66,.07); }
.dun-empty { font-size: 11.5px; color: #bda797; text-align: center; padding: 4px 0; }

/* ── 操作轨迹 ── */
.ap-audit { border: 1px solid rgba(180,140,110,.2); border-radius: 12px; background: #fff; overflow: hidden; }
.ap-audit-head { width: 100%; display: flex; align-items: center; gap: 8px; padding: 10px 13px; border: none; background: none; cursor: pointer; font-family: inherit; }
.ap-audit-head:hover { background: rgba(201,99,66,.03); }
.ap-audit-ico   { font-size: 14px; }
.ap-audit-title { font-size: 13px; font-weight: 800; color: #5a4636; }
.ap-audit-hint  { font-size: 10.5px; color: #b0987e; }
.ap-audit-caret { margin-left: auto; font-size: 13px; color: #c0ad9d; transition: transform .2s; transform: rotate(180deg); flex-shrink: 0; }
.ap-audit-caret.open { transform: rotate(0deg); }
.ap-audit-body  { padding: 2px 13px 13px; }
.ap-audit-empty { font-size: 12px; color: #bda797; text-align: center; padding: 12px 0; }
.ap-audit-list  { position: relative; }
.ap-audit-item  { display: flex; gap: 9px; position: relative; padding-bottom: 10px; }
.ap-audit-item:not(.last)::before { content: ''; position: absolute; left: 11px; top: 23px; bottom: 0; width: 1.5px; background: rgba(180,140,110,.2); }
.ap-audit-dot   { width: 23px; height: 23px; flex-shrink: 0; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; background: #fbf7f1; border: 1px solid rgba(180,140,110,.25); z-index: 1; }
.ap-audit-main  { flex: 1; min-width: 0; padding-top: 1px; }
.ap-audit-act   { font-size: 12.5px; color: #4a3a2c; font-weight: 600; }
.ap-audit-detail{ color: #8a7665; font-weight: 400; }
.ap-audit-meta  { font-size: 10.5px; color: #a8917e; margin-top: 1px; }

/* ── 催款函弹层 ── */
.lt-overlay { position: fixed; inset: 0; z-index: 720; background: rgba(40,24,12,.4); display: flex; align-items: center; justify-content: center; padding: 20px; }
.lt-modal { width: 480px; max-width: 94vw; background: #fff; border-radius: 14px; box-shadow: 0 16px 50px rgba(60,30,10,.3); display: flex; flex-direction: column; overflow: hidden; }
.lt-head  { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid rgba(180,140,110,.18); background: linear-gradient(135deg,#fceede,#fff); }
.lt-title { font-size: 14px; font-weight: 800; color: #5a4636; }
.lt-close { border: none; background: rgba(0,0,0,.04); width: 26px; height: 26px; border-radius: 50%; font-size: 13px; color: #9b8070; cursor: pointer; }
.lt-close:hover { background: rgba(201,99,66,.12); color: #c96342; }
.lt-ta    { border: none; outline: none; resize: vertical; padding: 14px 18px; font-size: 13px; line-height: 1.8; color: #3a2e22; font-family: inherit; min-height: 280px; }
.lt-foot  { display: flex; align-items: center; gap: 10px; padding: 11px 16px; border-top: 1px solid rgba(180,140,110,.18); background: #fbf7f1; }
.lt-hint  { font-size: 11px; color: #a8917e; }
.lt-copy  { margin-left: auto; padding: 7px 22px; border: none; border-radius: 8px; background: linear-gradient(120deg,#c96342,#b5532f); color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; }
.lt-copy:hover { filter: brightness(1.06); }

/* ── 录入条 ── */
.ap-compose { padding: 9px 14px 11px; border-top: 1px solid rgba(180,140,110,.18); background: rgba(255,253,250,.94); flex-shrink: 0; display: flex; flex-direction: column; gap: 6px; }
.ap-cmp-row1 { display: flex; gap: 5px; align-items: center; }
.ap-cmp-type { border: 1px solid rgba(180,140,110,.25); background: #fff; border-radius: 8px; padding: 3px 8px; font-size: 14px; cursor: pointer; line-height: 1; transition: all .12s; }
.ap-cmp-type:hover { border-color: rgba(201,99,66,.5); }
.ap-cmp-type.on { border-color: #c96342; background: rgba(201,99,66,.1); transform: translateY(-1px); }
.ap-cmp-target { margin-left: auto; font-size: 11px; color: #a8917e; }
.ap-cmp-target b { font-weight: 800; }
.ap-cmp-phrases { display: flex; gap: 5px; overflow-x: auto; padding-bottom: 1px; scrollbar-width: none; }
.ap-cmp-phrases::-webkit-scrollbar { display: none; }
.ap-cmp-phrase { flex-shrink: 0; border: 1px solid rgba(180,140,110,.28); background: #fff; color: #8a7665; font-size: 11px; padding: 3px 9px; border-radius: 12px; cursor: pointer; white-space: nowrap; transition: all .12s; }
.ap-cmp-phrase:hover { border-color: #c96342; color: #c96342; background: rgba(201,99,66,.05); }
.ap-cmp-ta { width: 100%; border: 1px solid rgba(180,140,110,.25); border-radius: 9px; padding: 8px 10px; font-size: 13px; color: #5a4636; resize: vertical; min-height: 40px; font-family: inherit; background: #fff; outline: none; box-sizing: border-box; transition: border-color .12s; }
.ap-cmp-ta:focus { border-color: rgba(201,99,66,.55); }
.ap-cmp-row2 { display: flex; gap: 6px; align-items: center; }
.ap-cmp-sel { border: 1px solid rgba(180,140,110,.28); border-radius: 7px; font-size: 12px; padding: 5px 7px; color: #5a4636; background: #fff; outline: none; font-family: inherit; }
.ap-cmp-btn { margin-left: auto; padding: 6px 20px; border: none; border-radius: 8px; background: linear-gradient(120deg,#c96342,#b5532f); color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; transition: filter .12s; }
.ap-cmp-btn:hover:not(:disabled) { filter: brightness(1.06); }
.ap-cmp-btn:disabled { opacity: .45; cursor: default; }
</style>
