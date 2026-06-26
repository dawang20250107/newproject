<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import ar from '../../api/ar.js'
import { useAuthStore } from '../../stores/auth.js'
import { todayCST } from '../../constants.js'

const auth = useAuthStore()
const data = ref(null)
const loading = ref(false)
const err = ref('')
const transfers = ref([])
const expandedDept = ref('')
const cardRefs = {}

const pessimistic = ref(false)
const showMethodology = ref(false)

const wan = v => {
  const n = parseFloat(v)
  if (v == null || isNaN(n)) return '—'
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  return (n / 1e4).toFixed(1) + '万'
}
const statusLabel = { ok: '健康', warn: '预警', danger: '告急' }

async function load() {
  loading.value = true; err.value = ''
  try {
    const res = await ar.cashPool()
    data.value = res.data
  } catch (e) {
    err.value = e?.msg || (typeof e === 'string' ? e.slice(0, 200) : '加载失败（服务器错误，请检查后端日志）')
    loading.value = false
    return
  }
  try {
    const trs = await ar.listPoolTransfers()
    transfers.value = trs.data.items
  } catch (_) {
    transfers.value = []
  }
  loading.value = false
}

const pools = computed(() => data.value?.pools || [])
const configured = computed(() => pools.value.filter(p => p.configured))
const unconfigured = computed(() => pools.value.filter(p => !p.configured))

const balanceLabel = computed(() => {
  const g = data.value?.group
  if (!g) return '资金余额'
  if (g.is_full_scope) return '集团资金余额'
  if (g.scope_dept_count === 1) return '本部门资金余额'
  return '合计资金余额（可见范围）'
})

const maxBalance = computed(() =>
  Math.max(1, ...configured.value.map(p => parseFloat(p.balance) || 0)))
const colHeight = p => Math.max(6, Math.min(90, (parseFloat(p.balance) || 0) / maxBalance.value * 90))
const warnTick = p => {
  const w = parseFloat(p.warning.amount)
  return w > 0 ? Math.min(100, w / maxBalance.value * 100) : null
}

function fillPct(p) {
  const bal = parseFloat(p.balance)
  const warn = parseFloat(p.warning.amount)
  if (bal <= 0) return 0
  if (warn <= 0) return 72
  return Math.min(88, (bal / (warn * 3)) * 100)
}

function projVal(p, key) {
  if (key === 'd30' && pessimistic.value) return p.projection.d30_with_pipeline
  return p.projection[key]
}
const projColor = v => (parseFloat(v) < 0 ? 'var(--c-danger)' : 'var(--c-success)')

function spark(p) {
  const vals = [parseFloat(p.balance), parseFloat(projVal(p, 'd30')),
                parseFloat(projVal(p, 'd60')), parseFloat(projVal(p, 'd90'))]
  const lo = Math.min(...vals, 0), hi = Math.max(...vals, 1)
  const span = hi - lo || 1
  const X = [10, 56, 102, 148], W = 158, H = 46
  const y = v => 6 + (1 - (v - lo) / span) * (H - 14)
  const pts = vals.map((v, i) => [X[i], y(v)])
  const line = pts.map((pt, i) => `${i ? 'L' : 'M'}${pt[0]},${pt[1].toFixed(1)}`).join(' ')
  const area = `${line} L${X[3]},${H - 2} L${X[0]},${H - 2} Z`
  const zero = lo < 0 ? y(0) : null
  const danger = vals.some(v => v < 0)
  return { pts, line, area, zero, danger, W, H }
}

function focusPool(dept) {
  expandedDept.value = dept
  nextTick(() => cardRefs[dept]?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
}

const showTransfer = ref(false)
const trForm = reactive({ from_dept: '', to_dept: '', amount: '', transfer_date: todayCST(), expected_return_date: '', notes: '' })
const trSaving = ref(false)
const canRequestTransfer = computed(() => auth.canArWrite && !auth.isSuperAdmin)
const myDepts = computed(() => auth.user?.departments || [])
const trStatusLabel = { pending: '待审批', approved: '已生效', rejected: '已拒绝' }

async function saveTransfer() {
  if (!trForm.from_dept || !trForm.to_dept || !(parseFloat(trForm.amount) > 0)) { alert('调出/调入/金额必填'); return }
  trSaving.value = true
  try {
    const res = await ar.createPoolTransfer({ ...trForm })
    showTransfer.value = false
    Object.assign(trForm, { from_dept: '', to_dept: '', amount: '', transfer_date: todayCST(), expected_return_date: '', notes: '' })
    if (res.data?.status === 'pending') alert('调拨申请已提交，待调出方事业部（或超管）审批后生效')
    await load()
  } catch (e) { alert(e?.msg || '调拨失败') }
  finally { trSaving.value = false }
}

function canReview(t) {
  if (t.status !== 'pending') return false
  if (auth.isSuperAdmin) return true
  return auth.canArWrite && myDepts.value.includes(t.from_dept)
    && t.created_by_id !== auth.user?.id
}
const canCancel = t => t.status === 'pending'
  && (auth.isSuperAdmin || t.created_by_id === auth.user?.id)

async function approveTransfer(t) {
  if (!confirm(`批准调拨：${t.from_dept} → ${t.to_dept} ¥${t.amount}？批准后立即生效（生效日=今天），两池余额随之变动。`)) return
  try { await ar.reviewPoolTransfer(t.id, { action: 'approve' }); await load() }
  catch (e) { alert(e?.msg || '审批失败') }
}
async function rejectTransfer(t) {
  const notes = prompt(`拒绝调拨申请：${t.from_dept} → ${t.to_dept} ¥${t.amount}\n请填写拒绝原因（将反馈给申请人）：`)
  if (notes === null) return
  try { await ar.reviewPoolTransfer(t.id, { action: 'reject', review_notes: notes }); await load() }
  catch (e) { alert(e?.msg || '审批失败') }
}
async function removeTransfer(t) {
  const tip = t.status === 'pending'
    ? `撤回调拨申请：${t.from_dept} → ${t.to_dept} ¥${t.amount}？`
    : `删除已生效的调拨记录：${t.from_dept} → ${t.to_dept} ¥${t.amount}？两池账面余额将回退。`
  if (!confirm(tip)) return
  try { await ar.deletePoolTransfer(t.id); await load() }
  catch (e) { alert(e?.msg || '删除失败') }
}

const showConfig = ref(false)
const cfgRows = ref([])
const cfgSaving = ref(false)
async function openConfig() {
  const res = await ar.poolConfigs()
  const existing = Object.fromEntries(res.data.items.map(c => [c.delivery_dept, c]))
  cfgRows.value = res.data.departments.map(d => ({
    delivery_dept: d,
    initial_date: existing[d]?.initial_date || '',
    initial_amount: existing[d]?.initial_amount || '',
    warning_days: existing[d]?.warning_days || 30,
    warning_amount: existing[d]?.warning_amount || '',
    saved: !!existing[d],
    origDate: existing[d]?.initial_date || '',
    origAmount: existing[d]?.initial_amount || '',
  }))
  showConfig.value = true
}
async function saveCfgRow(row) {
  if (!row.initial_date) { alert('期初基准日必填'); return }
  if (row.saved && (row.initial_date !== row.origDate
      || String(row.initial_amount || 0) !== String(row.origAmount || 0))) {
    if (!confirm(`「${row.delivery_dept}」已有期初基准（${row.origDate} / ¥${row.origAmount}）。\n修改期初基准日或期初金额将重算该池全部历史余额，历史调拨与预警状态也会随之变化。确认修改？`)) return
  }
  cfgSaving.value = true
  try {
    await ar.savePoolConfig({
      delivery_dept: row.delivery_dept, initial_date: row.initial_date,
      initial_amount: row.initial_amount || 0, warning_days: row.warning_days,
      warning_amount: row.warning_amount === '' ? null : row.warning_amount,
    })
    row.saved = true
    row.origDate = row.initial_date
    row.origAmount = row.initial_amount
    await load()
  } catch (e) { alert(e?.msg || '保存失败') }
  finally { cfgSaving.value = false }
}

const projDimDept = ref('')
const projDimMode = ref('project')
const projDimData = ref({})
const projDimLoading = ref({})

const dimKey = dept => `${dept}|${projDimMode.value}`

async function fetchProjDim(dept) {
  const key = dimKey(dept)
  if (projDimData.value[key]) return
  projDimLoading.value = { ...projDimLoading.value, [key]: true }
  try {
    const year = new Date().getFullYear()
    const res = await ar.projectCashflow({ dept, year, group_by: projDimMode.value })
    projDimData.value = { ...projDimData.value, [key]: res.data }
  } catch (_) {
    projDimData.value = { ...projDimData.value, [key]: null }
  } finally {
    projDimLoading.value = { ...projDimLoading.value, [key]: false }
  }
}

function toggleProjDim(dept) {
  if (projDimDept.value === dept) { projDimDept.value = ''; return }
  projDimDept.value = dept
  fetchProjDim(dept)
}

function setProjDimMode(mode) {
  if (projDimMode.value === mode) return
  projDimMode.value = mode
  if (projDimDept.value) fetchProjDim(projDimDept.value)
}

const onScopeChange = () => load()
onMounted(() => { load(); window.addEventListener('pk:depts-changed', onScopeChange) })
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template>
  <div class="cp-panel">
    <div v-if="loading && !data" class="cp-empty">加载中…</div>
    <div v-else-if="err" class="cp-empty err">{{ err }}</div>
    <template v-else-if="data">

      <!-- ══ 命令条 ══ -->
      <div class="cp-bar">
        <div class="cpb-brand">
          <span class="cpb-icon">💧</span>
          <div>
            <div class="cpb-title">资金池</div>
            <div class="cpb-date">{{ data.today }}</div>
          </div>
        </div>

        <div v-if="data.group" class="cpb-summary">
          <div class="cpb-main-num">{{ wan(data.group.balance) }}</div>
          <div class="cpb-main-label">{{ balanceLabel }}</div>
          <div class="cpb-projs">
            <span v-for="(k,i) in ['d30','d60','d90']" :key="k" class="cpb-proj">
              <em>+{{ [30,60,90][i] }}天</em>
              <b :style="`color:${projColor(data.group['projection_'+k])}`">{{ wan(data.group['projection_'+k]) }}</b>
            </span>
          </div>
        </div>

        <div class="cpb-alerts-area">
          <span v-if="data.group?.danger_count" class="cpb-alert-chip danger">
            🚨 {{ data.group.danger_count }} 池告急
          </span>
          <span v-if="data.group?.warn_count" class="cpb-alert-chip warn">
            ⚠ {{ data.group.warn_count }} 池预警
          </span>
          <span v-if="data.group?.pipeline_approved || data.group?.pipeline_pending"
                class="cpb-pipeline">
            在途 <b>{{ wan(data.group.pipeline_approved) }}</b>已批
            / <b>{{ wan(data.group.pipeline_pending) }}</b>审批中
          </span>
        </div>

        <div class="cpb-actions">
          <label class="pess-toggle" :class="{ on: pessimistic }"
                 title="勾选后：30天预测余额按审慎口径（含在途支出）计算">
            <input type="checkbox" v-model="pessimistic" /><span>审慎</span>
          </label>
          <button class="cpb-btn" @click="showMethodology = true">口径说明</button>
          <button v-if="auth.isSuperAdmin || canRequestTransfer" class="cpb-btn accent"
                  @click="showTransfer = true">
            ⇄ {{ auth.isSuperAdmin ? '调拨' : '申请调拨' }}
          </button>
          <button v-if="auth.isSuperAdmin" class="cpb-btn" @click="openConfig">⚙ 配置</button>
        </div>
      </div>

      <!-- ══ 水位总览条（横向）══ -->
      <div v-if="configured.length" class="rsv-strip">
        <div v-for="p in configured" :key="p.dept" class="rsv-seg"
             :class="`st-${p.warning?.status}`"
             :title="`${p.dept}：${wan(p.balance)} · 点击跳转`"
             @click="focusPool(p.dept)">
          <div class="rsv-fill" :class="`w-${p.warning?.status}`" :style="`width:${colHeight(p)}%`">
            <i v-if="warnTick(p)" class="rsv-warn-mark" :style="`left:${warnTick(p)}%`"></i>
          </div>
          <span class="rsv-label">{{ p.dept.replace('事业部','') }}</span>
          <span class="rsv-val">{{ wan(p.balance) }}</span>
        </div>
      </div>

      <!-- ══ 池列表（行式，非卡片）══ -->
      <div class="cp-list">
        <template v-for="p in configured" :key="p.dept">
          <!-- 池行 -->
          <div class="pool-row" :class="[`st-${p.warning?.status}`, { active: expandedDept === p.dept }]"
               :ref="el => { cardRefs[p.dept] = el }"
               @click="expandedDept = expandedDept === p.dept ? '' : p.dept">

            <!-- 竖向水管 -->
            <div class="pool-tube" :title="`水位 ${fillPct(p).toFixed(0)}%`">
              <div class="pool-tube-fill" :class="`w-${p.warning?.status}`"
                   :style="`height:${fillPct(p)}%`">
                <i class="ptf-wave"></i>
              </div>
              <i v-if="parseFloat(p.warning?.amount) > 0" class="pool-tube-warn"></i>
            </div>

            <!-- 事业部 + 状态 -->
            <div class="pool-id">
              <span class="pool-name">{{ p.dept.replace('事业部', '') }}</span>
              <span v-if="p.error" class="pool-badge err">出错</span>
              <span v-else class="pool-badge" :class="`bd-${p.warning.status}`">
                {{ statusLabel[p.warning.status] }}
              </span>
            </div>

            <!-- 余额 -->
            <div class="pool-balance" :class="{ neg: parseFloat(p.balance) < 0 }">
              {{ wan(p.balance) }}
              <span class="pool-warn-line-label" v-if="!p.error">
                预警 {{ wan(p.warning.amount) }}
              </span>
            </div>

            <!-- 预测迷你图 -->
            <svg v-if="!p.error" class="pool-spark"
                 :viewBox="`0 0 ${spark(p).W} ${spark(p).H}`" width="110" height="32">
              <line v-if="spark(p).zero != null"
                    x1="6" :y1="spark(p).zero" :x2="spark(p).W-4" :y2="spark(p).zero"
                    stroke="#c62828" stroke-width="1" stroke-dasharray="3,3" opacity=".5" />
              <path :d="spark(p).area"
                    :fill="spark(p).danger ? 'rgba(198,40,40,.09)' : 'rgba(201,99,66,.1)'" />
              <path :d="spark(p).line" fill="none"
                    :stroke="spark(p).danger ? '#c62828' : '#c96342'"
                    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
              <circle v-for="(pt,i) in spark(p).pts" :key="i"
                      :cx="pt[0]" :cy="pt[1]" r="2.2"
                      :fill="spark(p).danger ? '#c62828' : '#c96342'" />
            </svg>

            <!-- 健康 KPI 小标签 -->
            <div v-if="!p.error" class="pool-kpi-row">
              <span class="kpi-tag" :class="parseFloat(projVal(p,'d30'))>=0?'good':'bad'"
                    title="+30天预测余额（审慎口径下含在途支出扣减）">
                +30天 {{ wan(projVal(p, 'd30')) }}
              </span>
              <span class="kpi-tag neutral"
                    title="按近90天日均流出，当前余额可支撑天数">
                {{ p.health.runway_days != null ? p.health.runway_days + '天续航' : '∞续航' }}
              </span>
              <span class="kpi-tag" :class="(p.health.self_rate ?? 0) >= 100 ? 'good' : 'warn'"
                    title="近90天流入/流出，>100%为净流入">
                自给 {{ p.health.self_rate != null ? p.health.self_rate + '%' : '—' }}
              </span>
            </div>

            <div class="pool-chevron" :class="{ open: expandedDept === p.dept }">›</div>
          </div>

          <!-- 手风琴详情 -->
          <Transition name="acc">
            <div v-if="expandedDept === p.dept && !p.error" class="pool-detail">
              <div class="pd-cols">

                <!-- 收支构成 -->
                <div class="pd-col">
                  <div class="pd-col-head">收支构成</div>
                  <div class="pd-row"><i>期初（{{ p.config.initial_date }}）</i><b>{{ wan(p.parts.initial) }}</b></div>
                  <div class="pd-row in"><i>＋ 回款</i><b>{{ wan(p.parts.collected) }}</b></div>
                  <div class="pd-row in"><i>＋ 预收款</i><b>{{ wan(p.parts.advance_received) }}</b></div>
                  <div class="pd-row out"><i>− 实付（已扣预付冲抵）</i><b>{{ wan(p.parts.paid) }}</b></div>
                  <div class="pd-row out"><i>− 预付款</i><b>{{ wan(p.parts.advance_paid) }}</b></div>
                  <div v-if="parseFloat(p.parts.transfer_in) || parseFloat(p.parts.transfer_out)" class="pd-row">
                    <i>± 调拨（已生效）</i>
                    <b>+{{ wan(p.parts.transfer_in) }} / −{{ wan(p.parts.transfer_out) }}</b>
                  </div>
                  <div v-if="parseFloat(p.balance) < 0" class="pd-negtip">
                    ⚠ 账面余额为负——请核对期初基准与收支流水是否完整
                  </div>
                </div>

                <!-- 待付与在途 -->
                <div class="pd-col">
                  <div class="pd-col-head">刚性待付 · 在途</div>
                  <div class="pd-row out"><i>已到期未付</i><b style="color:var(--c-danger)">{{ wan(p.committed.overdue) }}</b></div>
                  <div class="pd-row out"><i>30 / 60 / 90天待付</i><b>{{ wan(p.committed.d30) }} / {{ wan(p.committed.d60) }} / {{ wan(p.committed.d90) }}</b></div>
                  <div class="pd-row"><i>在途：已批待排 / 审批中</i><b>{{ wan(p.pipeline.approved) }} / {{ wan(p.pipeline.pending) }}</b></div>
                  <div v-if="parseFloat(p.pipeline.transfer_out_pending)" class="pd-row out">
                    <i>待批调拨出款申请</i><b style="color:#e65100">{{ wan(p.pipeline.transfer_out_pending) }}</b>
                  </div>
                  <div class="pd-col-head" style="margin-top:10px">预期回款</div>
                  <div class="pd-row in"><i>30 / 60 / 90天内</i><b>{{ wan(p.expected_in.d30) }} / {{ wan(p.expected_in.d60) }} / {{ wan(p.expected_in.d90) }}</b></div>
                  <div class="pd-row"><i>逾期应收在外</i><b style="color:#e65100">{{ wan(p.expected_in.overdue_outstanding) }}</b></div>
                </div>

                <!-- 项目维度 -->
                <div class="pd-col">
                  <div class="pd-col-head">
                    项目维度
                    <span class="dim-seg" @click.stop>
                      <button :class="{ on: projDimMode === 'project' }" @click="setProjDimMode('project')">项目</button>
                      <button :class="{ on: projDimMode === 'secondary_dept' }" @click="setProjDimMode('secondary_dept')">二级部门</button>
                    </span>
                    <button class="pd-load-btn" @click.stop="toggleProjDim(p.dept)">
                      {{ projDimDept === p.dept ? '收起' : '加载' }}
                    </button>
                  </div>
                  <div v-if="projDimLoading[dimKey(p.dept)]" class="pd-loading">加载中…</div>
                  <template v-else-if="projDimDept === p.dept && projDimData[dimKey(p.dept)]">
                    <div v-if="projDimData[dimKey(p.dept)].rows?.length" class="pd-proj-list">
                      <div v-for="r in projDimData[dimKey(p.dept)].rows.slice(0, 8)" :key="r.project" class="pd-proj-row">
                        <span class="ppr-name" :title="r.project">{{ r.project }}</span>
                        <span class="ppr-in" title="年内流入">↑{{ wan(r.inflow) }}</span>
                        <span class="ppr-out" title="年内流出">↓{{ wan(r.outflow) }}</span>
                        <span class="ppr-net" :style="{ color: r.net >= 0 ? 'var(--c-success)' : 'var(--c-danger)' }">{{ wan(r.net) }}</span>
                      </div>
                      <div v-if="projDimData[dimKey(p.dept)].rows.length > 8" class="pd-more">
                        还有 {{ projDimData[dimKey(p.dept)].rows.length - 8 }} 条
                        <router-link :to="`/caiwu/project-cashflow?dept=${encodeURIComponent(p.dept)}`">查看全部 →</router-link>
                      </div>
                    </div>
                    <div v-else class="pd-loading">暂无关联{{ projDimMode === 'project' ? '项目' : '二级部门' }}数据</div>
                  </template>
                  <div v-else-if="projDimDept === p.dept" class="pd-loading">加载失败，请稍后重试</div>
                  <div v-else class="pd-hint">点击「加载」查看{{ projDimMode === 'project' ? '项目' : '二级部门' }}维度现金分布</div>
                </div>
              </div>
            </div>
          </Transition>
        </template>

        <!-- 未配置的池 -->
        <div v-for="p in unconfigured" :key="p.dept" class="pool-row st-none nocfg">
          <div class="pool-tube"></div>
          <div class="pool-id">
            <span class="pool-name">{{ p.dept.replace('事业部', '') }}</span>
            <span class="pool-badge bd-none">未配置</span>
          </div>
          <div class="pool-nocfg-txt">
            未配置期初基准，暂无法核算余额
            <button v-if="auth.isSuperAdmin" class="cpb-btn" style="margin-left:10px" @click.stop="openConfig">去配置</button>
          </div>
        </div>
      </div>

      <!-- ══ 调拨台账（精简列表，位于池列表下方）══ -->
      <div v-if="transfers.length" class="cp-ledger">
        <div class="ledger-head">⇄ 池间调拨台账 <em>（{{ transfers.length }} 条）</em></div>
        <div class="ledger-list">
          <div v-for="t in transfers" :key="t.id" class="ledger-item" :class="`trs-${t.status}`">
            <span class="ts-chip" :class="`ts-${t.status}`">{{ trStatusLabel[t.status] || t.status }}</span>
            <span class="tr-date">{{ t.transfer_date }}</span>
            <span class="tr-route">
              <b>{{ t.from_dept.replace('事业部', '') }}</b>
              <i class="tr-pipe">→</i>
              <b>{{ t.to_dept.replace('事业部', '') }}</b>
            </span>
            <span class="tr-amt">{{ wan(t.amount) }}</span>
            <span class="tr-notes">
              <em v-if="t.expected_return_date">归还 {{ t.expected_return_date }}</em>
              <em v-if="t.notes">{{ t.notes }}</em>
              <em v-if="t.created_by_name">申请 {{ t.created_by_name }}</em>
              <em v-if="t.reviewed_by_name">审批 {{ t.reviewed_by_name }}</em>
              <em v-if="t.status === 'rejected' && t.review_notes" class="rej">拒：{{ t.review_notes }}</em>
            </span>
            <template v-if="canReview(t)">
              <button class="tr-ok" @click="approveTransfer(t)">批准</button>
              <button class="tr-del" @click="rejectTransfer(t)">拒绝</button>
            </template>
            <button v-if="canCancel(t) && !canReview(t)" class="tr-del" @click="removeTransfer(t)">撤回</button>
            <button v-else-if="auth.isSuperAdmin && t.status !== 'pending'" class="tr-del" @click="removeTransfer(t)">删</button>
          </div>
        </div>
      </div>

    </template><!-- end v-else-if data -->

    <!-- ══ 口径说明 Modal ══ -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showMethodology" class="modal-mask" @click.self="showMethodology = false">
          <div class="modal-box">
            <div class="modal-hd">
              <span class="modal-title">口径说明</span>
              <button class="modal-close" @click="showMethodology = false">✕</button>
            </div>
            <div class="modal-bd">
              <ul class="method-list">
                <li><b>账面余额</b> ＝ 期初金额 ＋ 现金流入 − 现金流出 ± 池间调拨（仅已生效的调拨计入）。</li>
                <li class="method-note">
                  <b>为什么与「现金流分析」对不上？</b>
                  资金池余额是<b>存量</b>（期初基准日累计至今，含池间调拨）；
                  现金流分析是<b>选定区间的流量</b>（不含期初基准，不含内部调拨）。
                  二者口径不同，<b>不应直接相等</b>。单个事业部尤其明显——调拨改变池余额，但不进入现金流分析。
                </li>
                <li><b>现金流入</b> ＝ 应收回款 ＋ 预收款。<b>预收冲抵</b>不计现金流入——现金在预收入账时已计入，冲抵只是账务确认。</li>
                <li><b>现金流出</b> ＝ 实付分期 ＋ 预付款 − <b>预付冲抵</b>。预付发生时已流出，冲抵时无新现金事件。</li>
                <li><b>刚性待付</b> ＝ 付款管理中已审批待付余额（计划金额 − 已付 − 预付冲抵），按计划付款日分 30/60/90 天窗口。</li>
                <li><b>在途支出</b> ＝ 审批记录中「已批待排 / 审批中」金额 ＋ 待审批调拨出款申请。尚未排款，金额存在不确定性。</li>
                <li><b>资金预警线</b> ＝ 超管手动设定的最低安全余额；未设定时按「未来 N 天刚性待付」动态推算。余额低于预警线即「告急」。</li>
                <li><b>预测余额</b> ＝ 当前余额 ＋ 预期回款（按到期日分窗）− 刚性待付。审慎口径再扣除在途支出与待批调拨出款。</li>
              </ul>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ══ 调拨 Modal ══ -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showTransfer && (auth.isSuperAdmin || canRequestTransfer)"
             class="modal-mask" @click.self="showTransfer = false">
          <div class="modal-box transfer-modal">
            <div class="modal-hd">
              <span class="modal-title">{{ auth.isSuperAdmin ? '池间调拨' : '申请调拨' }}</span>
              <button class="modal-close" @click="showTransfer = false">✕</button>
            </div>
            <div class="modal-bd">
              <div class="tr-grid">
                <div class="tr-field">
                  <label class="tr-label">调出方</label>
                  <select v-model="trForm.from_dept" class="tr-sel">
                    <option value="">请选择</option>
                    <option v-for="p in configured" :key="p.dept" :value="p.dept">
                      {{ p.dept }}（{{ wan(p.balance) }}）
                    </option>
                  </select>
                </div>
                <div class="tr-arrow-center">→</div>
                <div class="tr-field">
                  <label class="tr-label">调入方</label>
                  <select v-model="trForm.to_dept" class="tr-sel">
                    <option value="">请选择</option>
                    <option v-for="p in configured" :key="p.dept" :value="p.dept">{{ p.dept }}</option>
                  </select>
                </div>
                <div class="tr-field">
                  <label class="tr-label">金额（元）</label>
                  <input v-model="trForm.amount" type="number" min="0" placeholder="0.00" class="tr-inp" />
                </div>
                <div v-if="auth.isSuperAdmin" class="tr-field">
                  <label class="tr-label">调拨日期</label>
                  <input v-model="trForm.transfer_date" type="date" class="tr-inp" />
                </div>
                <div class="tr-field">
                  <label class="tr-label">约定归还日（可选）</label>
                  <input v-model="trForm.expected_return_date" type="date" class="tr-inp" />
                </div>
                <div class="tr-field tr-field-full">
                  <label class="tr-label">备注</label>
                  <input v-model="trForm.notes" placeholder="如：拆借月息0.3%" class="tr-inp" />
                </div>
              </div>
              <div v-if="!auth.isSuperAdmin" class="tr-hint-box">
                申请须经调出方事业部（或超管）审批后生效；生效日以审批日为准
              </div>
              <div class="modal-footer">
                <button class="cpb-btn" @click="showTransfer = false">取消</button>
                <button class="cpb-btn accent" :disabled="trSaving" @click="saveTransfer">
                  {{ trSaving ? '提交中…' : (auth.isSuperAdmin ? '确认调拨' : '提交申请') }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ══ 池配置 Modal（超管）══ -->
    <div v-if="showConfig" class="modal-mask" @click.self="showConfig = false">
      <div class="modal-box config-modal">
        <div class="modal-hd">
          <span class="modal-title">池配置 — 期初基准</span>
          <button class="modal-close" @click="showConfig = false">✕</button>
        </div>
        <div class="modal-bd">
          <div class="cp-table-wrap">
            <table class="cp-table">
              <thead><tr>
                <th>事业部</th><th>期初基准日</th><th>期初金额(元)</th>
                <th title="手动设定的最低安全余额；留空则按预警窗口天数的刚性待付动态推算">资金预警线(元,可选)</th>
                <th title="未设固定预警线时：预警线 = 未来N天刚性待付">预警窗口(天)</th><th></th>
              </tr></thead>
              <tbody>
                <tr v-for="row in cfgRows" :key="row.delivery_dept">
                  <td><b>{{ row.delivery_dept }}</b> <span v-if="row.saved" style="color:var(--c-success)">✓</span></td>
                  <td><input v-model="row.initial_date" type="date" class="tr-inp" /></td>
                  <td><input v-model="row.initial_amount" type="number" class="tr-inp" style="width:120px" /></td>
                  <td><input v-model="row.warning_amount" type="number" min="0" placeholder="留空=按天数推算" class="tr-inp" style="width:130px" /></td>
                  <td><input v-model.number="row.warning_days" type="number" min="7" max="120" class="tr-inp" style="width:64px" /></td>
                  <td><button class="cpb-btn accent" :disabled="cfgSaving" @click="saveCfgRow(row)">保存</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="cfg-note">修改已有池子的期初基准日/期初金额，会重算该池自基准日以来的全部历史余额。</div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════
   基础
   ═══════════════════════════════════════════ */
.cp-panel { padding: 16px 0; }
.cp-empty { text-align: center; padding: 48px; color: var(--muted); }
.cp-empty.err { color: var(--c-danger); }

/* ═══════════════════════════════════════════
   命令条
   ═══════════════════════════════════════════ */
.cp-bar {
  display: flex; align-items: center; gap: 0;
  background: linear-gradient(135deg, #1e0e06 0%, #2e160a 50%, #3d1f0d 100%);
  border-radius: var(--radius-lg); margin-bottom: 12px;
  padding: 14px 20px; box-shadow: 0 8px 32px rgba(40,16,4,.28);
  border: 1px solid rgba(201,99,66,.18); flex-wrap: wrap; gap: 8px;
}
.cpb-brand { display: flex; align-items: center; gap: 10px; margin-right: 4px; }
.cpb-icon { font-size: 22px; filter: drop-shadow(0 2px 6px rgba(201,99,66,.5)); }
.cpb-title { font-size: 15px; font-weight: 800; color: #f5e8dc; line-height: 1; }
.cpb-date { font-size: 11px; color: #a07050; margin-top: 3px; }

.cpb-summary {
  display: flex; align-items: baseline; gap: 14px; padding: 0 18px;
  border-left: 1px solid rgba(201,99,66,.2); border-right: 1px solid rgba(201,99,66,.2);
  margin: 0 8px; flex-wrap: wrap;
}
.cpb-main-num {
  font-size: 32px; font-weight: 900; color: #fff;
  font-variant-numeric: tabular-nums; line-height: 1;
  text-shadow: 0 2px 16px rgba(201,99,66,.4);
}
.cpb-main-label { font-size: 11px; color: #a07050; align-self: flex-end; padding-bottom: 3px; }
.cpb-projs { display: flex; gap: 12px; align-items: center; }
.cpb-proj { display: flex; flex-direction: column; align-items: center; gap: 1px; }
.cpb-proj em { font-style: normal; font-size: 10px; color: #806040; }
.cpb-proj b { font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }

.cpb-alerts-area { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cpb-alert-chip {
  font-size: 11.5px; font-weight: 700; padding: 4px 12px;
  border-radius: 20px; white-space: nowrap;
}
.cpb-alert-chip.danger { background: rgba(255,82,82,.18); color: #ff9a90; animation: cpPulse 1.6s ease-in-out infinite; }
.cpb-alert-chip.warn { background: rgba(255,183,77,.16); color: #ffd27a; }
@keyframes cpPulse { 50% { box-shadow: 0 0 0 5px rgba(255,82,82,.1); } }
.cpb-pipeline { font-size: 11.5px; color: #a07050; white-space: nowrap; }
.cpb-pipeline b { color: #e8d0b0; font-weight: 700; font-variant-numeric: tabular-nums; }

.cpb-actions { display: flex; align-items: center; gap: 7px; margin-left: auto; flex-wrap: wrap; }
.pess-toggle {
  display: flex; align-items: center; gap: 5px; cursor: pointer; user-select: none;
  font-size: 12px; color: #c8a080; padding: 5px 11px 5px 9px; border-radius: 20px;
  border: 1px solid rgba(201,99,66,.28); background: rgba(255,255,255,.04);
  transition: all .15s;
}
.pess-toggle:hover { background: rgba(255,255,255,.09); }
.pess-toggle.on { background: rgba(201,99,66,.22); border-color: rgba(201,99,66,.5); color: #ffd8b8; }
.pess-toggle input { accent-color: #c96342; cursor: pointer; }
.cpb-btn {
  padding: 6px 14px; border: 1px solid rgba(201,99,66,.35); border-radius: 20px;
  background: rgba(255,255,255,.06); font-size: 12px; font-weight: 600; color: #e8d0b8;
  cursor: pointer; transition: all .15s; white-space: nowrap;
}
.cpb-btn:hover { background: rgba(201,99,66,.18); border-color: rgba(201,99,66,.6); }
.cpb-btn.accent { background: var(--grad); border: none; color: #fff; box-shadow: 0 3px 10px rgba(201,99,66,.35); }
.cpb-btn.accent:hover:not(:disabled) { filter: brightness(1.1); transform: translateY(-1px); }
.cpb-btn:disabled { opacity: .5; cursor: not-allowed; }

/* ═══════════════════════════════════════════
   水位总览条（横向进度条）
   ═══════════════════════════════════════════ */
.rsv-strip {
  display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px;
  background: var(--surface-1); border: 1px solid var(--border-soft);
  border-radius: var(--radius); padding: 10px 14px;
  box-shadow: var(--shadow-sm);
}
.rsv-seg {
  display: flex; align-items: center; gap: 8px; cursor: pointer;
  position: relative; height: 22px;
}
.rsv-seg:hover .rsv-fill { filter: brightness(1.12); }
.rsv-fill {
  position: relative; height: 14px; border-radius: 7px; min-width: 4px;
  transition: width .7s cubic-bezier(.2,.8,.3,1);
  flex-shrink: 0;
}
.rsv-fill.w-ok { background: linear-gradient(90deg, #c96342, #e8855a); }
.rsv-fill.w-warn { background: linear-gradient(90deg, #e65100, #ffb74d); }
.rsv-fill.w-danger { background: linear-gradient(90deg, #b71c1c, #e57373); }
.rsv-warn-mark {
  position: absolute; top: -3px; bottom: -3px; width: 2px;
  background: rgba(255,82,82,.9); border-radius: 1px;
  box-shadow: 0 0 4px rgba(255,82,82,.6);
}
.rsv-label { font-size: 11.5px; color: var(--text-2); font-weight: 600; min-width: 36px; white-space: nowrap; }
.rsv-val { font-size: 11.5px; color: var(--text); font-weight: 700; font-variant-numeric: tabular-nums; }

/* ═══════════════════════════════════════════
   池列表
   ═══════════════════════════════════════════ */
.cp-list {
  background: var(--surface-1); border: 1px solid var(--border-soft);
  border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-sm);
}

/* 池行 */
.pool-row {
  display: flex; align-items: center; gap: 12px; padding: 10px 16px;
  border-bottom: 1px solid var(--border-soft); cursor: pointer;
  transition: background .14s; position: relative;
  border-left: 3px solid transparent;
}
.pool-row:last-child { border-bottom: none; }
.pool-row:hover { background: var(--surface-tint); }
.pool-row.active { background: color-mix(in srgb, var(--primary) 4%, transparent); }
.pool-row.st-ok { border-left-color: var(--c-success); }
.pool-row.st-warn { border-left-color: var(--c-warn); }
.pool-row.st-danger { border-left-color: var(--c-danger); }
.pool-row.st-none { border-left-color: var(--border); cursor: default; }
.pool-row.nocfg { opacity: .7; }

/* 水管 */
.pool-tube {
  width: 12px; height: 48px; border-radius: 6px 6px 8px 8px; flex-shrink: 0;
  background: rgba(0,0,0,.06); border: 1.5px solid var(--border);
  position: relative; overflow: hidden;
}
.pool-tube-fill {
  position: absolute; bottom: 0; left: 0; right: 0;
  transition: height .8s cubic-bezier(.2,.8,.3,1);
  border-radius: 0 0 5px 5px;
}
.pool-tube-fill.w-ok { background: linear-gradient(180deg, #e8855a, #a84e32); }
.pool-tube-fill.w-warn { background: linear-gradient(180deg, #ffb74d, #e65100); }
.pool-tube-fill.w-danger { background: linear-gradient(180deg, #e57373, #b71c1c); }
.ptf-wave {
  position: absolute; top: -4px; left: 0; width: 200%; height: 5px;
  background: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 5" preserveAspectRatio="none"><path d="M0 2.5 Q 15 0 30 2.5 T 60 2.5 V5 H0 Z" fill="%23ffffff" opacity="0.5"/></svg>') repeat-x;
  background-size: 60px 5px; animation: waveDrift 4s linear infinite;
}
@keyframes waveDrift { to { transform: translateX(-50%); } }
.pool-tube-warn {
  position: absolute; left: -2px; right: -2px; bottom: 33.3%;
  border-top: 1.5px dashed rgba(198,40,40,.75);
}

/* 池行各列 */
.pool-id { display: flex; flex-direction: column; gap: 3px; min-width: 60px; flex-shrink: 0; }
.pool-name { font-size: 14px; font-weight: 800; color: var(--text); }
.pool-badge {
  font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 20px;
  width: fit-content;
}
.bd-ok { background: var(--c-success-bg); color: var(--c-success); border: 1px solid var(--c-success-bdr); }
.bd-warn { background: var(--c-warn-bg); color: var(--c-warn); border: 1px solid var(--c-warn-bdr); }
.bd-danger { background: var(--c-danger-bg); color: var(--c-danger); border: 1px solid var(--c-danger-bdr); animation: cpPulse 1.6s ease-in-out infinite; }
.bd-none { background: var(--surface-tint); color: var(--muted); border: 1px solid var(--border); }
.pool-badge.err { background: var(--c-danger-bg); color: var(--c-danger); border: 1px solid var(--c-danger-bdr); }

.pool-balance {
  font-size: 24px; font-weight: 900; color: var(--text);
  font-variant-numeric: tabular-nums; line-height: 1; min-width: 80px;
  display: flex; flex-direction: column; gap: 3px;
}
.pool-balance.neg { color: var(--c-danger); }
.pool-warn-line-label { font-size: 10px; font-weight: 500; color: var(--c-warn); }

.pool-spark { display: block; flex-shrink: 0; }

.pool-kpi-row { display: flex; gap: 5px; flex-wrap: wrap; flex: 1; }
.kpi-tag {
  font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 20px;
  border: 1px solid var(--border-soft); background: var(--surface-tint); color: var(--muted);
  white-space: nowrap;
}
.kpi-tag.good { color: var(--c-success); background: var(--c-success-bg); border-color: var(--c-success-bdr); }
.kpi-tag.bad { color: var(--c-danger); background: var(--c-danger-bg); border-color: var(--c-danger-bdr); }
.kpi-tag.warn { color: var(--c-warn); background: var(--c-warn-bg); border-color: var(--c-warn-bdr); }

.pool-chevron {
  font-size: 20px; color: var(--muted); transition: transform .2s, color .14s;
  flex-shrink: 0; line-height: 1;
}
.pool-chevron.open { transform: rotate(90deg); color: var(--primary); }
.pool-row:hover .pool-chevron { color: var(--text-2); }

.pool-nocfg-txt { font-size: 12.5px; color: var(--muted); flex: 1; }

/* 手风琴详情 */
.acc-enter-active { transition: all .24s ease; }
.acc-leave-active { transition: all .18s ease; }
.acc-enter-from, .acc-leave-to { opacity: 0; transform: translateY(-8px); max-height: 0; }
.acc-enter-to, .acc-leave-from { max-height: 600px; }

.pool-detail {
  padding: 14px 16px 16px 28px; border-bottom: 1px solid var(--border-soft);
  background: color-mix(in srgb, var(--primary) 3%, var(--surface-1));
  border-left: 3px solid color-mix(in srgb, var(--primary) 30%, transparent);
}
.pd-cols { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }
.pd-col { display: flex; flex-direction: column; gap: 2px; }
.pd-col-head {
  font-size: 11px; font-weight: 800; color: var(--primary); text-transform: uppercase;
  letter-spacing: .6px; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;
}
.pd-row { display: flex; justify-content: space-between; gap: 8px; font-size: 11.5px; padding: 2.5px 0; color: var(--text-2); border-bottom: 1px solid var(--border-soft); }
.pd-row:last-child { border-bottom: none; }
.pd-row i { font-style: normal; }
.pd-row b { color: var(--text); font-weight: 700; font-variant-numeric: tabular-nums; flex-shrink: 0; }
.pd-row.in b { color: var(--c-success); }
.pd-row.out b { color: var(--c-danger); }
.pd-negtip { font-size: 10.5px; color: var(--c-danger); background: var(--c-danger-bg); border-radius: var(--radius-xs); padding: 4px 8px; margin-top: 4px; }

/* 项目维度 */
.dim-seg { display: inline-flex; border: 1px solid var(--border-strong); border-radius: var(--radius-xs); overflow: hidden; margin-left: 4px; }
.dim-seg button { border: none; background: transparent; padding: 2px 8px; font-size: 10px; color: var(--muted); cursor: pointer; font-weight: 600; transition: all .12s; }
.dim-seg button + button { border-left: 1px solid var(--border); }
.dim-seg button.on { background: var(--primary); color: #fff; }
.pd-load-btn { border: 1px solid var(--border-strong); background: var(--surface-tint); color: var(--text-2); font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: var(--radius-xs); cursor: pointer; margin-left: 4px; transition: all .12s; }
.pd-load-btn:hover { background: rgba(201,99,66,.12); border-color: var(--primary); color: var(--primary); }
.pd-loading { font-size: 11px; color: var(--muted); padding: 8px 0; }
.pd-hint { font-size: 11px; color: var(--muted); padding: 8px 0; font-style: italic; }
.pd-proj-list { display: flex; flex-direction: column; gap: 1px; margin-top: 2px; }
.pd-proj-row { display: flex; align-items: center; gap: 5px; padding: 3px 0; font-size: 11px; border-bottom: 1px solid var(--border-soft); }
.pd-proj-row:last-child { border-bottom: none; }
.ppr-name { flex: 1; color: var(--text); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; min-width: 0; }
.ppr-in { color: var(--c-success); font-variant-numeric: tabular-nums; flex-shrink: 0; min-width: 48px; text-align: right; }
.ppr-out { color: var(--c-danger); font-variant-numeric: tabular-nums; flex-shrink: 0; min-width: 48px; text-align: right; }
.ppr-net { font-weight: 700; font-variant-numeric: tabular-nums; flex-shrink: 0; min-width: 48px; text-align: right; }
.pd-more { font-size: 11px; color: var(--muted); padding: 4px 0; }
.pd-more a { color: var(--primary); text-decoration: none; }
.pd-more a:hover { text-decoration: underline; }

/* ═══════════════════════════════════════════
   调拨台账
   ═══════════════════════════════════════════ */
.cp-ledger {
  margin-top: 12px; background: var(--surface-1); border: 1px solid var(--border-soft);
  border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-sm);
}
.ledger-head {
  padding: 9px 16px; font-size: 13px; font-weight: 800; color: var(--text);
  border-bottom: 1px solid var(--border-soft); background: var(--surface-tint);
}
.ledger-head em { font-style: normal; color: var(--muted); font-weight: 500; font-size: 11.5px; }
.ledger-list { display: flex; flex-direction: column; }
.ledger-item {
  display: flex; align-items: center; gap: 10px; padding: 8px 14px;
  font-size: 12px; border-bottom: 1px solid var(--border-soft); flex-wrap: wrap;
}
.ledger-item:last-child { border-bottom: none; }
.ledger-item:hover { background: var(--surface-tint); }
.ledger-item.trs-pending { background: color-mix(in srgb, var(--c-warn) 5%, transparent); border-left: 3px solid var(--c-warn); }
.ledger-item.trs-rejected { opacity: .6; }
.ts-chip { font-size: 10.5px; font-weight: 700; padding: 2px 9px; border-radius: 20px; flex-shrink: 0; }
.ts-pending { background: var(--c-warn-bg); color: var(--c-warn); }
.ts-approved { background: var(--c-success-bg); color: var(--c-success); }
.ts-rejected { background: rgba(120,120,120,.12); color: #888; }
.tr-date { color: var(--muted); font-variant-numeric: tabular-nums; flex-shrink: 0; }
.tr-route { display: flex; align-items: center; gap: 6px; font-weight: 700; color: var(--text); flex-shrink: 0; }
.tr-pipe { font-style: normal; color: var(--primary); font-weight: 800; }
.tr-amt { font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; flex-shrink: 0; }
.tr-notes { display: flex; gap: 10px; color: var(--muted); flex: 1; flex-wrap: wrap; }
.tr-notes em { font-style: normal; }
.tr-notes .rej { color: var(--c-danger); }
.tr-ok { border: 1px solid var(--c-success-bdr); color: var(--c-success); background: var(--c-success-bg); border-radius: var(--radius-xs); padding: 3px 10px; font-size: 11px; font-weight: 600; cursor: pointer; transition: filter .12s; }
.tr-ok:hover { filter: brightness(.94); }
.tr-del { border: 1px solid var(--c-danger-bdr); color: var(--c-danger); background: var(--c-danger-bg); border-radius: var(--radius-xs); padding: 3px 10px; font-size: 11px; font-weight: 600; cursor: pointer; transition: filter .12s; }
.tr-del:hover { filter: brightness(.94); }

/* ═══════════════════════════════════════════
   Modal 通用
   ═══════════════════════════════════════════ */
.modal-mask {
  position: fixed; inset: 0; background: rgba(10,5,2,.48);
  backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.modal-enter-active { transition: all .2s ease; }
.modal-leave-active { transition: all .16s ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; transform: scale(.96); }

.modal-box {
  background: var(--surface-2); border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg); width: min(560px, 94vw); max-height: 88vh;
  overflow: hidden; display: flex; flex-direction: column;
  box-shadow: 0 24px 64px rgba(10,5,2,.38), 0 1px 0 rgba(255,255,255,.8) inset;
}
.modal-box.transfer-modal { width: min(520px, 94vw); }
.modal-box.config-modal { width: min(820px, 96vw); }

.modal-hd {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px 14px; border-bottom: 1px solid var(--border-soft);
  background: var(--surface-tint); flex-shrink: 0;
}
.modal-title { font-size: 14px; font-weight: 800; color: var(--text); }
.modal-close {
  width: 28px; height: 28px; border: none; background: var(--surface-1);
  border-radius: 50%; cursor: pointer; font-size: 14px; color: var(--muted);
  display: flex; align-items: center; justify-content: center; transition: all .14s;
  border: 1px solid var(--border-soft);
}
.modal-close:hover { background: var(--c-danger-bg); color: var(--c-danger); border-color: var(--c-danger-bdr); }
.modal-bd { padding: 20px; overflow-y: auto; flex: 1; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border-soft); }

/* 口径说明 modal 内容 */
.method-list { margin: 0; padding-left: 18px; }
.method-list li { font-size: 12.5px; color: var(--text-2); line-height: 2; }
.method-list li b { color: var(--text); }
.method-note {
  margin: 10px 0; padding: 10px 14px; background: var(--surface-tint);
  border-left: 3px solid var(--primary); border-radius: var(--radius-xs);
  list-style: none; margin-left: -18px;
}

/* 调拨表单 */
.tr-grid { display: grid; grid-template-columns: 1fr auto 1fr; gap: 12px 10px; align-items: end; }
.tr-field { display: flex; flex-direction: column; gap: 5px; }
.tr-field-full { grid-column: 1 / -1; }
.tr-arrow-center { font-size: 22px; font-weight: 900; color: var(--primary); padding-bottom: 6px; text-align: center; }
.tr-label { font-size: 11.5px; font-weight: 700; color: var(--text-2); }
.tr-sel, .tr-inp {
  padding: 8px 10px; border: 1px solid var(--border-strong); border-radius: var(--radius-xs);
  font-size: 13px; background: var(--surface-1); color: var(--text); width: 100%;
  transition: border-color .14s, box-shadow .14s; box-sizing: border-box;
}
.tr-sel:focus, .tr-inp:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-glow); }
.tr-hint-box {
  margin-top: 12px; padding: 10px 13px; font-size: 11.5px; color: var(--c-warn);
  background: var(--c-warn-bg); border-radius: var(--radius-sm); border: 1px solid var(--c-warn-bdr);
}

/* 配置表格 */
.cp-table-wrap { overflow-x: auto; border-radius: var(--radius-sm); border: 1px solid var(--border-soft); }
.cp-table { width: 100%; min-width: 640px; border-collapse: collapse; font-size: 12.5px; }
.cp-table th { background: var(--surface-tint); color: var(--muted); padding: 8px 11px; font-weight: 700; text-align: left; white-space: nowrap; }
.cp-table td { padding: 8px 11px; border-bottom: 1px solid var(--border-soft); white-space: nowrap; }
.cp-table tbody tr:last-child td { border-bottom: none; }
.cfg-note { margin-top: 10px; font-size: 11px; color: var(--c-warn); }

/* 响应式 */
@media (max-width: 768px) {
  .pd-cols { grid-template-columns: 1fr; }
  .cpb-summary { border: none; padding: 0; margin: 0; }
  .cpb-projs { flex-wrap: wrap; }
  .pool-spark { display: none; }
  .tr-grid { grid-template-columns: 1fr; }
  .tr-arrow-center { display: none; }
}
</style>
