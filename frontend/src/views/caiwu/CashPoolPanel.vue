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

// 审慎口径开关：已批待排的在途支出与待批调拨出款，按30天内全部付出计入预测
const pessimistic = ref(false)
// 余额构成与预测的口径说明
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
  // Transfers are secondary; a failure should not block the pool overview
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

// ── 余额对比条：各池柱高按最大余额归一 ──────────────────────────────────────
const maxBalance = computed(() =>
  Math.max(1, ...configured.value.map(p => parseFloat(p.balance) || 0)))
const colHeight = p => Math.max(6, Math.min(90, (parseFloat(p.balance) || 0) / maxBalance.value * 90))
const warnTick = p => {
  const w = parseFloat(p.warning.amount)
  return w > 0 ? Math.min(100, w / maxBalance.value * 100) : null
}

// ── 余额刻度图填充：以「资金预警线×3」为满格基准，预警线天然落在 1/3 高度；
//    封顶 88% 留出顶部呼吸空间 ──────────────────────────────────────────────
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
const projColor = v => (parseFloat(v) < 0 ? '#ff8a80' : '#69f0ae')
const projColorDark = v => (parseFloat(v) < 0 ? '#c62828' : '#2e7d32')

// ── 余额预测迷你曲线（现在→+30→+60→+90）────────────────────────────────────
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

// ── 池间调拨：超管直接生效；事业部用户提交申请，由调出方审批 ────────────────
const showTransfer = ref(false)
const trForm = reactive({ from_dept: '', to_dept: '', amount: '', transfer_date: todayCST(), expected_return_date: '', notes: '' })
const trSaving = ref(false)
// 事业部用户具备应收写入能力即可发起申请（与后端 _write_denied 口径一致）
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

// 审批权限：超管；或调出方事业部成员（有写入权限）且不是申请发起人本人
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

// ── 池配置（超管）──────────────────────────────────────────────────────────
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
  // 修改已生效的期初基准会重算该池自基准日以来的全部历史余额（含历史调拨校验口径）
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

const onScopeChange = () => load()
onMounted(() => { load(); window.addEventListener('pk:depts-changed', onScopeChange) })
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template>
  <div class="cp-panel">
    <div v-if="loading && !data" class="cp-empty">加载中…</div>
    <div v-else-if="err" class="cp-empty err">{{ err }}</div>
    <template v-else-if="data">

      <!-- ══ 集团资金总览横幅 ══ -->
      <div class="cp-hero">
        <div class="hero-waves"><i class="hw hw1"></i><i class="hw hw2"></i></div>
        <div class="hero-main">
          <div class="hero-title">资金池<span class="hero-sub">事业部资金调度 · {{ data.today }}</span></div>
          <template v-if="data.group">
            <div class="hero-balance">
              <div class="hb-num">{{ wan(data.group.balance) }}</div>
              <div class="hb-label">集团资金余额</div>
            </div>
            <div class="hero-flow">
              <div v-for="(k, i) in ['d30','d60','d90']" :key="k" class="hf-step">
                <div class="hf-val" :style="`color:${projColor(data.group['projection_' + k])}`">{{ wan(data.group['projection_' + k]) }}</div>
                <div class="hf-k">+{{ [30,60,90][i] }}天预测余额</div>
              </div>
              <div class="hf-step pipe">
                <div class="hf-val">{{ wan(data.group.pipeline_approved) }}<em> / {{ wan(data.group.pipeline_pending) }}</em></div>
                <div class="hf-k">在途支出：已批 / 审批中</div>
              </div>
            </div>
          </template>
          <div v-else class="hero-balance"><div class="hb-label">尚未配置任何资金池</div></div>
          <div class="hero-actions">
            <span v-if="data.group && (data.group.danger_count || data.group.warn_count)" class="hero-alert">
              <i v-if="data.group.danger_count" class="ha-danger">🚨 {{ data.group.danger_count }}池告急</i>
              <i v-if="data.group.warn_count" class="ha-warn">⚠ {{ data.group.warn_count }}池预警</i>
            </span>
            <label class="hero-pess" title="勾选后：30天预测余额按「已批待排的在途支出与待批调拨出款，30天内全部付出」的审慎口径计算">
              <input type="checkbox" v-model="pessimistic" />审慎口径
            </label>
            <button class="hero-btn" @click="showMethodology = !showMethodology">ⓘ 口径说明</button>
            <button v-if="auth.isSuperAdmin" class="hero-btn" @click="showTransfer = !showTransfer">⇄ 调拨</button>
            <button v-else-if="canRequestTransfer" class="hero-btn" @click="showTransfer = !showTransfer">⇄ 申请调拨</button>
            <button v-if="auth.isSuperAdmin" class="hero-btn" @click="openConfig">⚙ 池配置</button>
          </div>
        </div>

        <!-- 余额对比：各池柱形同一基准 -->
        <div v-if="configured.length" class="reservoir">
          <div v-for="p in configured" :key="p.dept" class="rsv-col" @click="focusPool(p.dept)"
               :title="`${p.dept}：账面余额 ${wan(p.balance)}（点击查看明细）`">
            <div class="rsv-amt">{{ wan(p.balance) }}</div>
            <div class="rsv-tube">
              <div class="rsv-water" :class="`w-${p.warning.status}`" :style="`height:${colHeight(p)}%`">
                <i class="rsv-wave"></i>
              </div>
              <i v-if="warnTick(p)" class="rsv-warntick" :style="`bottom:${warnTick(p)}%`"></i>
            </div>
            <div class="rsv-name" :class="`t-${p.warning.status}`">{{ p.dept.replace('事业部', '') }}</div>
          </div>
        </div>
      </div>

      <!-- ══ 口径说明 ══ -->
      <div v-if="showMethodology" class="cp-method card">
        <div class="section-title" style="margin-bottom:6px">口径说明（与现金流分析一致）</div>
        <ul>
          <li><b>账面余额</b> ＝ 期初金额 ＋ 现金流入 − 现金流出 ± 池间调拨（仅已生效的调拨计入）。</li>
          <li><b>现金流入</b> ＝ 应收回款 ＋ 预收款。其中<b>预收冲抵</b>（用客户预收款核销应收）不计现金流入——现金在预收入账当天已经计入，冲抵只是账务确认，再计就重复了。</li>
          <li><b>现金流出</b> ＝ 实付分期 ＋ 预付款 − <b>预付冲抵</b>（用预付余额抵减正式付款）。现金在预付发生当天已经流出，核销冲抵当天没有新的现金事件，不再重复计。</li>
          <li><b>刚性待付</b> ＝ 付款台账中已审批待付的余额（计划金额 − 已付 − 预付冲抵），按计划付款日分 30/60/90 天窗口。</li>
          <li><b>在途支出</b> ＝ 审批记录中「已批待排 / 审批中」的金额 ＋ 待审批的调拨出款申请。尚未排款，金额与时点存在不确定性。</li>
          <li><b>资金预警线</b> ＝ 超管手动设定的最低安全余额；未设定时按「未来 N 天刚性待付（含逾期未付）」动态推算。余额低于预警线即「告急」。</li>
          <li><b>预测余额</b> ＝ 当前余额 ＋ 预期回款（按到期日分窗）− 刚性待付。审慎口径再扣除在途支出与待批调拨出款。</li>
        </ul>
      </div>

      <!-- ══ 池子卡片 ══ -->
      <div class="cp-grid">
        <div v-for="p in configured" :key="p.dept" class="cp-card" :class="p.error ? 'st-none' : `st-${p.warning?.status}`"
             :ref="el => { cardRefs[p.dept] = el }">
          <div class="cpc-top">
            <div class="cpc-dept">{{ p.dept }}</div>
            <span v-if="!p.error" class="cpc-badge" :class="`bg-${p.warning.status}`">{{ statusLabel[p.warning.status] }}</span>
            <span v-else class="cpc-badge" style="background:#c62828;color:#fff">计算失败</span>
          </div>
          <div v-if="p.error" class="cpc-unconfigured" style="color:#c62828">
            指标计算出错：{{ p.error }}<br/>请重启后端服务后刷新，或查阅服务器日志排查原因
          </div>

          <div v-if="!p.error" class="cpc-body">
            <!-- 余额刻度图 -->
            <div class="tank" :title="p.warning.mode === 'fixed'
                   ? `资金预警线 ${wan(p.warning.amount)}（手动设定的最低安全余额）`
                   : `资金预警线 ${wan(p.warning.amount)}（未来${p.config.warning_days}天刚性待付推算）`">
              <div class="tank-glass"></div>
              <div class="tank-water" :class="`w-${p.warning.status}`" :style="`height:${fillPct(p)}%`">
                <i class="tank-wave"></i><i class="tank-wave wave2"></i>
              </div>
              <i v-if="parseFloat(p.warning.amount) > 0" class="tank-warnline"><b>预警</b></i>
            </div>

            <div class="cpc-nums">
              <div class="cpc-balance" :class="{ neg: parseFloat(p.balance) < 0 }">{{ wan(p.balance) }}</div>
              <div v-if="parseFloat(p.balance) < 0" class="cpc-negtip">账面余额为负——请核对期初基准与收支流水是否完整</div>
              <div class="cpc-warn">资金预警线 {{ wan(p.warning.amount) }}
                <em>· {{ p.warning.mode === 'fixed' ? '手动设定' : p.config.warning_days + '天刚性待付' }}</em></div>
              <!-- 余额预测走势 -->
              <svg class="cpc-spark" :viewBox="`0 0 ${spark(p).W} ${spark(p).H}`" :style="`width:${spark(p).W}px;height:${spark(p).H}px`">
                <line v-if="spark(p).zero != null" x1="6" :y1="spark(p).zero" :x2="spark(p).W - 4" :y2="spark(p).zero"
                      stroke="#c62828" stroke-width="1" stroke-dasharray="3,3" opacity=".6" />
                <path :d="spark(p).area" :fill="spark(p).danger ? 'rgba(198,40,40,.10)' : 'rgba(21,101,192,.10)'" />
                <path :d="spark(p).line" fill="none" :stroke="spark(p).danger ? '#c62828' : '#1565c0'" stroke-width="2" stroke-linecap="round" />
                <circle v-for="(pt, i) in spark(p).pts" :key="i" :cx="pt[0]" :cy="pt[1]" r="2.6"
                        :fill="spark(p).danger ? '#c62828' : '#1565c0'" />
              </svg>
              <div class="cpc-spark-labels"><i>现在</i><i>+30</i><i>+60</i><i :title="pessimistic ? '30天为审慎口径（含在途支出）' : ''">+90</i></div>
            </div>
          </div>

          <!-- 健康指标条（固定三格，缺数据显示 — 保持排版稳定） -->
          <div v-if="!p.error" class="cpc-vitals">
            <div class="vital" title="按近90天日均流出，现有余额可支撑的天数（近90天无流出时为 ∞）">
              <b>{{ p.health.runway_days != null ? p.health.runway_days + '天' : '∞' }}</b><i>余额支撑</i>
            </div>
            <div class="vital" title="近90天 流入/流出（>100% 为净流入部门）"
                 :class="p.health.self_rate == null ? '' : (p.health.self_rate >= 100 ? 'good' : 'bad')">
              <b>{{ p.health.self_rate != null ? p.health.self_rate + '%' : '—' }}</b><i>自给率</i>
            </div>
            <div class="vital" :title="`+30天预测余额${pessimistic ? '（审慎口径）' : ''}`"
                 :class="parseFloat(projVal(p, 'd30')) >= 0 ? 'good' : 'bad'">
              <b>{{ wan(projVal(p, 'd30')) }}</b><i>+30天余额</i>
            </div>
          </div>

          <button v-if="!p.error" class="cpc-expand" @click="expandedDept = expandedDept === p.dept ? '' : p.dept">
            {{ expandedDept === p.dept ? '收起明细 ▲' : '收支构成明细 ▼' }}
          </button>
          <Transition v-if="!p.error" name="cpd">
            <div v-if="expandedDept === p.dept" class="cpc-detail">
              <div class="cpd-row"><i>期初（{{ p.config.initial_date }}）</i><b>{{ wan(p.parts.initial) }}</b></div>
              <div class="cpd-row in"><i>＋ 回款</i><b>{{ wan(p.parts.collected) }}</b></div>
              <div class="cpd-row in"><i>＋ 预收款</i><b>{{ wan(p.parts.advance_received) }}</b></div>
              <div class="cpd-row out"><i>− 实付（已扣预付冲抵）</i><b>{{ wan(p.parts.paid) }}</b></div>
              <div class="cpd-row out"><i>− 预付款</i><b>{{ wan(p.parts.advance_paid) }}</b></div>
              <div class="cpd-row" v-if="parseFloat(p.parts.transfer_in) || parseFloat(p.parts.transfer_out)">
                <i>± 调拨（已生效）</i><b>+{{ wan(p.parts.transfer_in) }} / −{{ wan(p.parts.transfer_out) }}</b></div>
              <div class="cpd-sep"></div>
              <div class="cpd-row out"><i>刚性待付：已到期</i><b style="color:#c62828">{{ wan(p.committed.overdue) }}</b></div>
              <div class="cpd-row out"><i>刚性待付：30/60/90天</i><b>{{ wan(p.committed.d30) }} / {{ wan(p.committed.d60) }} / {{ wan(p.committed.d90) }}</b></div>
              <div class="cpd-row"><i>在途支出：已批待排 / 审批中</i><b>{{ wan(p.pipeline.approved) }} / {{ wan(p.pipeline.pending) }}</b></div>
              <div class="cpd-row out" v-if="parseFloat(p.pipeline.transfer_out_pending)">
                <i>待批调拨出款申请</i><b style="color:#e65100">{{ wan(p.pipeline.transfer_out_pending) }}</b></div>
              <div class="cpd-row in"><i>预期回款：30/60/90天</i><b>{{ wan(p.expected_in.d30) }} / {{ wan(p.expected_in.d60) }} / {{ wan(p.expected_in.d90) }}</b></div>
              <div class="cpd-row"><i>逾期应收在外（催回即流入）</i><b style="color:#e65100">{{ wan(p.expected_in.overdue_outstanding) }}</b></div>
            </div>
          </Transition>
        </div>

        <!-- 未配置的池 -->
        <div v-for="p in unconfigured" :key="p.dept" class="cp-card st-none">
          <div class="cpc-dept">{{ p.dept }}</div>
          <div class="cpc-unconfigured">
            未配置期初基准，暂无法核算余额
            <button v-if="auth.isSuperAdmin" class="cp-btn" style="margin-top:8px" @click="openConfig">配置期初基准</button>
          </div>
        </div>
      </div>

      <!-- ══ 调拨表单 + 台账 ══ -->
      <div v-if="showTransfer && (auth.isSuperAdmin || canRequestTransfer)" class="cp-transfer-form">
        <select v-model="trForm.from_dept" class="cp-sel"><option value="">调出方</option>
          <option v-for="p in configured" :key="p.dept" :value="p.dept">{{ p.dept }}（{{ wan(p.balance) }}）</option></select>
        <span class="tr-arrow">→</span>
        <select v-model="trForm.to_dept" class="cp-sel"><option value="">调入方</option>
          <option v-for="p in configured" :key="p.dept" :value="p.dept">{{ p.dept }}</option></select>
        <input v-model="trForm.amount" type="number" min="0" placeholder="金额(元)" class="cp-inp" style="width:120px" />
        <input v-if="auth.isSuperAdmin" v-model="trForm.transfer_date" type="date" class="cp-inp" title="调拨日期（实际发生日）" />
        <input v-model="trForm.expected_return_date" type="date" class="cp-inp" title="约定归还日（可选）" />
        <input v-model="trForm.notes" placeholder="备注（如：拆借月息0.3%）" class="cp-inp" style="flex:1" />
        <button class="cp-btn primary" :disabled="trSaving" @click="saveTransfer">
          {{ trSaving ? '提交中…' : (auth.isSuperAdmin ? '确认调拨' : '提交申请') }}</button>
        <div v-if="!auth.isSuperAdmin" class="tr-hint">申请须经调出方事业部（或超管）审批后生效；生效日以审批日为准</div>
      </div>

      <div v-if="transfers.length" class="card cp-tr-card">
        <div class="section-title" style="margin-bottom:8px">⇄ 池间调拨台账（内部拆借）</div>
        <div class="tr-list">
          <div v-for="t in transfers" :key="t.id" class="tr-item" :class="`trs-${t.status}`">
            <span class="tr-date">{{ t.transfer_date }}</span>
            <span class="tr-status" :class="`ts-${t.status}`">{{ trStatusLabel[t.status] || t.status }}</span>
            <span class="tr-route"><b>{{ t.from_dept.replace('事业部','') }}</b><i class="tr-pipe">— {{ wan(t.amount) }} →</i><b>{{ t.to_dept.replace('事业部','') }}</b></span>
            <span class="tr-meta">
              <em v-if="t.expected_return_date">约定归还 {{ t.expected_return_date }}</em>
              <em v-if="t.notes">{{ t.notes }}</em>
              <em v-if="t.created_by_name">申请 {{ t.created_by_name }}</em>
              <em v-if="t.reviewed_by_name">审批 {{ t.reviewed_by_name }}</em>
              <em v-if="t.status === 'rejected' && t.review_notes" class="tr-reject">拒因：{{ t.review_notes }}</em>
            </span>
            <template v-if="canReview(t)">
              <button class="cp-ok" @click="approveTransfer(t)">批准</button>
              <button class="cp-del" @click="rejectTransfer(t)">拒绝</button>
            </template>
            <button v-if="canCancel(t) && !canReview(t)" class="cp-del" @click="removeTransfer(t)">撤回</button>
            <button v-else-if="auth.isSuperAdmin && t.status !== 'pending'" class="cp-del" @click="removeTransfer(t)">删</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 池配置弹窗（超管） -->
    <div v-if="showConfig" class="cp-modal-mask" @click.self="showConfig = false">
      <div class="cp-modal">
        <div class="cp-modal-title">池配置 — 期初基准（该日终账面资金；之后按收支流水推算余额）</div>
        <table class="cp-table">
          <thead><tr><th>事业部</th><th>期初基准日</th><th>期初金额(元)</th>
            <th title="手动设定的最低安全余额；留空则按预警窗口天数的刚性待付动态推算">资金预警线(元,可选)</th>
            <th title="未设固定预警线时：预警线 = 未来N天刚性待付">预警窗口(天)</th><th></th></tr></thead>
          <tbody>
            <tr v-for="row in cfgRows" :key="row.delivery_dept">
              <td><b>{{ row.delivery_dept }}</b> <span v-if="row.saved" style="color:#2e7d32">✓</span></td>
              <td><input v-model="row.initial_date" type="date" class="cp-inp" /></td>
              <td><input v-model="row.initial_amount" type="number" class="cp-inp" style="width:120px" /></td>
              <td><input v-model="row.warning_amount" type="number" min="0" placeholder="留空=按天数推算" class="cp-inp" style="width:130px" /></td>
              <td><input v-model.number="row.warning_days" type="number" min="7" max="120" class="cp-inp" style="width:64px" /></td>
              <td><button class="cp-btn primary" :disabled="cfgSaving" @click="saveCfgRow(row)">保存</button></td>
            </tr>
          </tbody>
        </table>
        <div class="cp-cfg-note">修改已有池子的期初基准日/期初金额，会重算该池自基准日以来的全部历史余额。</div>
        <div style="text-align:right;margin-top:10px"><button class="cp-btn" @click="showConfig = false">关闭</button></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cp-panel { padding: 16px 0; }
.cp-empty { text-align: center; padding: 40px; color: #9e9e9e; }
.cp-empty.err { color: #c62828; }

/* ══ 深水总览横幅 ══ */
.cp-hero { position: relative; border-radius: 16px; overflow: hidden; margin-bottom: 16px;
  background: linear-gradient(160deg, #0a2540 0%, #0e3a5c 45%, #14507a 100%);
  box-shadow: 0 8px 28px rgba(10,37,64,.28); }
.hero-waves { position: absolute; inset: 0; pointer-events: none; opacity: .5; }
.hw { position: absolute; left: 0; width: 300%; height: 90px; bottom: -34px;
  background: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 40" preserveAspectRatio="none"><path d="M0 22 Q 30 10 60 22 T 120 22 T 180 22 T 240 22 V40 H0 Z" fill="%23ffffff" opacity="0.06"/></svg>') repeat-x;
  background-size: 240px 40px; animation: heroDrift 16s linear infinite; }
.hw2 { bottom: -22px; opacity: .8; animation-duration: 9s; animation-direction: reverse; }
@keyframes heroDrift { to { transform: translateX(-240px); } }

.hero-main { position: relative; display: flex; align-items: center; gap: 26px; padding: 18px 22px 12px; flex-wrap: wrap; }
.hero-title { font-size: 17px; font-weight: 800; color: #eaf6ff; }
.hero-sub { display: block; font-size: 11px; font-weight: 400; color: #8fb8d9; margin-top: 3px; }
.hero-balance { display: flex; flex-direction: column; }
.hb-num { font-size: 34px; font-weight: 800; color: #fff; letter-spacing: .5px; line-height: 1.05;
  text-shadow: 0 2px 14px rgba(79,195,247,.35); font-variant-numeric: tabular-nums; }
.hb-label { font-size: 11px; color: #8fb8d9; margin-top: 2px; }
.hero-flow { display: flex; gap: 20px; align-items: flex-end; }
.hf-step { text-align: center; }
.hf-val { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
.hf-step.pipe .hf-val { color: #ffd54f; font-size: 14px; }
.hf-step.pipe em { font-style: normal; color: #b8cfe0; font-size: 12px; }
.hf-k { font-size: 10.5px; color: #8fb8d9; margin-top: 2px; }
.hero-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.hero-alert i { font-style: normal; font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 10px; margin-left: 6px; }
.ha-danger { background: rgba(255,82,82,.18); color: #ff8a80; animation: pulse 1.6s ease-in-out infinite; }
.ha-warn { background: rgba(255,183,77,.15); color: #ffd54f; }
@keyframes pulse { 50% { box-shadow: 0 0 0 5px rgba(255,82,82,.12); } }
.hero-pess { font-size: 12px; color: #b8cfe0; display: flex; align-items: center; gap: 5px; cursor: pointer; }
.hero-btn { padding: 6px 14px; border: 1px solid rgba(143,184,217,.45); border-radius: 9px;
  background: rgba(255,255,255,.07); font-size: 12.5px; color: #eaf6ff; cursor: pointer; backdrop-filter: blur(4px); }
.hero-btn:hover { background: rgba(255,255,255,.16); }

/* 连通水域 */
.reservoir { position: relative; display: flex; align-items: flex-end; justify-content: space-around;
  gap: 10px; padding: 8px 26px 0; height: 168px;
  border-top: 1px solid rgba(143,184,217,.18); }
.rsv-col { display: flex; flex-direction: column; align-items: center; justify-content: flex-end;
  height: 100%; flex: 1; max-width: 120px; cursor: pointer; }
.rsv-amt { font-size: 12px; font-weight: 700; color: #cfe8ff; margin-bottom: 4px; font-variant-numeric: tabular-nums; }
.rsv-tube { position: relative; width: 100%; max-width: 74px; height: 100px;
  border: 1.5px solid rgba(143,184,217,.35); border-bottom: none; border-radius: 10px 10px 0 0;
  background: rgba(255,255,255,.04); overflow: hidden; }
.rsv-water { position: absolute; bottom: 0; left: 0; right: 0; transition: height .7s cubic-bezier(.2,.8,.3,1); }
.rsv-wave, .tank-wave { position: absolute; top: -7px; left: 0; width: 200%; height: 8px;
  background: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 8" preserveAspectRatio="none"><path d="M0 4 Q 15 0 30 4 T 60 4 V8 H0 Z" fill="%23ffffff" opacity="0.55"/></svg>') repeat-x;
  background-size: 60px 8px; animation: heroDrift 5s linear infinite; }
.rsv-warntick { position: absolute; left: 0; right: 0; border-top: 2px dashed rgba(255,138,128,.85); }
.rsv-name { margin: 6px 0 10px; font-size: 12px; font-weight: 600; color: #b8cfe0; }
.rsv-col:hover .rsv-tube { border-color: rgba(79,195,247,.8); }
.t-danger { color: #ff8a80; } .t-warn { color: #ffd54f; }
.w-ok { background: linear-gradient(180deg, #4fc3f7 0%, #1565c0 90%); }
.w-warn { background: linear-gradient(180deg, #ffb74d 0%, #e65100 90%); }
.w-danger { background: linear-gradient(180deg, #e57373 0%, #b71c1c 90%); }

/* ══ 池子卡片 ══ */
.cp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px; }
.cp-card { background: #fff; border: 1.5px solid #e8ddd0; border-radius: 14px; padding: 16px;
  box-shadow: 0 2px 10px rgba(74,55,40,.05); transition: box-shadow .2s, transform .2s; }
.cp-card:hover { box-shadow: 0 6px 18px rgba(74,55,40,.10); transform: translateY(-1px); }
.cp-card.st-danger { border-color: rgba(198,40,40,.55); background: linear-gradient(180deg, rgba(198,40,40,.035), #fff 40%); }
.cp-card.st-warn { border-color: rgba(230,81,0,.5); }
.cp-card.st-none { border-style: dashed; box-shadow: none; background: #fdfbf8; }
.cpc-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.cpc-dept { font-size: 14.5px; font-weight: 700; color: #4a3728; }
.cpc-badge { font-size: 11px; font-weight: 700; padding: 3px 11px; border-radius: 10px; }
.bg-ok { background: rgba(46,125,50,.12); color: #2e7d32; }
.bg-warn { background: rgba(230,81,0,.12); color: #e65100; }
.bg-danger { background: rgba(198,40,40,.14); color: #c62828; animation: pulse 1.6s ease-in-out infinite; }

.cpc-body { display: flex; gap: 16px; align-items: stretch; }
.tank { position: relative; width: 76px; min-height: 128px; border-radius: 10px 10px 14px 14px;
  background: linear-gradient(180deg, #f4f9fd, #e9f2f9); overflow: hidden; flex-shrink: 0;
  border: 2px solid #cfe0ee; }
.tank-glass { position: absolute; inset: 0; pointer-events: none; z-index: 3;
  background: linear-gradient(105deg, rgba(255,255,255,.38) 5%, transparent 14%, transparent 80%, rgba(255,255,255,.18) 94%); }
.tank-water { position: absolute; bottom: 0; left: 0; right: 0; transition: height .8s cubic-bezier(.2,.8,.3,1); z-index: 1; }
.tank-wave.wave2 { animation-duration: 8s; animation-direction: reverse; opacity: .5; top: -5px; }
.tank-warnline { position: absolute; bottom: 33.3%; left: 0; right: 0; z-index: 2;
  border-top: 2px dashed rgba(198,40,40,.8); }
.tank-warnline b { position: absolute; right: 1px; top: -7px; font-size: 9px; color: #c62828;
  font-weight: 700; background: rgba(255,255,255,.82); border-radius: 4px; padding: 0 3px; line-height: 13px; }

.cpc-nums { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 3px; min-width: 0; }
.cpc-balance { font-size: 26px; font-weight: 800; color: #2d2010; font-variant-numeric: tabular-nums; line-height: 1.1; }
.cpc-balance.neg { color: #c62828; }
.cpc-negtip { font-size: 10.5px; color: #c62828; background: rgba(198,40,40,.07); border-radius: 6px; padding: 2px 7px; }
.cpc-warn { font-size: 11px; color: #e65100; }
.cpc-warn em { font-style: normal; color: #9b8070; }
.cpc-spark { margin-top: 6px; display: block; }
.cpc-spark-labels { display: flex; justify-content: space-between; width: 158px; font-size: 9.5px; color: #9b8070; padding: 0 4px; }
.cpc-spark-labels i { font-style: normal; }

.cpc-vitals { display: flex; gap: 8px; margin-top: 12px; }
.vital { flex: 1; text-align: center; padding: 7px 4px; border-radius: 9px; background: #faf6f1; }
.vital b { display: block; font-size: 14.5px; font-weight: 800; color: #4a3728; font-variant-numeric: tabular-nums; }
.vital i { font-style: normal; font-size: 10px; color: #9b8070; }
.vital.good b { color: #2e7d32; } .vital.bad b { color: #c62828; }

.cpc-expand { margin-top: 10px; width: 100%; padding: 4px; border: none; background: none; font-size: 11.5px; color: #9b8070; cursor: pointer; }
.cpc-expand:hover { color: #4a3728; }
.cpc-detail { margin-top: 6px; border-top: 1px dashed #e8ddd0; padding-top: 8px; overflow: hidden; }
.cpd-enter-active { transition: all .25s ease; } .cpd-enter-from { opacity: 0; transform: translateY(-6px); }
.cpd-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2.5px 0; color: #6b5a4a; }
.cpd-row b { color: #2d2010; font-weight: 600; font-variant-numeric: tabular-nums; }
.cpd-row.in b { color: #2e7d32; }
.cpd-row.out b { color: #c62828; }
.cpd-sep { border-top: 1px dashed #e8ddd0; margin: 6px 0; }
.cpc-unconfigured { text-align: center; padding: 26px 0 30px; color: #9b8070; font-size: 13px; }
.dry { font-size: 30px; margin-bottom: 6px; opacity: .7; }

/* ══ 调拨 ══ */
.cp-btn { padding: 5px 12px; border: 1px solid #d4b896; border-radius: 7px; background: #faf8f5; font-size: 12.5px; color: #4a3728; cursor: pointer; }
.cp-btn:hover { border-color: #4a3728; }
.cp-btn.primary { background: #4a3728; color: #fff; border-color: #4a3728; }
.cp-transfer-form { display: flex; gap: 8px; align-items: center; margin-top: 14px; padding: 12px; background: #fef9f5; border: 1px solid #e8ddd0; border-radius: 10px; flex-wrap: wrap; }
.tr-arrow { font-weight: 700; color: #4a3728; }
.cp-sel, .cp-inp { padding: 6px 8px; border: 1px solid #d4b896; border-radius: 7px; font-size: 12.5px; background: #fff; }
.cp-tr-card { margin-top: 14px; padding: 14px; }
.tr-list { display: flex; flex-direction: column; gap: 6px; }
.tr-item { display: flex; align-items: center; gap: 14px; padding: 8px 12px; border-radius: 9px; background: #faf6f1; font-size: 12.5px; }
.tr-date { color: #9b8070; font-variant-numeric: tabular-nums; flex-shrink: 0; }
.tr-route { display: flex; align-items: center; gap: 8px; font-weight: 700; color: #4a3728; flex-shrink: 0; }
.tr-pipe { font-style: normal; font-weight: 600; font-size: 12px; color: #1565c0; background: rgba(21,101,192,.08); padding: 2px 10px; border-radius: 10px; }
.tr-meta { display: flex; gap: 12px; color: #9b8070; flex: 1; min-width: 0; flex-wrap: wrap; }
.tr-meta em { font-style: normal; }
.tr-meta .tr-reject { color: #c62828; }
.tr-status { font-style: normal; font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 9px; flex-shrink: 0; }
.ts-pending { background: rgba(230,81,0,.12); color: #e65100; }
.ts-approved { background: rgba(46,125,50,.12); color: #2e7d32; }
.ts-rejected { background: rgba(120,120,120,.13); color: #757575; }
.tr-item.trs-rejected .tr-route, .tr-item.trs-rejected .tr-pipe { opacity: .55; }
.tr-item.trs-pending { background: #fff8f0; border: 1px dashed rgba(230,81,0,.35); }
.tr-hint { width: 100%; font-size: 11px; color: #9b8070; }
.cp-ok { border: 1px solid rgba(46,125,50,.45); color: #2e7d32; background: none; border-radius: 6px; padding: 2px 8px; font-size: 11px; cursor: pointer; }
.cp-del { border: 1px solid rgba(198,40,40,.4); color: #c62828; background: none; border-radius: 6px; padding: 2px 8px; font-size: 11px; cursor: pointer; }
.cp-method { margin-bottom: 14px; padding: 12px 16px; }
.cp-method ul { margin: 0; padding-left: 18px; }
.cp-method li { font-size: 12px; color: #6b5a4a; line-height: 1.9; }
.cp-method li b { color: #4a3728; }
.cp-cfg-note { margin-top: 8px; font-size: 11px; color: #e65100; }

.cp-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.cp-table th { background: #f3ede6; color: #6b5a4a; padding: 7px 10px; font-weight: 600; text-align: left; white-space: nowrap; }
.cp-table td { padding: 7px 10px; border-bottom: 1px solid #f0e8de; }
.cp-modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.cp-modal { background: #fff; border-radius: 12px; padding: 18px; width: min(680px, 94vw); max-height: 84vh; overflow-y: auto; }
.cp-modal-title { font-size: 14px; font-weight: 700; color: #4a3728; margin-bottom: 12px; }

@media (max-width: 768px) {
  .hero-main { gap: 14px; }
  .hb-num { font-size: 26px; }
  .reservoir { padding: 8px 10px 0; height: 140px; }
}
</style>
