<script setup>
/*
 * 应收账款「生命线工作台」—— 一条应收记录的完整生命故事。
 * 合同 → 对账 → 开票 → 回款 → 催款，每个关键节点的录入/跟踪/附件都在此完成，不再跳转。
 *  · 顶部生命线导航：点击节点平滑滚动到对应阶段；滚动时自动高亮当前阶段（scroll-spy）
 *  · 各阶段为可折叠里程碑：已完成自动折叠，需处理的自动展开
 *  · 底部录入条「上下文感知」：跟随当前阶段，记录的跟进自动归入该阶段
 */
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import ar from '../../api/ar.js'
import { useToast } from '../../composables/useToast.js'
import { todayCST, DEPARTMENTS } from '../../constants.js'
import { copyText } from '../../utils/clipboard.js'
import LifelineSection from './LifelineSection.vue'

const props = defineProps({
  rec: { type: Object, required: true },
  canWrite: { type: Boolean, default: false },     // auth.canArWrite —— 改记录字段
  canCollect: { type: Boolean, default: false },   // auth.canAction('ar_collect') —— 登记回款
})
const emit = defineEmits(['close', 'field-saved'])

const toast = useToast()
const errMsg = e => e?.msg || e?.error || '操作失败'

// ── 数据：一次拉全量，按阶段在前端切分 ──────────────────────────────────────
const loading = ref(false)
const allActivities = ref([])
const attachments = ref([])
const payments = ref([])

async function load() {
  loading.value = true
  try {
    const [actRes, payRes] = await Promise.all([
      ar.listActivity(props.rec.id, {}),
      // 回款明细对所有可见者展示；无 r_payments 权限时后端 403，降级为空列表
      ar.listPayments(props.rec.id).catch(() => ({ data: [] })),
    ])
    allActivities.value = actRes.data.activities || []
    attachments.value = actRes.data.attachments || []
    payments.value = Array.isArray(payRes.data) ? payRes.data : []
  } catch (e) {
    toast.error(errMsg(e))
  } finally {
    loading.value = false
  }
}
watch(() => props.rec?.id, (id) => { if (id) load() }, { immediate: true })

// 旧数据的 general/未知阶段并入「催款」兜底展示，避免遗漏
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
const estimated = computed(() => Number(props.rec.estimated_amount || 0))
const outstanding = computed(() => Number(props.rec.outstanding_amount || 0))
const paid = computed(() => Math.max(0, estimated.value - outstanding.value))
const paidPct = computed(() => estimated.value > 0 ? Math.min(1, paid.value / estimated.value) : 0)
const overdueDays = computed(() => Number(props.rec.overdue_days || 0))

// ── 各阶段状态推断（导航 + 区块共用）────────────────────────────────────────
const stageInfo = computed(() => {
  const r = props.rec
  const reconDone = !!r.reconciliation_date
  const invDone = !!(r.invoice_date || Number(r.actual_invoice_amount) > 0)
  const collDone = estimated.value > 0 && outstanding.value === 0
  const a = actsByStage.value
  return {
    contract: { state: 'done', label: '已签订' },
    reconciliation: {
      state: reconDone ? 'done' : (a.reconciliation.length ? 'active' : 'pending'),
      label: reconDone ? '已对账' : '待对账',
      summary: reconDone ? `对账日 ${r.reconciliation_date}` : '尚未对账',
    },
    invoice: {
      state: invDone ? 'done' : (a.invoice.length ? 'active' : 'pending'),
      label: invDone ? '已开票' : '待开票',
      summary: invDone ? `¥${fmtAmt(r.actual_invoice_amount)}${r.invoice_date ? ' · ' + r.invoice_date : ''}` : '尚未开票',
    },
    collection: {
      state: collDone ? 'done' : (paid.value > 0 ? 'partial' : (a.collection.length ? 'active' : 'pending')),
      label: collDone ? '已收齐' : (paid.value > 0 ? `已收 ${Math.round(paidPct.value * 100)}%` : '待回款'),
      summary: `¥${fmtAmt(paid.value)} / ¥${fmtAmt(estimated.value)}`,
    },
    dunning: {
      state: overdueDays.value > 0 ? 'urgent' : (a.dunning.length ? 'active' : 'pending'),
      label: overdueDays.value > 0 ? `逾期 ${overdueDays.value} 天` : '跟进中',
      summary: a.dunning.length ? `${a.dunning.length} 条跟进` : '暂无跟进',
    },
  }
})

// ── 跟进提醒：到期的计划跟进 + 距上次催款天数 ────────────────────────────────
const pendingFollowUp = computed(() => {
  const today = todayCST()
  return allActivities.value
    .filter(a => a.follow_up_date && a.status !== 'resolved' && a.follow_up_date <= today)
    .sort((x, y) => (x.follow_up_date < y.follow_up_date ? -1 : 1))[0] || null
})
const daysSinceLastDun = computed(() => {
  const last = actsByStage.value.dunning[0]   // 倒序，[0] 为最新
  if (!last?.created_at) return null
  const d = new Date(last.created_at.replace(' ', 'T'))
  if (isNaN(d)) return null
  return Math.floor((Date.now() - d.getTime()) / 86400000)
})

// ── 智能下一步：把面板从"看板"变成"行动建议" ──────────────────────────────────
const settled = computed(() => estimated.value > 0 && outstanding.value === 0)
const nextAction = computed(() => {
  const r = props.rec
  const invDone = !!(r.invoice_date || Number(r.actual_invoice_amount) > 0)
  if (settled.value) return { icon: '✅', text: '已全部收齐，应收已结清', tone: 'done', stage: 'collection' }
  if (overdueDays.value > 0) return { icon: '⚠️', text: `已逾期 ${overdueDays.value} 天，建议立即催款`, tone: 'danger', stage: 'dunning', cta: '去催款' }
  if (pendingFollowUp.value) return { icon: '📅', text: `有计划跟进已到期（${pendingFollowUp.value.follow_up_date}）`, tone: 'warn', stage: 'dunning', cta: '去跟进' }
  if (!r.reconciliation_date && !invDone) return { icon: '✓', text: '尚未对账，建议先完成对账', tone: 'info', stage: 'reconciliation', cta: '去对账' }
  if (r.reconciliation_date && !invDone) return { icon: '🧾', text: '对账已完成，可以开票了', tone: 'info', stage: 'invoice', cta: '去开票' }
  if (invDone && outstanding.value > 0) return { icon: '💰', text: `已开票，待回款 ¥${fmtAmt(outstanding.value)}`, tone: 'info', stage: 'collection', cta: '记回款' }
  return null
})

const NAV = [
  { stage: 'contract', label: '合同', icon: '📄' },
  { stage: 'reconciliation', label: '对账', icon: '✓' },
  { stage: 'invoice', label: '开票', icon: '🧾' },
  { stage: 'collection', label: '回款', icon: '💰' },
  { stage: 'dunning', label: '催款', icon: '🔔' },
]
const ACCENT = { reconciliation: '#1976d2', invoice: '#8e63c5', collection: '#2e9e5b', dunning: '#c96342' }
const REAL_STAGES = ['reconciliation', 'invoice', 'collection', 'dunning']

// ── 滑入 / 滑出动画 ─────────────────────────────────────────────────────────
const visible = ref(false)
function close() { visible.value = false; setTimeout(() => emit('close'), 220) }

// ── 记录字段行内编辑（对账日期 / 开票字段 / 催收人 / 目标回款 / 备注）─────────
const editingField = ref('')
const fieldBuf = ref('')
const fieldInp = ref(null)
function beginField(field, cur) {
  if (!props.canWrite) return
  editingField.value = field
  fieldBuf.value = cur ?? ''
  nextTick(() => fieldInp.value?.focus())
}
async function saveField() {
  const field = editingField.value
  if (!field) { return }
  editingField.value = ''
  const val = fieldBuf.value === '' ? null : fieldBuf.value
  if ((props.rec[field] ?? null) === val) return   // 与现值相同则跳过
  await saveFieldValue(field, val)
}
async function saveFieldValue(field, val) {
  try {
    const res = await ar.updateRecord(props.rec.id, { [field]: val })
    Object.assign(props.rec, res.data)          // 同步本面板（含重算后的未收/税额等派生值）
    emit('field-saved', { id: props.rec.id, ...res.data })
    toast.success('已保存')
  } catch (e) {
    toast.error(errMsg(e))
  }
}
// 日期字段「今天」快捷填入
function setToday(field) { if (props.canWrite) saveFieldValue(field, todayCST()) }

// ── 回款登记 ─────────────────────────────────────────────────────────────────
// source：'回款'（现金）｜ '内部往来'（事业部间核销，需选往来部门，不计现金）
const DEPT_OPTS = computed(() => DEPARTMENTS.filter(d => d !== props.rec.delivery_dept))
const payForm = reactive({ amount: '', payment_date: '', source: '回款', counterparty_dept: '', notes: '' })
const addingPay = ref(false)
async function submitPayment() {
  if (!(Number(payForm.amount) > 0)) { toast.error('请填写金额'); return }
  if (!payForm.payment_date) { toast.error('请选择日期'); return }
  if (payForm.source === '内部往来' && !payForm.counterparty_dept) { toast.error('请选择往来事业部'); return }
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
  } catch (e) {
    toast.error(errMsg(e))
  } finally {
    addingPay.value = false
  }
}
async function settleRemaining() {
  if (!(outstanding.value > 0)) return
  if (!confirm(`登记一笔 ¥${fmtAmt(outstanding.value)} 的回款，结清全部余款？`)) return
  addingPay.value = true
  try {
    await ar.addPayment(props.rec.id, { amount: outstanding.value, payment_date: todayCST(), source: '回款', notes: '结清余款' })
    await refreshRecordAndPayments()
    toast.success('已结清余款')
  } catch (e) {
    toast.error(errMsg(e))
  } finally {
    addingPay.value = false
  }
}
async function deletePayment(p) {
  if (!confirm(`删除第 ${p.payment_no} 笔回款（¥${p.amount}）？`)) return
  try {
    await ar.deletePayment(props.rec.id, p.id)
    await refreshRecordAndPayments()
    toast.success('已删除')
  } catch (e) {
    toast.error(errMsg(e))
  }
}
async function refreshRecordAndPayments() {
  // 回款增删由后端信号重算 outstanding，回拉记录 + 回款以刷新欠款/进度
  const [recRes, payRes] = await Promise.all([
    ar.getRecord(props.rec.id),
    ar.listPayments(props.rec.id),
  ])
  Object.assign(props.rec, recRes.data)
  emit('field-saved', { id: props.rec.id, ...recRes.data })
  payments.value = Array.isArray(payRes.data) ? payRes.data : []
}

// ── 阶段内动态：编辑 / 删除 / 状态切换（由各区块上抛）─────────────────────────
async function saveActEdit({ act, note, status, follow_up_date }) {
  try {
    const res = await ar.updateActivity(props.rec.id, act.id, { note, status, follow_up_date: follow_up_date || null })
    const i = allActivities.value.findIndex(a => a.id === act.id)
    if (i !== -1) allActivities.value[i] = res.data
    toast.success('已更新')
  } catch (e) { toast.error(errMsg(e)) }
}
async function deleteAct(act) {
  if (!confirm(`删除这条${act.act_type_display}记录？`)) return
  try {
    await ar.deleteActivity(props.rec.id, act.id)
    allActivities.value = allActivities.value.filter(a => a.id !== act.id)
    emit('field-saved', { id: props.rec.id, activity_count: Math.max(0, (props.rec.activity_count || 1) - 1) })
    toast.success('已删除')
  } catch (e) { toast.error(errMsg(e)) }
}
async function toggleStatus(act) {
  const order = ['in_progress', 'pending', 'resolved', 'no_response']
  const next = order[(order.indexOf(act.status) + 1) % order.length]
  try {
    const res = await ar.updateActivity(props.rec.id, act.id, { note: act.note, status: next })
    const i = allActivities.value.findIndex(a => a.id === act.id)
    if (i !== -1) allActivities.value[i] = res.data
  } catch (e) { toast.error(errMsg(e)) }
}

// ── 附件上传 / 删除 ──────────────────────────────────────────────────────────
async function uploadTo(file, stage) {
  if (!file) return
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  const ALLOWED = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.xlsx', '.xls', '.docx', '.doc', '.txt', '.csv']
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

// ── 底部录入条（上下文感知）──────────────────────────────────────────────────
const ACT_TYPES = [
  { v: 'call', l: '📞', t: '电话' }, { v: 'email', l: '📧', t: '邮件' },
  { v: 'visit', l: '🚶', t: '拜访' }, { v: 'meeting', l: '💬', t: '会议' }, { v: 'note', l: '📝', t: '备注' },
]
const STATUSES = [
  { v: 'in_progress', l: '跟进中' }, { v: 'pending', l: '待回复' },
  { v: 'resolved', l: '已解决' }, { v: 'no_response', l: '无响应' },
]
const composeStage = ref('dunning')          // 录入归属阶段（跟随滚动 / 点击）
const compose = reactive({ act_type: 'call', note: '', status: 'in_progress', follow_up_date: '' })
const adding = ref(false)
const composeTa = ref(null)
const STAGE_LABEL = { reconciliation: '对账', invoice: '开票', collection: '回款', dunning: '催款' }

// 快捷跟进短语：一键插入常用催收用语，减少重复打字
const QUICK_PHRASES = ['已电话联系，承诺近期付款', '对方财务已确认，走流程中', '已发送对账单/催款函', '客户资金紧张，申请延期', '多次联系暂无回复']
function insertPhrase(p) {
  compose.note = compose.note.trim() ? compose.note.trim() + '；' + p : p
  nextTick(() => composeTa.value?.focus())
}

// 复制催收摘要：把整单生命周期要点复制为文本，便于微信/邮件交接
async function copySummary() {
  const r = props.rec
  const invDone = !!(r.invoice_date || Number(r.actual_invoice_amount) > 0)
  const lastDun = actsByStage.value.dunning[0]
  const lines = [
    `【${r.short_name || r.customer_name}】应收摘要`,
    `客户：${r.customer_name || '—'}　交付部门：${r.delivery_dept || '—'}`,
    `应收 ¥${fmtAmt(estimated.value)}　已收 ¥${fmtAmt(paid.value)}　欠款 ¥${fmtAmt(outstanding.value)}`,
    overdueDays.value > 0 ? `⚠️ 已逾期 ${overdueDays.value} 天` : `应收到期：${r.due_date || '—'}`,
    `对账：${r.reconciliation_date || '未对账'}　开票：${invDone ? ('¥' + fmtAmt(r.actual_invoice_amount) + (r.invoice_date ? ' / ' + r.invoice_date : '')) : '未开票'}`,
    r.collector ? `催收负责人：${r.collector}` : '',
    r.target_collection_date ? `目标回款日：${r.target_collection_date}` : '',
    lastDun ? `最近跟进（${(lastDun.created_at || '').slice(0, 10)}）：${lastDun.note}` : '',
  ].filter(Boolean)
  const okCopy = await copyText(lines.join('\n'))
  okCopy ? toast.success('已复制催收摘要') : toast.error('复制失败')
}

async function submitCompose() {
  if (!compose.note.trim()) { toast.error('请填写跟进内容'); return }
  adding.value = true
  try {
    const res = await ar.addActivity(props.rec.id, {
      stage: composeStage.value, act_type: compose.act_type,
      note: compose.note, status: compose.status, follow_up_date: compose.follow_up_date || null,
    })
    allActivities.value.unshift(res.data)
    emit('field-saved', { id: props.rec.id, activity_count: (props.rec.activity_count || 0) + 1 })
    compose.note = ''; compose.follow_up_date = ''
    toast.success(`已记录到「${STAGE_LABEL[composeStage.value]}」`)
  } catch (e) { toast.error(errMsg(e)) }
  finally { adding.value = false }
}
function focusCompose(stage) {
  composeManual.value = true
  composeStage.value = stage
  nextTick(() => composeTa.value?.focus())
  setTimeout(() => { composeManual.value = false }, 1200)
}

// ── 滚动定位 + scroll-spy ────────────────────────────────────────────────────
const bodyEl = ref(null)
const sectionEls = {}
const expandFns = {}
const activeNav = ref('contract')
const composeManual = ref(false)
let io = null

function registerSection(stage, el, expandFn) {
  if (el) {
    el.setAttribute('data-stage', stage)
    sectionEls[stage] = el
    if (expandFn) expandFns[stage] = expandFn
    if (io) io.observe(el)
  } else if (sectionEls[stage]) {
    if (io) io.unobserve(sectionEls[stage])
    delete sectionEls[stage]
    delete expandFns[stage]
  }
}
function scrollToStage(stage) {
  expandFns[stage]?.()                       // 收起的（如已完成）阶段，点导航即展开
  activeNav.value = stage
  if (REAL_STAGES.includes(stage)) focusComposeSilently(stage)
  nextTick(() => sectionEls[stage]?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}
function focusComposeSilently(stage) {
  composeManual.value = true
  composeStage.value = stage
  setTimeout(() => { composeManual.value = false }, 900)
}

onMounted(() => {
  requestAnimationFrame(() => { visible.value = true })
  document.addEventListener('paste', onPaste)
  document.addEventListener('keydown', onKey)
  io = new IntersectionObserver((entries) => {
    // 取与检测带相交、且最靠上的区块作为当前阶段
    const hit = entries.filter(e => e.isIntersecting)
      .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
    if (hit) {
      const stage = hit.target.getAttribute('data-stage')
      if (stage) {
        activeNav.value = stage
        if (!composeManual.value && REAL_STAGES.includes(stage)) composeStage.value = stage
      }
    }
  }, { root: bodyEl.value, rootMargin: '-12% 0px -78% 0px', threshold: 0 })
  Object.values(sectionEls).forEach(el => el && io.observe(el))
})
onBeforeUnmount(() => {
  document.removeEventListener('paste', onPaste)
  document.removeEventListener('keydown', onKey)
  if (io) io.disconnect()
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
  if (editingField.value) { editingField.value = ''; return }
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
            <button class="ap-icobtn" title="复制催收摘要" @click="copySummary">📋</button>
            <button class="ap-close" title="关闭 (Esc)" @click="close">✕</button>
          </div>
        </div>
        <!-- 金额进度 -->
        <div class="ap-money">
          <div class="ap-money-row">
            <span class="ap-m-est">应收 ¥{{ fmtAmt(estimated) }}</span>
            <span class="ap-m-pct">{{ Math.round(paidPct * 100) }}%</span>
          </div>
          <div class="ap-bar"><div class="ap-bar-fill" :style="{ width: (paidPct * 100) + '%' }"></div></div>
          <div class="ap-money-foot">
            <span class="ap-m-paid">已收 ¥{{ fmtAmt(paid) }}</span>
            <span class="ap-m-out" :class="{ 'ap-m-danger': overdueDays > 0 }">
              欠款 ¥{{ fmtAmt(outstanding) }}
              <em v-if="overdueDays > 0" class="ap-m-od">逾期{{ overdueDays }}天</em>
            </span>
          </div>
        </div>
      </div>

      <!-- ═══ 生命线导航 ═══ -->
      <div class="ap-nav">
        <template v-for="(n, i) in NAV" :key="n.stage">
          <button class="ap-nav-step" :class="{ on: activeNav === n.stage }" @click="scrollToStage(n.stage)">
            <span class="ap-nav-dot" :class="`nv-${(stageInfo[n.stage] || {}).state || 'pending'}`">{{ n.icon }}</span>
            <span class="ap-nav-lab">{{ n.label }}</span>
          </button>
          <span v-if="i < NAV.length - 1" class="ap-nav-line"
            :class="{ 'nv-line-done': (stageInfo[NAV[i].stage] || {}).state === 'done' }"></span>
        </template>
      </div>

      <!-- ═══ 智能下一步 ═══ -->
      <div v-if="!loading && nextAction" class="ap-next" :class="`nx-${nextAction.tone}`"
        :role="nextAction.cta ? 'button' : null" @click="nextAction.cta && scrollToStage(nextAction.stage)">
        <span class="ap-next-ico">{{ nextAction.icon }}</span>
        <span class="ap-next-txt">{{ nextAction.text }}</span>
        <span v-if="nextAction.cta" class="ap-next-cta">{{ nextAction.cta }} →</span>
      </div>

      <!-- ═══ 生命线主体 ═══ -->
      <div ref="bodyEl" class="ap-body">
        <template v-if="loading">
          <div class="ap-skeleton" v-for="n in 4" :key="n"></div>
        </template>
        <template v-else>
          <!-- 合同 -->
          <section :ref="el => registerSection('contract', el)" class="ap-contract">
            <div class="apc-head"><span class="apc-ico">📄</span><span class="apc-title">合同 / 概要</span><span class="apc-done">已签订</span></div>
            <div class="apc-grid">
              <div class="apc-cell"><i>客户</i><b>{{ rec.customer_name || '—' }}</b></div>
              <div class="apc-cell"><i>交付部门</i><b>{{ rec.delivery_dept || '—' }}</b></div>
              <div class="apc-cell"><i>预估应收</i><b>¥{{ fmtAmt(estimated) }}</b></div>
              <div class="apc-cell"><i>应收到期</i><b>{{ rec.due_date || '—' }}</b></div>
              <div class="apc-cell"><i>项目经理</i><b>{{ rec.project_manager || '—' }}</b></div>
              <div class="apc-cell"><i>开票方式</i><b>{{ rec.invoice_mode || '—' }}</b></div>
            </div>
            <div class="apc-notes">
              <span class="apc-notes-lab">备注</span>
              <textarea v-if="editingField === 'notes'" ref="fieldInp" v-model="fieldBuf" class="apc-notes-ta" rows="2"
                @blur="saveField" @keyup.escape="editingField = ''"></textarea>
              <span v-else class="apc-notes-val" :class="{ empty: !rec.notes, ro: !canWrite }" @click="beginField('notes', rec.notes)">
                {{ rec.notes || (canWrite ? '＋ 添加备注' : '—') }}
              </span>
            </div>
          </section>

          <!-- 对账 -->
          <LifelineSection
            stage="reconciliation" title="对账" icon="✓" :accent="ACCENT.reconciliation"
            :state="stageInfo.reconciliation.state" :state-label="stageInfo.reconciliation.label" :summary="stageInfo.reconciliation.summary"
            :activities="actsByStage.reconciliation" :attachments="attsByStage.reconciliation"
            :can-write="canWrite" :default-open="stageInfo.reconciliation.state !== 'done'"
            @save-edit="saveActEdit" @delete-act="deleteAct" @toggle-status="toggleStatus"
            @upload="f => uploadTo(f, 'reconciliation')" @delete-att="deleteAtt" @compose="focusCompose" @register="registerSection">
            <template #fields>
              <div class="kf">
                <span class="kf-lab">对账日期</span>
                <input v-if="editingField === 'reconciliation_date'" ref="fieldInp" v-model="fieldBuf" type="date" class="kf-inp"
                  @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                <span v-else class="kf-val" :class="{ empty: !rec.reconciliation_date, ro: !canWrite }" @click="beginField('reconciliation_date', rec.reconciliation_date)">
                  {{ rec.reconciliation_date || (canWrite ? '＋ 标记对账日' : '—') }}
                </span>
                <button v-if="canWrite && !rec.reconciliation_date && editingField !== 'reconciliation_date'" class="kf-today" @click="setToday('reconciliation_date')">今天</button>
              </div>
            </template>
          </LifelineSection>

          <!-- 开票 -->
          <LifelineSection
            stage="invoice" title="开票" icon="🧾" :accent="ACCENT.invoice"
            :state="stageInfo.invoice.state" :state-label="stageInfo.invoice.label" :summary="stageInfo.invoice.summary"
            :activities="actsByStage.invoice" :attachments="attsByStage.invoice"
            :can-write="canWrite" :default-open="stageInfo.invoice.state !== 'done'"
            @save-edit="saveActEdit" @delete-act="deleteAct" @toggle-status="toggleStatus"
            @upload="f => uploadTo(f, 'invoice')" @delete-att="deleteAtt" @compose="focusCompose" @register="registerSection">
            <template #fields>
              <div class="kf-grid">
                <div class="kf">
                  <span class="kf-lab">实际开票金额</span>
                  <input v-if="editingField === 'actual_invoice_amount'" ref="fieldInp" v-model="fieldBuf" type="number" step="0.01" class="kf-inp" :placeholder="`预估 ${estimated}`"
                    @blur="saveField" @keyup.enter="saveField" @keyup.escape="editingField = ''" />
                  <span v-else class="kf-val" :class="{ empty: rec.actual_invoice_amount == null, ro: !canWrite }" @click="beginField('actual_invoice_amount', rec.actual_invoice_amount)">
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
              <div v-if="rec.invoice_batch_no" class="kf-batch-hint">
                🔗 已并入批次 <b>{{ rec.invoice_batch_no }}</b>，可在「应收明细 · 批次」页做批量开票/回款
              </div>
            </template>
          </LifelineSection>

          <!-- 回款 -->
          <LifelineSection
            stage="collection" title="回款" icon="💰" :accent="ACCENT.collection"
            :state="stageInfo.collection.state" :state-label="stageInfo.collection.label" :summary="stageInfo.collection.summary"
            :activities="actsByStage.collection" :attachments="attsByStage.collection"
            :can-write="canWrite" :default-open="estimated > 0 && outstanding > 0"
            @save-edit="saveActEdit" @delete-act="deleteAct" @toggle-status="toggleStatus"
            @upload="f => uploadTo(f, 'collection')" @delete-att="deleteAtt" @compose="focusCompose" @register="registerSection">
            <template #fields>
              <!-- 回款进度 -->
              <div class="pay-prog">
                <div class="pay-prog-bar"><div class="pay-prog-fill" :style="{ width: (paidPct * 100) + '%' }"></div></div>
                <div class="pay-prog-txt"><span>已收 ¥{{ fmtAmt(paid) }}</span><span>待收 ¥{{ fmtAmt(outstanding) }}</span></div>
              </div>
              <!-- 回款明细 -->
              <div v-if="payments.length" class="pay-list">
                <div v-for="p in payments" :key="p.id" class="pay-item">
                  <span class="pay-no">#{{ p.payment_no }}</span>
                  <span class="pay-amt">¥{{ fmtAmt(p.amount) }}</span>
                  <span class="pay-date">{{ p.payment_date }}</span>
                  <span class="pay-src" :class="{ 'pay-src-other': p.source !== '回款' }">{{ p.source }}</span>
                  <span v-if="p.counterparty_dept" class="pay-cp">↔ {{ p.counterparty_dept }}</span>
                  <button v-if="canCollect && p.source !== '预收抵扣'" class="pay-del" title="删除" @click="deletePayment(p)">🗑</button>
                </div>
              </div>
              <div v-else class="pay-empty">暂无回款记录</div>
              <!-- 登记回款 / 内部往来核销 -->
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
            </template>
          </LifelineSection>

          <!-- 催款 -->
          <LifelineSection
            stage="dunning" title="催款" icon="🔔" :accent="ACCENT.dunning"
            :state="stageInfo.dunning.state" :state-label="stageInfo.dunning.label" :summary="stageInfo.dunning.summary"
            :activities="actsByStage.dunning" :attachments="attsByStage.dunning"
            :can-write="canWrite" :default-open="true"
            @save-edit="saveActEdit" @delete-act="deleteAct" @toggle-status="toggleStatus"
            @upload="f => uploadTo(f, 'dunning')" @delete-att="deleteAtt" @compose="focusCompose" @register="registerSection">
            <template #fields>
              <div class="kf-grid">
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
              <div v-if="daysSinceLastDun != null" class="dun-last" :class="{ cold: daysSinceLastDun >= 7 }">
                <template v-if="daysSinceLastDun === 0">🔥 今天已跟进</template>
                <template v-else>{{ daysSinceLastDun >= 7 ? '🥶' : '🕓' }} 上次跟进 {{ daysSinceLastDun }} 天前{{ daysSinceLastDun >= 7 ? ' · 建议再跟进' : '' }}</template>
              </div>
            </template>
          </LifelineSection>
        </template>
      </div>

      <!-- ═══ 上下文录入条 ═══ -->
      <div v-if="canWrite && !loading" class="ap-compose">
        <div class="ap-cmp-row1">
          <button v-for="t in ACT_TYPES" :key="t.v" class="ap-cmp-type" :class="{ on: compose.act_type === t.v }" :title="t.t" @click="compose.act_type = t.v">{{ t.l }}</button>
          <span class="ap-cmp-target">记入 <b :style="{ color: ACCENT[composeStage] }">{{ STAGE_LABEL[composeStage] }}</b></span>
        </div>
        <div class="ap-cmp-phrases">
          <button v-for="p in QUICK_PHRASES" :key="p" class="ap-cmp-phrase" :title="`插入：${p}`" @click="insertPhrase(p)">{{ p }}</button>
        </div>
        <textarea v-model="compose.note" ref="composeTa" class="ap-cmp-ta" rows="2"
          :placeholder="`记录${STAGE_LABEL[composeStage]}跟进…（Ctrl+Enter 保存）`" @keydown.ctrl.enter.prevent="submitCompose"></textarea>
        <div class="ap-cmp-row2">
          <select v-model="compose.status" class="ap-cmp-sel">
            <option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option>
          </select>
          <input v-model="compose.follow_up_date" type="date" class="ap-cmp-sel" title="计划跟进日期" />
          <button class="ap-cmp-btn" :disabled="adding || !compose.note.trim()" @click="submitCompose">{{ adding ? '保存…' : '记录' }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.ap-backdrop { position: fixed; inset: 0; z-index: 700; background: rgba(40,24,12,0.22); opacity: 0; transition: opacity .22s ease; }
.ap-backdrop.ap-open { opacity: 1; }
.ap-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: 560px; max-width: 96vw;
  z-index: 701; background: #fbf7f1; border-left: 1px solid rgba(180,140,110,.28);
  box-shadow: -10px 0 40px rgba(60,30,10,0.16);
  display: flex; flex-direction: column; overflow: hidden;
  transform: translateX(100%); transition: transform .24s cubic-bezier(.4,0,.2,1);
}
.ap-panel.ap-open { transform: translateX(0); }

/* 头部 */
.ap-header { padding: 13px 16px 11px; border-bottom: 1px solid rgba(180,140,110,.2); background: linear-gradient(135deg, #fceede, #fbf7f1); flex-shrink: 0; }
.ap-htop { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.ap-title { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.ap-proj { font-size: 16px; font-weight: 800; color: #5a4636; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-sub { font-size: 11.5px; color: #9b8070; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ap-hbtns { display: flex; align-items: center; gap: 5px; flex-shrink: 0; }
.ap-icobtn { border: none; background: rgba(0,0,0,.04); width: 26px; height: 26px; border-radius: 50%; font-size: 12px; cursor: pointer; transition: all .12s; }
.ap-icobtn:hover { background: rgba(201,99,66,.12); }
.ap-close { border: none; background: rgba(0,0,0,.04); width: 26px; height: 26px; border-radius: 50%; font-size: 13px; color: #9b8070; cursor: pointer; flex-shrink: 0; transition: all .12s; }
.ap-close:hover { background: rgba(201,99,66,.12); color: #c96342; }

/* 金额进度 */
.ap-money { margin-top: 9px; }
.ap-money-row { display: flex; justify-content: space-between; align-items: baseline; }
.ap-m-est { font-size: 13px; font-weight: 800; color: #5a4636; }
.ap-m-pct { font-size: 12px; font-weight: 800; color: #2e9e5b; }
.ap-bar { height: 7px; border-radius: 4px; background: rgba(180,140,110,.18); overflow: hidden; margin: 4px 0; }
.ap-bar-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, #66bb6a, #2e9e5b); transition: width .4s ease; }
.ap-money-foot { display: flex; justify-content: space-between; font-size: 11.5px; }
.ap-m-paid { color: #2e7d32; font-weight: 600; }
.ap-m-out { color: #8a7665; font-weight: 600; }
.ap-m-danger { color: #c62828; }
.ap-m-od { font-style: normal; font-size: 10px; background: rgba(198,40,40,.12); color: #c62828; padding: 0 6px; border-radius: 7px; margin-left: 4px; font-weight: 700; }

/* 生命线导航 */
.ap-nav { display: flex; align-items: flex-start; padding: 10px 14px; border-bottom: 1px solid rgba(180,140,110,.15); background: rgba(255,253,250,.6); flex-shrink: 0; }
.ap-nav-step { display: flex; flex-direction: column; align-items: center; gap: 4px; border: none; background: none; cursor: pointer; padding: 2px 0; width: 50px; flex-shrink: 0; border-radius: 9px; transition: background .12s; }
.ap-nav-step:hover { background: rgba(201,99,66,.06); }
.ap-nav-step.on .ap-nav-lab { color: #c96342; font-weight: 800; }
.ap-nav-dot { width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; background: #f0e6dc; color: #a8917e; transition: box-shadow .15s; }
.ap-nav-step.on .ap-nav-dot { box-shadow: 0 0 0 3px rgba(201,99,66,.16); }
.nv-done { background: linear-gradient(145deg, #66bb6a, #2e7d32); color: #fff; }
.nv-active { background: linear-gradient(145deg, #e07848, #c96342); color: #fff; }
.nv-partial { background: linear-gradient(145deg, #ffb74d, #f57c00); color: #fff; }
.nv-urgent { background: linear-gradient(145deg, #ef5350, #c62828); color: #fff; animation: nv-pulse 1.4s ease-out infinite; }
@keyframes nv-pulse { 0% { box-shadow: 0 0 0 0 rgba(239,83,80,.5); } 100% { box-shadow: 0 0 0 8px rgba(239,83,80,0); } }
.ap-nav-lab { font-size: 11px; color: #8a7665; white-space: nowrap; }
.ap-nav-line { flex: 1; height: 2px; background: rgba(180,140,110,.25); margin-top: 15px; border-radius: 2px; min-width: 4px; }
.nv-line-done { background: linear-gradient(90deg, #66bb6a, #2e7d32); }

/* 智能下一步 */
.ap-next { display: flex; align-items: center; gap: 9px; padding: 9px 16px; flex-shrink: 0; border-bottom: 1px solid rgba(180,140,110,.15); font-size: 12.5px; font-weight: 600; }
.ap-next[role="button"] { cursor: pointer; transition: filter .12s; }
.ap-next[role="button"]:hover { filter: brightness(.97); }
.ap-next-ico { font-size: 15px; flex-shrink: 0; }
.ap-next-txt { flex: 1; min-width: 0; }
.ap-next-cta { font-size: 11.5px; font-weight: 800; padding: 3px 12px; border-radius: 8px; background: rgba(255,255,255,.7); flex-shrink: 0; }
.nx-danger { background: linear-gradient(90deg, #fdeceb, #fbf7f1); color: #c62828; }
.nx-danger .ap-next-cta { color: #c62828; }
.nx-warn { background: linear-gradient(90deg, #fdf3e6, #fbf7f1); color: #e8830c; }
.nx-warn .ap-next-cta { color: #e8830c; }
.nx-info { background: linear-gradient(90deg, #eaf2fb, #fbf7f1); color: #1565c0; }
.nx-info .ap-next-cta { color: #1565c0; }
.nx-done { background: linear-gradient(90deg, #eaf6ec, #fbf7f1); color: #2e7d32; }

/* 主体 */
.ap-body { flex: 1; overflow-y: auto; padding: 12px 14px; display: flex; flex-direction: column; gap: 11px; scroll-behavior: smooth; }
.ap-body > section { scroll-margin-top: 8px; }
.ap-skeleton { height: 66px; border-radius: 12px; background: linear-gradient(90deg, rgba(180,140,110,.08), rgba(180,140,110,.16), rgba(180,140,110,.08)); background-size: 200% 100%; animation: ap-sk 1.3s ease infinite; }
@keyframes ap-sk { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* 合同区块 */
.ap-contract { border: 1px solid rgba(180,140,110,.2); border-radius: 12px; background: #fff; padding: 11px 13px; }
.apc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 9px; }
.apc-ico { width: 26px; height: 26px; border-radius: 50%; background: linear-gradient(145deg, #b8a48f, #97826c); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 13px; }
.apc-title { font-size: 13.5px; font-weight: 800; color: #5a4636; }
.apc-done { font-size: 10.5px; font-weight: 700; padding: 1px 8px; border-radius: 8px; color: #2e7d32; background: rgba(46,125,50,.1); }
.apc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px; }
.apc-cell { display: flex; flex-direction: column; gap: 1px; }
.apc-cell i { font-size: 10.5px; color: #a8917e; font-style: normal; }
.apc-cell b { font-size: 12.5px; color: #5a4636; font-weight: 700; }
.apc-notes { display: flex; align-items: flex-start; gap: 8px; margin-top: 9px; padding-top: 9px; border-top: 1px solid rgba(180,140,110,.14); }
.apc-notes-lab { font-size: 10.5px; color: #a8917e; flex-shrink: 0; padding-top: 2px; }
.apc-notes-val { font-size: 12.5px; color: #5a4636; cursor: pointer; flex: 1; padding: 2px 7px; border-radius: 6px; border: 1px solid transparent; white-space: pre-wrap; word-break: break-word; }
.apc-notes-val:hover { background: #fbf7f1; border-color: rgba(201,99,66,.22); }
.apc-notes-val.empty { color: #c0ad9d; }
.apc-notes-val.ro { cursor: default; }
.apc-notes-val.ro:hover { background: none; border-color: transparent; }
.apc-notes-ta { flex: 1; border: 1px solid rgba(201,99,66,.4); border-radius: 6px; padding: 5px 8px; font-size: 12.5px; color: #5a4636; resize: vertical; font-family: inherit; outline: none; box-sizing: border-box; }

/* 关键字段 */
.kf-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px; }
.kf { display: flex; align-items: center; gap: 8px; min-width: 0; }
.kf-lab { font-size: 11px; color: #a8917e; flex-shrink: 0; }
.kf-val { font-size: 12.5px; color: #5a4636; cursor: pointer; padding: 2px 8px; border-radius: 6px; border: 1px solid transparent; transition: all .1s; font-weight: 600; }
.kf-val:hover { background: #fff; border-color: rgba(201,99,66,.25); }
.kf-val.empty { color: #c0ad9d; font-weight: 400; }
.kf-val.ro { cursor: default; }
.kf-val.ro:hover { background: none; border-color: transparent; }
.kf-inp { border: 1px solid rgba(201,99,66,.45); border-radius: 6px; padding: 3px 7px; font-size: 12.5px; color: #5a4636; background: #fff; outline: none; font-family: inherit; max-width: 130px; }
.kf-today { border: 1px solid rgba(180,140,110,.3); background: #fff; color: #8a7665; font-size: 10px; padding: 2px 7px; border-radius: 6px; cursor: pointer; flex-shrink: 0; transition: all .12s; }
.kf-today:hover { border-color: #c96342; color: #c96342; }
.kf-batch-hint { font-size: 11px; color: #8e63c5; background: rgba(142,99,197,.08); padding: 5px 9px; border-radius: 7px; }
.kf-batch-hint b { font-weight: 800; }
.dun-last { font-size: 11px; color: #8a7665; padding: 2px 2px 0; }
.dun-last.cold { color: #c96342; font-weight: 600; }

/* 回款 */
.pay-prog { display: flex; flex-direction: column; gap: 4px; }
.pay-prog-bar { height: 8px; border-radius: 5px; background: rgba(180,140,110,.18); overflow: hidden; }
.pay-prog-fill { height: 100%; border-radius: 5px; background: linear-gradient(90deg, #66bb6a, #2e9e5b); transition: width .4s ease; }
.pay-prog-txt { display: flex; justify-content: space-between; font-size: 11px; color: #8a7665; font-weight: 600; }
.pay-list { display: flex; flex-direction: column; gap: 5px; }
.pay-item { display: flex; align-items: center; gap: 8px; background: #fff; border: 1px solid rgba(180,140,110,.16); border-radius: 8px; padding: 6px 10px; }
.pay-no { font-size: 10.5px; color: #a8917e; font-weight: 700; flex-shrink: 0; }
.pay-amt { font-size: 13px; font-weight: 800; color: #2e7d32; font-variant-numeric: tabular-nums; }
.pay-date { font-size: 11.5px; color: #8a7665; }
.pay-src { font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 7px; color: #2e9e5b; background: rgba(46,158,91,.1); margin-left: auto; }
.pay-src-other { color: #e8830c; background: rgba(232,131,12,.1); }
.pay-cp { font-size: 10px; color: #8a7665; }
.pay-del { border: none; background: none; font-size: 11px; cursor: pointer; opacity: .65; flex-shrink: 0; }
.pay-del:hover { opacity: 1; }
.pay-empty { font-size: 11.5px; color: #bda797; text-align: center; padding: 6px 0; }
.pay-form { display: flex; flex-direction: column; gap: 6px; }
.pay-srcs { display: flex; gap: 5px; }
.pay-src-tab { flex: 1; border: 1px solid rgba(180,140,110,.28); background: #fff; color: #8a7665; font-size: 11.5px; padding: 5px 0; border-radius: 7px; cursor: pointer; transition: all .12s; }
.pay-src-tab:hover { border-color: rgba(46,158,91,.45); }
.pay-src-tab.on { border-color: #2e9e5b; background: rgba(46,158,91,.1); color: #25844c; font-weight: 700; }
.pay-add { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.pay-inp { border: 1px solid rgba(180,140,110,.3); border-radius: 7px; padding: 5px 8px; font-size: 12px; color: #5a4636; background: #fff; outline: none; font-family: inherit; min-width: 0; }
.pay-inp-amt { flex: 1; min-width: 90px; }
.pay-inp-dept { flex: 1; min-width: 110px; }
.pay-inp:focus { border-color: rgba(46,158,91,.5); }
.pay-btn { padding: 6px 14px; border: none; border-radius: 7px; background: linear-gradient(120deg, #2e9e5b, #25844c); color: #fff; font-size: 12px; font-weight: 700; cursor: pointer; flex-shrink: 0; }
.pay-btn:disabled { opacity: .5; cursor: default; }
.pay-settle { border: 1px dashed rgba(46,158,91,.5); background: rgba(46,158,91,.05); color: #25844c; font-size: 11.5px; font-weight: 700; padding: 6px; border-radius: 8px; cursor: pointer; transition: background .12s; }
.pay-settle:hover:not(:disabled) { background: rgba(46,158,91,.12); }
.pay-settle:disabled { opacity: .5; cursor: default; }

/* 录入条 */
.ap-compose { padding: 9px 14px 11px; border-top: 1px solid rgba(180,140,110,.18); background: rgba(255,253,250,.92); flex-shrink: 0; display: flex; flex-direction: column; gap: 6px; }
.ap-cmp-row1 { display: flex; gap: 5px; align-items: center; }
.ap-cmp-type { border: 1px solid rgba(180,140,110,.25); background: #fff; border-radius: 8px; padding: 3px 8px; font-size: 14px; cursor: pointer; line-height: 1; transition: all .12s; }
.ap-cmp-type:hover { border-color: rgba(201,99,66,.5); }
.ap-cmp-type.on { border-color: #c96342; background: rgba(201,99,66,.1); transform: translateY(-1px); }
.ap-cmp-target { margin-left: auto; font-size: 11px; color: #a8917e; }
.ap-cmp-target b { font-weight: 800; }
.ap-cmp-phrases { display: flex; gap: 5px; overflow-x: auto; padding-bottom: 1px; scrollbar-width: thin; }
.ap-cmp-phrase { flex-shrink: 0; border: 1px solid rgba(180,140,110,.28); background: #fff; color: #8a7665; font-size: 11px; padding: 3px 9px; border-radius: 12px; cursor: pointer; white-space: nowrap; transition: all .12s; }
.ap-cmp-phrase:hover { border-color: #c96342; color: #c96342; background: rgba(201,99,66,.05); }
.ap-cmp-ta { width: 100%; border: 1px solid rgba(180,140,110,.25); border-radius: 9px; padding: 8px 10px; font-size: 13px; color: #5a4636; resize: vertical; min-height: 40px; font-family: inherit; background: #fff; outline: none; box-sizing: border-box; transition: border-color .12s; }
.ap-cmp-ta:focus { border-color: rgba(201,99,66,.55); }
.ap-cmp-row2 { display: flex; gap: 6px; align-items: center; }
.ap-cmp-sel { border: 1px solid rgba(180,140,110,.28); border-radius: 7px; font-size: 12px; padding: 5px 7px; color: #5a4636; background: #fff; outline: none; font-family: inherit; }
.ap-cmp-btn { margin-left: auto; padding: 6px 20px; border: none; border-radius: 8px; background: linear-gradient(120deg, #c96342, #b5532f); color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; transition: filter .12s; }
.ap-cmp-btn:hover:not(:disabled) { filter: brightness(1.06); }
.ap-cmp-btn:disabled { opacity: .45; cursor: default; }
</style>
