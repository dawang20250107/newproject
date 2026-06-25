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
        <!-- 金额进度 -->
        <div class="ap-money">
          <div class="ap-money-row">
            <div class="ap-m-left">
              <span class="ap-m-est">应收</span>
              <span class="ap-m-est-val">¥{{ fmtAmt(estimated) }}</span>
            </div>
            <div class="ap-m-chips">
              <span class="ap-chip ap-chip-paid">已收 ¥{{ fmtAmt(paid) }}</span>
              <span class="ap-chip" :class="overdueDays > 0 ? 'ap-chip-danger' : 'ap-chip-out'">
                欠 ¥{{ fmtAmt(outstanding) }}
                <em v-if="overdueDays > 0">逾期{{ overdueDays }}d</em>
              </span>
            </div>
          </div>
          <div class="ap-bar-wrap">
            <div class="ap-bar">
              <div class="ap-bar-fill" :style="{ width: paidPct * 100 + '%' }"></div>
            </div>
            <span class="ap-bar-pct" :class="paidPct >= 1 ? 'done' : ''">{{ Math.round(paidPct * 100) }}%</span>
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

              <!-- 连接器 -->
              <div v-if="idx > 0" class="lc-connector">
                <div class="lc-line"
                  :class="{
                    'lc-line-done': nodeStates[NODES[idx-1].stage].state === 'done' || (NODES[idx-1].stage === 'invoice' && invoiceSkipped),
                    'lc-line-skip': invoiceSkipped && node.stage === 'collection' && NODES[idx-1].stage === 'invoice',
                  }"></div>
                <span class="lc-arrow"
                  :class="{ 'lc-arrow-done': nodeStates[NODES[idx-1].stage].state === 'done' || (NODES[idx-1].stage === 'invoice' && invoiceSkipped) }">›</span>
              </div>

              <!-- 节点卡片 -->
              <button class="lc-node"
                :class="[`lc-ns-${nodeStates[node.stage].state}`, { 'lc-active': activeNode === node.stage }]"
                :style="`--ac:${node.accent}`"
                @click="clickNode(node.stage)">
                <!-- 步骤编号 -->
                <span class="lc-step">{{ idx + 1 }}</span>
                <!-- 图标圈 -->
                <span class="lc-dot" :class="`lc-dot-${nodeStates[node.stage].state}`">
                  {{ nodeStates[node.stage].state === 'done' ? '✓' : (nodeStates[node.stage].state === 'skipped' ? '⏭' : node.icon) }}
                </span>
                <!-- 标签 -->
                <span class="lc-label">{{ node.label }}</span>
                <!-- 状态 -->
                <span class="lc-badge" :class="`lc-bg-${nodeStates[node.stage].state}`">
                  {{ nodeStates[node.stage].label }}
                </span>
                <!-- 摘要 -->
                <span v-if="nodeStates[node.stage].summary" class="lc-sum">{{ nodeStates[node.stage].summary }}</span>
                <!-- 展开指示 -->
                <span class="lc-pip" :class="{ open: activeNode === node.stage }">▾</span>
              </button>
            </template>
          </div>

          <!-- ──── 节点详情面板 ──── -->
          <transition name="nd">
            <div v-if="activeNode" :key="activeNode" class="lc-detail"
              :style="`--ac:${NODE_ACCENT[activeNode]}`">

              <!-- ── 对账节点 ── -->
              <template v-if="activeNode === 'reconciliation'">
                <div class="nd-stage-header">
                  <span class="nd-stage-icon" style="background:linear-gradient(135deg,#42a5f5,#1565c0)">✓</span>
                  <span class="nd-stage-name">对账</span>
                  <span class="nd-stage-badge" :class="`lc-bg-${nodeStates.reconciliation.state}`">{{ nodeStates.reconciliation.label }}</span>
                  <span v-if="nodeStates.reconciliation.summary" class="nd-stage-sum">{{ nodeStates.reconciliation.summary }}</span>
                </div>
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
                <div class="nd-stage-header">
                  <span class="nd-stage-icon" style="background:linear-gradient(135deg,#ba68c8,#6a1b9a)">🧾</span>
                  <span class="nd-stage-name">开票</span>
                  <span class="nd-stage-badge" :class="`lc-bg-${nodeStates.invoice.state}`">{{ nodeStates.invoice.label }}</span>
                  <span v-if="nodeStates.invoice.summary" class="nd-stage-sum">{{ nodeStates.invoice.summary }}</span>
                </div>
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
                <div class="nd-stage-header">
                  <span class="nd-stage-icon" style="background:linear-gradient(135deg,#66bb6a,#1b5e20)">💰</span>
                  <span class="nd-stage-name">回款</span>
                  <span class="nd-stage-badge" :class="`lc-bg-${nodeStates.collection.state}`">{{ nodeStates.collection.label }}</span>
                  <span v-if="nodeStates.collection.summary" class="nd-stage-sum">{{ nodeStates.collection.summary }}</span>
                </div>
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
/* ════════════════════════════════════════════════════
   AR 生命线工作台 — Design System
   Palette: warm-cream base · stage-accent accents
   Elevation: flat / card / raised / modal
   ════════════════════════════════════════════════════ */

/* ── 面板 & 遮罩 ── */
.ap-backdrop {
  position: fixed; inset: 0; z-index: 700;
  background: rgba(28,18,8,.3);
  opacity: 0; transition: opacity .24s;
  backdrop-filter: blur(2px);
}
.ap-backdrop.ap-open { opacity: 1; }

.ap-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: 600px; max-width: 97vw;
  z-index: 701;
  background: #f8f5f0;
  border-left: 1px solid rgba(160,120,80,.2);
  box-shadow: -16px 0 56px rgba(40,20,8,.18);
  display: flex; flex-direction: column; overflow: hidden;
  transform: translateX(100%);
  transition: transform .28s cubic-bezier(.34,1.06,.64,1);
}
.ap-panel.ap-open { transform: translateX(0); }

/* ── 头部 ── */
.ap-header {
  padding: 14px 18px 12px;
  border-bottom: 1px solid rgba(160,120,80,.18);
  background: linear-gradient(160deg, #fdf0e0 0%, #faf5ee 60%, #f8f5f0 100%);
  flex-shrink: 0;
}
.ap-htop { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ap-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.ap-proj {
  font-size: 17px; font-weight: 900; color: #3d2a1a;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  letter-spacing: -.3px;
}
.ap-sub { font-size: 11.5px; color: #9b8070; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-hbtns { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.ap-icobtn {
  border: 1px solid rgba(160,120,80,.22);
  background: rgba(255,255,255,.7);
  width: 28px; height: 28px; border-radius: 8px; font-size: 12px;
  cursor: pointer; transition: all .14s; color: #7a6050;
}
.ap-icobtn:hover, .ap-icobtn.on {
  background: rgba(201,99,66,.1); border-color: rgba(201,99,66,.4); color: #c96342;
}
.ap-close {
  border: 1px solid rgba(160,120,80,.22); background: rgba(255,255,255,.7);
  width: 28px; height: 28px; border-radius: 8px; font-size: 13px;
  color: #9b8070; cursor: pointer; flex-shrink: 0; transition: all .14s;
}
.ap-close:hover { background: rgba(201,99,66,.1); border-color: rgba(201,99,66,.4); color: #c96342; }

/* 金额进度 */
.ap-money { margin-top: 10px; }
.ap-money-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; }
.ap-m-left { display: flex; align-items: baseline; gap: 5px; }
.ap-m-est { font-size: 11px; color: #9b8070; font-weight: 600; }
.ap-m-est-val { font-size: 15px; font-weight: 900; color: #3d2a1a; letter-spacing: -.3px; }
.ap-m-chips { display: flex; gap: 6px; align-items: center; }
.ap-chip {
  font-size: 10.5px; font-weight: 700; padding: 3px 9px; border-radius: 20px;
  white-space: nowrap;
}
.ap-chip-paid  { color: #1b5e20; background: rgba(46,125,50,.12); border: 1px solid rgba(46,125,50,.2); }
.ap-chip-out   { color: #6d5236; background: rgba(160,120,80,.1); border: 1px solid rgba(160,120,80,.2); }
.ap-chip-danger { color: #b71c1c; background: rgba(198,40,40,.1); border: 1px solid rgba(198,40,40,.25); }
.ap-chip-danger em { font-style: normal; font-size: 9.5px; margin-left: 3px; }
.ap-bar-wrap { display: flex; align-items: center; gap: 8px; }
.ap-bar {
  flex: 1; height: 8px; border-radius: 6px;
  background: rgba(160,120,80,.15); overflow: hidden;
}
.ap-bar-fill {
  height: 100%; border-radius: 6px;
  background: linear-gradient(90deg, #81c784, #2e9e5b);
  transition: width .5s cubic-bezier(.4,0,.2,1);
  position: relative;
}
.ap-bar-fill::after {
  content: ''; position: absolute; top: 0; right: 0; bottom: 0; width: 40px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.35));
  animation: bar-shine 2.2s ease-in-out infinite;
}
@keyframes bar-shine { 0%,100% { opacity: 0 } 50% { opacity: 1 } }
.ap-bar-pct { font-size: 11px; font-weight: 800; color: #2e9e5b; flex-shrink: 0; min-width: 30px; text-align: right; }
.ap-bar-pct.done { color: #1b5e20; }

/* ── 概要信息条 ── */
.info-drop-enter-active, .info-drop-leave-active { transition: all .2s ease; overflow: hidden; }
.info-drop-enter-from, .info-drop-leave-to { max-height: 0; opacity: 0; }
.info-drop-enter-to, .info-drop-leave-from { max-height: 220px; opacity: 1; }
.ap-info {
  background: linear-gradient(180deg, rgba(253,240,224,.7), transparent);
  border-bottom: 1px solid rgba(160,120,80,.14);
  padding: 10px 18px;
}
.ap-info-grid { display: flex; flex-wrap: wrap; gap: 6px 22px; }
.ai-cell { display: flex; flex-direction: column; gap: 1px; }
.ai-cell i { font-size: 9.5px; color: #a8917e; font-style: normal; text-transform: uppercase; letter-spacing: .4px; }
.ai-cell b { font-size: 12px; color: #4a3322; font-weight: 700; }
.ai-danger { color: #b71c1c !important; }
.ap-info-note { display: flex; align-items: flex-start; gap: 8px; margin-top: 9px; padding-top: 9px; border-top: 1px solid rgba(160,120,80,.13); }
.ai-note-lab { font-size: 9.5px; color: #a8917e; flex-shrink: 0; padding-top: 3px; text-transform: uppercase; letter-spacing: .4px; }
.ai-note-val { font-size: 12px; color: #4a3322; cursor: pointer; flex: 1; padding: 3px 8px; border-radius: 6px; border: 1.5px solid transparent; white-space: pre-wrap; word-break: break-word; transition: all .12s; }
.ai-note-val:hover { background: rgba(255,255,255,.8); border-color: rgba(201,99,66,.25); }
.ai-note-val.empty { color: #c0ad9d; }
.ai-note-val.ro { cursor: default; }
.ai-note-val.ro:hover { background: none; border-color: transparent; }
.ai-note-ta { flex: 1; border: 1.5px solid rgba(201,99,66,.4); border-radius: 6px; padding: 5px 8px; font-size: 12px; color: #4a3322; resize: vertical; font-family: inherit; outline: none; box-sizing: border-box; }

/* ── 主体滚动区 ── */
.ap-body { flex: 1; overflow-y: auto; padding: 14px 16px 8px; display: flex; flex-direction: column; gap: 10px; scroll-behavior: smooth; }
/* 滚动容器内每个块都锁定自然高度：.lc-detail / .dun-section / 审计区都带
   overflow:hidden，若被 flex 压缩，自动最小尺寸会塌缩为 0 进而裁切内容
   （表现为"工作台内容被压缩看不见"）。统一禁止收缩，超出由 .ap-body 滚动。 */
.ap-body > * { flex-shrink: 0; }
.ap-body::-webkit-scrollbar { width: 4px; }
.ap-body::-webkit-scrollbar-track { background: transparent; }
.ap-body::-webkit-scrollbar-thumb { background: rgba(160,120,80,.25); border-radius: 4px; }
.ap-skeleton {
  height: 70px; border-radius: 14px;
  background: linear-gradient(90deg, #f0ebe4 0%, #e8e0d6 50%, #f0ebe4 100%);
  background-size: 200% 100%; animation: sk 1.4s ease infinite;
}
@keyframes sk { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }

/* ════════════════════════════════════════════════════
   3 NODE LIFECYCLE TRACK
   ════════════════════════════════════════════════════ */
.lc-track {
  display: flex; align-items: center;
  background: #ffffff;
  border-radius: 18px;
  border: 1px solid rgba(160,120,80,.16);
  padding: 14px 14px 16px;
  box-shadow: 0 2px 12px rgba(40,20,8,.06), 0 1px 3px rgba(40,20,8,.04);
  flex-shrink: 0;
  gap: 0;
}

/* 连接器组 */
.lc-connector {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  flex-shrink: 0; width: 28px;
}
.lc-line {
  height: 3px; width: 100%; border-radius: 3px;
  background: rgba(160,120,80,.2);
  transition: background .4s;
}
.lc-line-done {
  background: linear-gradient(90deg, #43a047, #1b5e20);
  box-shadow: 0 1px 4px rgba(46,125,50,.3);
}
.lc-line-skip {
  background: repeating-linear-gradient(90deg, rgba(160,120,80,.3) 0, rgba(160,120,80,.3) 4px, transparent 4px, transparent 8px);
}
.lc-arrow { font-size: 13px; color: rgba(160,120,80,.4); line-height: 1; margin-top: -2px; transition: color .3s; }
.lc-arrow-done { color: #43a047; }

/* 节点卡片 */
.lc-node {
  flex: 1;
  display: flex; flex-direction: column; align-items: center;
  gap: 6px; padding: 12px 8px 14px;
  border: 2px solid transparent;
  border-radius: 16px;
  background: #faf7f3;
  cursor: pointer;
  transition: all .22s cubic-bezier(.4,0,.2,1);
  position: relative; min-width: 0;
}
.lc-node:hover {
  background: #fff;
  border-color: rgba(160,120,80,.3);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(40,20,8,.08);
}
.lc-node.lc-active {
  background: #fff;
  border-color: var(--ac);
  box-shadow: 0 6px 24px color-mix(in srgb, var(--ac) 22%, transparent),
              0 2px 6px rgba(40,20,8,.06);
  transform: translateY(-2px);
}
.lc-node.lc-ns-skipped { opacity: .6; }
.lc-node.lc-ns-skipped:hover { opacity: .85; }

/* 步骤序号 */
.lc-step {
  position: absolute; top: 7px; left: 9px;
  width: 16px; height: 16px; border-radius: 50%;
  background: rgba(160,120,80,.12); color: #a8917e;
  font-size: 9px; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
  transition: all .2s;
}
.lc-node.lc-active .lc-step {
  background: color-mix(in srgb, var(--ac) 15%, transparent);
  color: var(--ac);
}

/* 图标圆 */
.lc-dot {
  width: 44px; height: 44px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700;
  background: #ece7e1; color: #a8917e;
  transition: all .22s cubic-bezier(.4,0,.2,1);
  flex-shrink: 0;
}
.lc-dot-done {
  background: linear-gradient(135deg, #66bb6a, #1b5e20);
  color: #fff; font-size: 20px;
  box-shadow: 0 4px 14px rgba(46,125,50,.35);
}
.lc-dot-active {
  background: linear-gradient(135deg, #ffb74d, #e65100);
  color: #fff;
  box-shadow: 0 4px 14px rgba(230,81,0,.3);
}
.lc-dot-partial {
  background: linear-gradient(135deg, #ffd54f, #f57c00);
  color: #fff;
  box-shadow: 0 4px 14px rgba(245,124,0,.3);
}
.lc-dot-skipped { background: #ddd5cc; color: #aaa; }
.lc-node.lc-active .lc-dot {
  box-shadow: 0 6px 22px color-mix(in srgb, var(--ac) 45%, transparent);
  transform: scale(1.06);
}

/* 节点文字 */
.lc-label {
  font-size: 13px; font-weight: 800; color: #4a3322;
  letter-spacing: .1px;
}
.lc-node.lc-active .lc-label { color: var(--ac); }

.lc-badge {
  font-size: 9.5px; font-weight: 700;
  padding: 2px 8px; border-radius: 20px; white-space: nowrap;
}
.lc-bg-done    { color: #1b5e20; background: rgba(46,125,50,.12); border: 1px solid rgba(46,125,50,.18); }
.lc-bg-active  { color: #e65100; background: rgba(230,81,0,.1);   border: 1px solid rgba(230,81,0,.18);  }
.lc-bg-partial { color: #e65100; background: rgba(245,124,0,.1);  border: 1px solid rgba(245,124,0,.18); }
.lc-bg-pending { color: #9e8a78; background: rgba(158,138,120,.1); border: 1px solid rgba(158,138,120,.18); }
.lc-bg-skipped { color: #9e9e9e; background: rgba(158,158,158,.08); border: 1px solid rgba(158,158,158,.15); text-decoration: line-through; }
.lc-node.lc-active .lc-bg-pending {
  color: var(--ac); background: color-mix(in srgb, var(--ac) 10%, transparent);
  border-color: color-mix(in srgb, var(--ac) 25%, transparent);
}

.lc-sum { font-size: 9.5px; color: #b0987e; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }

/* 展开箭头 */
.lc-pip {
  font-size: 14px; color: rgba(160,120,80,.35); line-height: 1;
  transition: all .2s; margin-top: -2px;
}
.lc-pip.open { color: var(--ac); transform: rotate(180deg); }

/* ════════════════════════════════════════════════════
   NODE DETAIL PANEL
   ════════════════════════════════════════════════════ */
.nd-enter-active { transition: all .24s cubic-bezier(.34,1.06,.64,1); }
.nd-leave-active { transition: all .16s ease; }
.nd-enter-from { opacity: 0; transform: translateY(-8px) scale(.98); }
.nd-leave-to   { opacity: 0; transform: translateY(-4px) scale(.99); }

.lc-detail {
  background: #fff;
  border-radius: 16px;
  border: 2px solid color-mix(in srgb, var(--ac) 30%, rgba(160,120,80,.2));
  overflow: hidden;
  box-shadow: 0 6px 28px rgba(40,20,8,.09), 0 2px 6px rgba(40,20,8,.05);
  display: flex; flex-direction: column; gap: 0;
  /* 关键：在 .ap-body 这个纵向 flex 容器里，overflow:hidden 会让该元素的
     自动最小尺寸塌缩为 0，被 flex 压扁后内容被裁切（表现为"工作台内容被压缩
     看不见"）。flex-shrink:0 锁定其自然高度，让滚动交给 .ap-body 承担。 */
  flex-shrink: 0;
}

/* 节点详情头部 */
.nd-stage-header {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px 11px;
  background: linear-gradient(135deg,
    color-mix(in srgb, var(--ac) 8%, #fff) 0%,
    #fff 100%);
  border-bottom: 1px solid color-mix(in srgb, var(--ac) 14%, rgba(160,120,80,.12));
}
.nd-stage-icon {
  width: 30px; height: 30px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; color: #fff; flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(0,0,0,.18);
}
.nd-stage-name { font-size: 14px; font-weight: 900; color: #3d2a1a; letter-spacing: -.2px; }
.nd-stage-badge {
  font-size: 9.5px; font-weight: 700; padding: 2px 9px; border-radius: 20px;
}
.nd-stage-sum { font-size: 11px; color: #9b8070; margin-left: auto; font-weight: 600; }

/* 详情主体：每个直接子块自带 margin:x 16px 做横向内缩并保留各自的纵向
   padding；这里只兜底首块顶距与末块底距。不要再加 padding:0 16px 通配规则
   ——它会以更高特异性清掉子块的纵向 padding，把字段/按钮挤成一条线。 */
.lc-detail > *:not(.nd-stage-header):first-of-type { margin-top: 12px; }
.lc-detail > *:last-child { margin-bottom: 14px; }

/* 跳过开票卡片 */
.lc-detail > .nd-skip-card {
  display: flex; align-items: center; gap: 12px;
  background: linear-gradient(135deg, #f5f0eb, #faf8f5);
  border: 1.5px solid rgba(160,120,80,.2);
  border-radius: 12px;
  padding: 13px 14px;
  margin: 12px 16px 0;
}
.nd-skip-icon { font-size: 24px; flex-shrink: 0; }
.nd-skip-body { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.nd-skip-body b { font-size: 12.5px; color: #4a3322; font-weight: 700; }
.nd-skip-body span { font-size: 11px; color: #9b8070; }
.nd-skip-undo {
  border: 1.5px solid rgba(142,99,197,.45); background: #fff; color: #8e63c5;
  font-size: 11px; font-weight: 700; padding: 5px 12px; border-radius: 8px; cursor: pointer;
  flex-shrink: 0; transition: all .14s;
}
.nd-skip-undo:hover { background: rgba(142,99,197,.08); }
.nd-skip-toggle {
  border: 1.5px dashed rgba(158,158,158,.5); background: none; color: #aaa;
  font-size: 11px; padding: 7px 13px; border-radius: 8px; cursor: pointer;
  transition: all .14s; margin: 8px 16px;
  align-self: flex-start;
}
.nd-skip-toggle:hover { border-color: #8e63c5; color: #8e63c5; background: rgba(142,99,197,.05); }

/* 字段区
   注意：选择器写成 .lc-detail > .nd-fields 提升特异性，否则会被上方
   .lc-detail > *:not(.nd-stage-header){padding:0 16px} 覆盖，导致内边距
   被清零、字段挤成一团。 */
.lc-detail > .nd-fields {
  background: #faf7f3;
  border: 1.5px solid rgba(160,120,80,.14);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 9px;
  margin: 12px 16px 0;
}
.lc-detail > .nd-fields-2 {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 9px 18px;
  padding: 0;
  margin: 12px 16px 0;
}
.kf { display: flex; align-items: center; gap: 8px; min-width: 0; }
.kf-lab {
  font-size: 10.5px; color: #a8917e; flex-shrink: 0; white-space: nowrap;
  font-weight: 600; text-transform: none;
}
.kf-val {
  font-size: 12.5px; color: #4a3322; cursor: pointer;
  padding: 3px 9px; border-radius: 7px;
  border: 1.5px solid transparent;
  transition: all .14s; font-weight: 600;
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.kf-val:hover { background: #fff; border-color: color-mix(in srgb, var(--ac, #c96342) 30%, transparent); box-shadow: 0 1px 5px rgba(0,0,0,.06); }
.kf-val.empty { color: #c4b3a5; font-weight: 400; }
.kf-val.ro, .kf-val.ro:hover { cursor: default; background: none; border-color: transparent; box-shadow: none; }
.kf-inp {
  border: 1.5px solid color-mix(in srgb, var(--ac, #c96342) 50%, transparent);
  border-radius: 7px; padding: 4px 8px; font-size: 12.5px; color: #4a3322;
  background: #fff; outline: none; font-family: inherit; max-width: 140px;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ac, #c96342) 10%, transparent);
}
.kf-today {
  border: 1.5px solid rgba(160,120,80,.28); background: #fff; color: #9b8070;
  font-size: 10px; padding: 2px 8px; border-radius: 6px; cursor: pointer;
  flex-shrink: 0; transition: all .14s;
}
.kf-today:hover { border-color: var(--ac, #c96342); color: var(--ac, #c96342); }
.kf-batch-hint {
  font-size: 11px; color: #8e63c5; background: rgba(142,99,197,.08);
  padding: 6px 10px; border-radius: 8px; margin: 6px 16px 0;
  border: 1px solid rgba(142,99,197,.15);
}
.kf-batch-hint b { font-weight: 800; }

/* ════════════════════════════════════════════════════
   ACTIVITY TIMELINE
   ════════════════════════════════════════════════════ */
.nd-acts {
  display: flex; flex-direction: column; gap: 0;
  margin: 10px 16px 0;
  position: relative;
}
.nd-acts::before {
  content: ''; position: absolute;
  left: 13px; top: 14px; bottom: 14px; width: 2px;
  background: linear-gradient(180deg, rgba(160,120,80,.2) 0%, rgba(160,120,80,.05) 100%);
  border-radius: 2px;
}
.act-item {
  display: flex; gap: 10px;
  padding-bottom: 10px; position: relative;
}
.act-item:last-child { padding-bottom: 0; }

.act-dot {
  width: 28px; height: 28px; flex-shrink: 0; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 13px;
  background: #fff;
  border: 2px solid var(--sc, #888);
  box-shadow: 0 0 0 3px #fff, 0 2px 8px rgba(0,0,0,.1);
  z-index: 1; position: relative;
}
.act-main {
  flex: 1; min-width: 0;
  background: #faf7f3;
  border: 1px solid rgba(160,120,80,.14);
  border-left: 3px solid var(--sc, #888);
  border-radius: 10px;
  padding: 8px 11px;
  box-shadow: 0 1px 4px rgba(40,20,8,.05);
  transition: box-shadow .14s;
}
.act-main:hover { box-shadow: 0 3px 10px rgba(40,20,8,.08); }
.act-top { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.act-who { font-size: 11.5px; font-weight: 800; color: #4a3322; }
.act-st {
  border: none; font-size: 9.5px; font-weight: 700; cursor: pointer;
  padding: 2px 8px; border-radius: 20px;
  color: var(--sc); background: color-mix(in srgb, var(--sc) 12%, transparent);
  transition: opacity .12s;
}
.act-st:hover { opacity: .8; }
.act-time { font-size: 10px; color: #c4b3a5; margin-left: auto; font-variant-numeric: tabular-nums; }
.act-ico  { border: none; background: none; font-size: 11px; cursor: pointer; padding: 2px 3px; border-radius: 4px; opacity: .6; transition: opacity .12s; }
.act-ico:hover { opacity: 1; background: rgba(0,0,0,.05); }
.act-note { font-size: 12.5px; color: #4a3322; white-space: pre-wrap; word-break: break-word; line-height: 1.55; margin-top: 4px; }
.act-fu   { font-size: 10.5px; color: #a8917e; margin-top: 3px; font-weight: 600; }
.act-edit-ta { width: 100%; border: 1.5px solid rgba(201,99,66,.4); border-radius: 7px; padding: 5px 8px; font-size: 12.5px; color: #4a3322; resize: vertical; font-family: inherit; box-sizing: border-box; outline: none; margin-top: 5px; }
.act-edit-foot { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
.act-sel  { border: 1.5px solid rgba(160,120,80,.28); border-radius: 7px; font-size: 11.5px; padding: 3px 7px; color: #4a3322; background: #fff; outline: none; font-family: inherit; }
.act-save { padding: 3px 13px; border: none; border-radius: 7px; background: var(--ac, #c96342); color: #fff; font-size: 11.5px; font-weight: 700; cursor: pointer; margin-left: auto; }
.act-cancel { padding: 3px 10px; border: 1.5px solid rgba(160,120,80,.28); border-radius: 7px; background: #fff; font-size: 11.5px; cursor: pointer; color: #9b8070; }

/* 附件区 */
.nd-atts { display: flex; flex-direction: column; gap: 5px; margin: 8px 16px 0; }
.att-file {
  display: flex; align-items: center; gap: 8px;
  background: #faf7f3; border: 1px solid rgba(160,120,80,.15);
  border-radius: 9px; padding: 6px 10px;
}
.att-fname { flex: 1; min-width: 0; font-size: 11.5px; color: #1565c0; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.att-fname:hover { text-decoration: underline; }
.att-meta { font-size: 10px; color: #a8917e; flex-shrink: 0; }
.att-del  { border: none; background: none; color: #c4b3a5; font-size: 11px; cursor: pointer; flex-shrink: 0; transition: color .12s; }
.att-del:hover { color: #c62828; }
.att-dz {
  border: 2px dashed rgba(160,120,80,.28); border-radius: 10px;
  padding: 9px; text-align: center; font-size: 11px; color: #b0987e;
  cursor: pointer; position: relative; transition: all .16s;
}
.att-dz:hover, .att-dz.over {
  background: color-mix(in srgb, var(--ac, #c96342) 5%, transparent);
  border-color: var(--ac, #c96342); color: var(--ac, #c96342);
}
.att-dz-inp { position: absolute; inset: 0; opacity: 0; cursor: pointer; }

/* "记录跟进" 快捷按钮 */
.nd-compose-btn {
  border: 1.5px dashed rgba(160,120,80,.32); background: none;
  color: #b0987e; font-size: 11.5px; padding: 8px;
  border-radius: 10px; cursor: pointer; transition: all .15s; font-weight: 600;
  margin: 8px 16px 14px; text-align: center;
}
.nd-compose-btn:hover {
  background: color-mix(in srgb, var(--ac, #c96342) 5%, transparent);
  border-color: var(--ac, #c96342); color: var(--ac, #c96342);
}

/* ── 回款 ── */
.pay-prog { display: flex; flex-direction: column; gap: 5px; margin: 12px 16px 0; }
.pay-prog-bar { height: 10px; border-radius: 7px; background: rgba(160,120,80,.15); overflow: hidden; }
.pay-prog-fill {
  height: 100%; border-radius: 7px;
  background: linear-gradient(90deg, #81c784, #2e9e5b);
  transition: width .5s cubic-bezier(.4,0,.2,1);
}
.pay-prog-txt { display: flex; justify-content: space-between; font-size: 11px; color: #9b8070; font-weight: 700; }
.pay-list  { display: flex; flex-direction: column; gap: 5px; margin: 10px 16px 0; }
.pay-item  {
  display: flex; align-items: center; gap: 8px;
  background: #fff; border: 1px solid rgba(160,120,80,.15);
  border-left: 3px solid #2e9e5b; border-radius: 10px; padding: 7px 11px;
  box-shadow: 0 1px 4px rgba(40,20,8,.04);
}
.pay-no   { font-size: 10px; color: #a8917e; font-weight: 800; flex-shrink: 0; }
.pay-amt  { font-size: 13.5px; font-weight: 900; color: #1b5e20; letter-spacing: -.3px; }
.pay-date { font-size: 11px; color: #9b8070; }
.pay-src  { font-size: 9.5px; font-weight: 700; padding: 2px 8px; border-radius: 20px; color: #2e9e5b; background: rgba(46,158,91,.1); border: 1px solid rgba(46,158,91,.2); margin-left: auto; }
.pay-src-other { color: #e65100; background: rgba(230,81,0,.09); border-color: rgba(230,81,0,.18); }
.pay-cp  { font-size: 10px; color: #9b8070; }
.pay-del { border: none; background: none; font-size: 12px; cursor: pointer; opacity: .55; flex-shrink: 0; transition: opacity .12s; }
.pay-del:hover { opacity: 1; }
.pay-empty { font-size: 11.5px; color: #c4b3a5; text-align: center; padding: 8px 0; margin: 4px 16px 0; }
.pay-form  { display: flex; flex-direction: column; gap: 7px; margin: 10px 16px 0; }
.pay-srcs  { display: flex; gap: 6px; }
.pay-src-tab {
  flex: 1; border: 1.5px solid rgba(160,120,80,.25); background: #fff;
  color: #9b8070; font-size: 11.5px; padding: 6px; border-radius: 9px; cursor: pointer; transition: all .14s; font-weight: 600;
}
.pay-src-tab:hover { border-color: rgba(46,158,91,.5); color: #2e9e5b; }
.pay-src-tab.on { border-color: #2e9e5b; background: rgba(46,158,91,.08); color: #1b5e20; }
.pay-add { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
.pay-inp  { border: 1.5px solid rgba(160,120,80,.28); border-radius: 8px; padding: 6px 9px; font-size: 12px; color: #4a3322; background: #fff; outline: none; font-family: inherit; min-width: 0; transition: border-color .14s; }
.pay-inp:focus { border-color: rgba(46,158,91,.55); box-shadow: 0 0 0 3px rgba(46,158,91,.08); }
.pay-inp-amt  { flex: 1; min-width: 90px; }
.pay-inp-dept { flex: 1; min-width: 110px; }
.pay-btn {
  padding: 7px 16px; border: none; border-radius: 9px;
  background: linear-gradient(135deg, #43a047, #1b5e20); color: #fff;
  font-size: 12px; font-weight: 700; cursor: pointer; flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(46,125,50,.3); transition: filter .14s;
}
.pay-btn:hover:not(:disabled) { filter: brightness(1.07); }
.pay-btn:disabled { opacity: .5; cursor: default; }
.pay-settle {
  border: 2px dashed rgba(46,158,91,.45);
  background: rgba(46,158,91,.04); color: #1b5e20;
  font-size: 11.5px; font-weight: 700; padding: 8px;
  border-radius: 10px; cursor: pointer; transition: all .15s;
  margin: 8px 16px 0; display: block; width: calc(100% - 32px);
}
.pay-settle:hover:not(:disabled) { background: rgba(46,158,91,.1); box-shadow: 0 2px 10px rgba(46,125,50,.15); }
.pay-settle:disabled { opacity: .5; cursor: default; }

/* ════════════════════════════════════════════════════
   催收跟进 SECTION
   ════════════════════════════════════════════════════ */
.dun-section {
  border: 1.5px solid rgba(160,120,80,.18);
  border-radius: 16px; background: #fff; overflow: hidden;
  box-shadow: 0 2px 10px rgba(40,20,8,.05);
}
.dun-head {
  width: 100%; display: flex; align-items: center; gap: 9px;
  padding: 11px 14px; border: none; background: none; cursor: pointer;
  font-family: inherit; transition: background .14s;
}
.dun-head:hover { background: rgba(201,99,66,.03); }
.dun-icon  { font-size: 16px; }
.dun-icon.dun-urgent { animation: dun-pulse 1.8s ease-out infinite; }
@keyframes dun-pulse {
  0% { filter: drop-shadow(0 0 0 rgba(239,83,80,.7)); }
  60% { filter: drop-shadow(0 0 5px rgba(239,83,80,.25)); }
  100% { filter: drop-shadow(0 0 0 rgba(239,83,80,0)); }
}
.dun-title { font-size: 13px; font-weight: 800; color: #3d2a1a; }
.dun-od {
  font-size: 10px; font-weight: 700; padding: 2px 9px; border-radius: 20px;
  color: #b71c1c; background: rgba(183,28,28,.1); border: 1px solid rgba(183,28,28,.2);
}
.dun-cnt   { font-size: 10.5px; color: #a8917e; font-weight: 600; }
.dun-caret { margin-left: auto; font-size: 13px; color: #c0ad9d; transform: rotate(180deg); transition: transform .22s; flex-shrink: 0; }
.dun-caret.open { transform: rotate(0deg); }
.dun-body  { padding: 0 14px 14px; display: flex; flex-direction: column; gap: 10px; }
.dun-kf-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 18px; background: #faf7f3; border-radius: 10px; padding: 10px 12px; border: 1.5px solid rgba(160,120,80,.14); }
.dun-meta  { display: flex; align-items: center; gap: 8px; }
.dun-last  { font-size: 11px; color: #9b8070; font-weight: 600; }
.dun-last.cold { color: #c96342; }
.dun-letter-btn {
  margin-left: auto; border: 1.5px solid rgba(201,99,66,.35); background: #fff;
  color: #c96342; font-size: 11px; font-weight: 700; padding: 5px 12px;
  border-radius: 8px; cursor: pointer; transition: all .14s; flex-shrink: 0;
}
.dun-letter-btn:hover { background: rgba(201,99,66,.06); box-shadow: 0 2px 8px rgba(201,99,66,.15); }
.dun-empty { font-size: 11.5px; color: #c4b3a5; text-align: center; padding: 4px 0; }

/* ── 操作轨迹 ── */
.ap-audit {
  border: 1.5px solid rgba(160,120,80,.18);
  border-radius: 16px; background: #fff; overflow: hidden;
  box-shadow: 0 2px 10px rgba(40,20,8,.04);
}
.ap-audit-head { width: 100%; display: flex; align-items: center; gap: 9px; padding: 11px 14px; border: none; background: none; cursor: pointer; font-family: inherit; }
.ap-audit-head:hover { background: rgba(201,99,66,.03); }
.ap-audit-ico   { font-size: 14px; }
.ap-audit-title { font-size: 13px; font-weight: 800; color: #3d2a1a; }
.ap-audit-hint  { font-size: 10.5px; color: #b0987e; }
.ap-audit-caret { margin-left: auto; font-size: 13px; color: #c0ad9d; transition: transform .22s; transform: rotate(180deg); flex-shrink: 0; }
.ap-audit-caret.open { transform: rotate(0deg); }
.ap-audit-body  { padding: 2px 14px 14px; }
.ap-audit-empty { font-size: 12px; color: #c4b3a5; text-align: center; padding: 12px 0; }
.ap-audit-list  { position: relative; }
.ap-audit-item  { display: flex; gap: 10px; position: relative; padding-bottom: 11px; }
.ap-audit-item:not(.last)::before { content: ''; position: absolute; left: 11px; top: 23px; bottom: 0; width: 2px; background: rgba(160,120,80,.15); }
.ap-audit-dot   { width: 24px; height: 24px; flex-shrink: 0; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; background: #faf7f3; border: 1.5px solid rgba(160,120,80,.22); z-index: 1; }
.ap-audit-main  { flex: 1; min-width: 0; padding-top: 1px; }
.ap-audit-act   { font-size: 12.5px; color: #3d2a1a; font-weight: 700; }
.ap-audit-detail { color: #9b8070; font-weight: 400; }
.ap-audit-meta  { font-size: 10.5px; color: #a8917e; margin-top: 1px; }

/* ── 催款函弹层 ── */
.lt-overlay { position: fixed; inset: 0; z-index: 720; background: rgba(28,16,6,.45); display: flex; align-items: center; justify-content: center; padding: 20px; backdrop-filter: blur(4px); }
.lt-modal { width: 500px; max-width: 94vw; background: #fff; border-radius: 18px; box-shadow: 0 24px 70px rgba(28,16,6,.32); display: flex; flex-direction: column; overflow: hidden; }
.lt-head  { display: flex; align-items: center; justify-content: space-between; padding: 13px 18px; border-bottom: 1px solid rgba(160,120,80,.16); background: linear-gradient(135deg, #fdf0e0, #fff); }
.lt-title { font-size: 14px; font-weight: 800; color: #3d2a1a; }
.lt-close { border: none; background: rgba(0,0,0,.04); width: 28px; height: 28px; border-radius: 8px; font-size: 13px; color: #9b8070; cursor: pointer; transition: all .14s; }
.lt-close:hover { background: rgba(201,99,66,.1); color: #c96342; }
.lt-ta    { border: none; outline: none; resize: vertical; padding: 15px 20px; font-size: 13.5px; line-height: 1.8; color: #3a2e22; font-family: inherit; min-height: 280px; letter-spacing: .01em; }
.lt-foot  { display: flex; align-items: center; gap: 10px; padding: 12px 18px; border-top: 1px solid rgba(160,120,80,.16); background: #faf7f3; }
.lt-hint  { font-size: 11px; color: #a8917e; }
.lt-copy  {
  margin-left: auto; padding: 8px 24px; border: none; border-radius: 10px;
  background: linear-gradient(135deg, #c96342, #a8431f); color: #fff;
  font-size: 13px; font-weight: 700; cursor: pointer;
  box-shadow: 0 4px 14px rgba(201,99,66,.3); transition: filter .14s;
}
.lt-copy:hover { filter: brightness(1.08); }

/* ════════════════════════════════════════════════════
   COMPOSE BAR
   ════════════════════════════════════════════════════ */
.ap-compose {
  padding: 10px 16px 13px;
  border-top: 1px solid rgba(160,120,80,.16);
  background: rgba(255,253,250,.96);
  flex-shrink: 0;
  display: flex; flex-direction: column; gap: 7px;
  box-shadow: 0 -4px 16px rgba(40,20,8,.06);
}
.ap-cmp-row1 { display: flex; gap: 5px; align-items: center; }
.ap-cmp-type {
  border: 1.5px solid rgba(160,120,80,.22);
  background: rgba(255,255,255,.8); border-radius: 9px;
  padding: 4px 9px; font-size: 14px; cursor: pointer; line-height: 1;
  transition: all .14s;
}
.ap-cmp-type:hover { border-color: rgba(201,99,66,.5); background: #fff; }
.ap-cmp-type.on { border-color: #c96342; background: rgba(201,99,66,.1); transform: translateY(-1px); box-shadow: 0 2px 8px rgba(201,99,66,.15); }
.ap-cmp-target { margin-left: auto; font-size: 11px; color: #b0987e; }
.ap-cmp-target b { font-weight: 800; font-size: 11.5px; }
.ap-cmp-phrases { display: flex; gap: 5px; overflow-x: auto; padding-bottom: 1px; scrollbar-width: none; }
.ap-cmp-phrases::-webkit-scrollbar { display: none; }
.ap-cmp-phrase {
  flex-shrink: 0; border: 1.5px solid rgba(160,120,80,.25); background: #fff;
  color: #9b8070; font-size: 10.5px; padding: 3px 10px; border-radius: 20px;
  cursor: pointer; white-space: nowrap; transition: all .14s; font-weight: 600;
}
.ap-cmp-phrase:hover { border-color: #c96342; color: #c96342; background: rgba(201,99,66,.05); }
.ap-cmp-ta {
  width: 100%; border: 1.5px solid rgba(160,120,80,.22); border-radius: 10px;
  padding: 9px 11px; font-size: 13px; color: #4a3322; resize: vertical;
  min-height: 42px; font-family: inherit; background: #fff; outline: none;
  box-sizing: border-box; transition: border-color .14s, box-shadow .14s;
}
.ap-cmp-ta:focus { border-color: rgba(201,99,66,.55); box-shadow: 0 0 0 3px rgba(201,99,66,.08); }
.ap-cmp-row2 { display: flex; gap: 6px; align-items: center; }
.ap-cmp-sel { border: 1.5px solid rgba(160,120,80,.25); border-radius: 8px; font-size: 12px; padding: 5px 8px; color: #4a3322; background: #fff; outline: none; font-family: inherit; }
.ap-cmp-btn {
  margin-left: auto; padding: 7px 22px; border: none; border-radius: 10px;
  background: linear-gradient(135deg, #c96342, #a8431f); color: #fff;
  font-size: 13px; font-weight: 700; cursor: pointer; transition: all .14s;
  box-shadow: 0 3px 12px rgba(201,99,66,.28);
}
.ap-cmp-btn:hover:not(:disabled) { filter: brightness(1.07); box-shadow: 0 5px 18px rgba(201,99,66,.35); }
.ap-cmp-btn:disabled { opacity: .45; cursor: default; box-shadow: none; }
</style>
