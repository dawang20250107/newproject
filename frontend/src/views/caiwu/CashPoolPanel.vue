<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import ar from '../../api/ar.js'
import { useAuthStore } from '../../stores/auth.js'
import { todayCST } from '../../constants.js'

const auth = useAuthStore()
const data = ref(null)
const loading = ref(false)
const err = ref('')
const transfers = ref([])
const expandedDept = ref('')

// 悲观口径开关：已批待排的管道支出按30天内全部变刚性计入预判
const pessimistic = ref(false)

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
    const [res, trs] = await Promise.all([ar.cashPool(), ar.listPoolTransfers()])
    data.value = res.data
    transfers.value = trs.data.items
  } catch (e) { err.value = e?.msg || '加载失败' }
  finally { loading.value = false }
}

const pools = computed(() => data.value?.pools || [])
const configured = computed(() => pools.value.filter(p => p.configured))

// 水箱填充：以「警戒线×3」为满箱基准，警戒线天然落在 1/3 高度处
function fillPct(p) {
  const bal = parseFloat(p.balance)
  const warn = parseFloat(p.warning.amount)
  if (bal <= 0) return 0
  if (warn <= 0) return 100
  return Math.min(100, (bal / (warn * 3)) * 100)
}
function projVal(p, key) {
  if (key === 'd30' && pessimistic.value) return p.projection.d30_with_pipeline
  return p.projection[key]
}
const projColor = v => (parseFloat(v) < 0 ? '#c62828' : '#2e7d32')

// ── 池间调拨（超管）────────────────────────────────────────────────────────
const showTransfer = ref(false)
const trForm = reactive({ from_dept: '', to_dept: '', amount: '', transfer_date: todayCST(), expected_return_date: '', notes: '' })
const trSaving = ref(false)
async function saveTransfer() {
  if (!trForm.from_dept || !trForm.to_dept || !(parseFloat(trForm.amount) > 0)) { alert('调出/调入/金额必填'); return }
  trSaving.value = true
  try {
    await ar.createPoolTransfer({ ...trForm })
    showTransfer.value = false
    Object.assign(trForm, { from_dept: '', to_dept: '', amount: '', transfer_date: todayCST(), expected_return_date: '', notes: '' })
    await load()
  } catch (e) { alert(e?.msg || '调拨失败') }
  finally { trSaving.value = false }
}
async function removeTransfer(t) {
  if (!confirm(`删除调拨记录：${t.from_dept} → ${t.to_dept} ¥${t.amount}？两池水位将回退。`)) return
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
    saved: !!existing[d],
  }))
  showConfig.value = true
}
async function saveCfgRow(row) {
  if (!row.initial_date) { alert('期初基准日必填'); return }
  cfgSaving.value = true
  try {
    await ar.savePoolConfig({
      delivery_dept: row.delivery_dept, initial_date: row.initial_date,
      initial_amount: row.initial_amount || 0, warning_days: row.warning_days,
    })
    row.saved = true
    await load()
  } catch (e) { alert(e?.msg || '保存失败') }
  finally { cfgSaving.value = false }
}

onMounted(load)
</script>

<template>
  <div class="cp-panel">
    <div class="cp-head">
      <div class="cp-title">💧 资金池 · 事业部水位调度
        <span class="cp-sub">水位 = 期初 + 回款/预收 − 实付/预付 ± 调拨；预判含已审批待付（刚性）与在途审批（管道）</span>
      </div>
      <div class="cp-controls">
        <label class="cp-pess" title="勾选后：30天预判按「已批待排的审批在30天内全部付款」的悲观口径计算">
          <input type="checkbox" v-model="pessimistic" />悲观口径
        </label>
        <button v-if="auth.isSuperAdmin" class="cp-btn" @click="showTransfer = !showTransfer">⇄ 池间调拨</button>
        <button v-if="auth.isSuperAdmin" class="cp-btn" @click="openConfig">⚙ 池配置</button>
      </div>
    </div>

    <div v-if="loading && !data" class="cp-empty">加载中…</div>
    <div v-else-if="err" class="cp-empty err">{{ err }}</div>
    <template v-else-if="data">
      <!-- 集团总池 -->
      <div v-if="data.group" class="cp-group">
        <div class="cpg-item"><div class="cpg-k">集团总水位</div><div class="cpg-v">{{ wan(data.group.balance) }}</div></div>
        <div class="cpg-item"><div class="cpg-k">30天刚性警戒线</div><div class="cpg-v" style="color:#e65100">{{ wan(data.group.warning_amount) }}</div></div>
        <div class="cpg-item"><div class="cpg-k">+30天预测水位</div><div class="cpg-v" :style="`color:${projColor(data.group.projection_d30)}`">{{ wan(data.group.projection_d30) }}</div></div>
        <div class="cpg-item"><div class="cpg-k">+90天预测水位</div><div class="cpg-v" :style="`color:${projColor(data.group.projection_d90)}`">{{ wan(data.group.projection_d90) }}</div></div>
        <div class="cpg-item"><div class="cpg-k">在途审批（管道）</div><div class="cpg-v">{{ wan(data.group.pipeline_approved) }}<span class="cpg-mini">已批 / {{ wan(data.group.pipeline_pending) }}审批中</span></div></div>
        <div class="cpg-item" v-if="data.group.danger_count || data.group.warn_count">
          <div class="cpg-k">池健康</div>
          <div class="cpg-v"><span v-if="data.group.danger_count" style="color:#c62828">{{ data.group.danger_count }}池告急</span>
            <span v-if="data.group.warn_count" style="color:#e65100"> {{ data.group.warn_count }}池预警</span></div>
        </div>
      </div>

      <!-- 池子网格 -->
      <div class="cp-grid">
        <div v-for="p in pools" :key="p.dept" class="cp-card" :class="p.configured ? `st-${p.warning.status}` : 'st-none'">
          <template v-if="p.configured">
            <div class="cpc-top">
              <div class="cpc-dept">{{ p.dept }}</div>
              <span class="cpc-badge" :class="`bg-${p.warning.status}`">{{ statusLabel[p.warning.status] }}</span>
            </div>
            <div class="cpc-body">
              <!-- 水箱 -->
              <div class="tank" :title="`警戒线 ${wan(p.warning.amount)}（未来${p.config.warning_days}天刚性流出）`">
                <div class="tank-fill" :class="`fill-${p.warning.status}`" :style="`height:${fillPct(p)}%`"></div>
                <div class="tank-warnline" v-if="parseFloat(p.warning.amount) > 0"></div>
              </div>
              <div class="cpc-nums">
                <div class="cpc-balance">{{ wan(p.balance) }}</div>
                <div class="cpc-warn">警戒线 {{ wan(p.warning.amount) }}</div>
                <div class="cpc-proj">
                  <span v-for="k in ['d30','d60','d90']" :key="k" class="proj-chip"
                        :style="`color:${projColor(projVal(p, k))}`"
                        :title="k === 'd30' && pessimistic ? '悲观口径：含已批待排管道' : ''">
                    +{{ k.slice(1) }}天 {{ wan(projVal(p, k)) }}
                  </span>
                </div>
                <div class="cpc-health">
                  <span v-if="p.health.runway_days != null" :title="'按近90天日均流出，现水位可支撑的天数'">⏳ {{ p.health.runway_days }}天</span>
                  <span v-if="p.health.self_rate != null" :style="`color:${p.health.self_rate >= 100 ? '#2e7d32' : '#e65100'}`"
                        :title="'近90天 流入/流出'">自给 {{ p.health.self_rate }}%</span>
                </div>
              </div>
            </div>
            <button class="cpc-expand" @click="expandedDept = expandedDept === p.dept ? '' : p.dept">
              {{ expandedDept === p.dept ? '收起明细 ▲' : '进出水明细 ▼' }}
            </button>
            <div v-if="expandedDept === p.dept" class="cpc-detail">
              <div class="cpd-row"><i>期初（{{ p.config.initial_date }}）</i><b>{{ wan(p.parts.initial) }}</b></div>
              <div class="cpd-row in"><i>＋ 回款</i><b>{{ wan(p.parts.collected) }}</b></div>
              <div class="cpd-row in"><i>＋ 预收</i><b>{{ wan(p.parts.advance_received) }}</b></div>
              <div class="cpd-row out"><i>− 实付（已扣预付核销）</i><b>{{ wan(p.parts.paid) }}</b></div>
              <div class="cpd-row out"><i>− 预付</i><b>{{ wan(p.parts.advance_paid) }}</b></div>
              <div class="cpd-row" v-if="parseFloat(p.parts.transfer_in) || parseFloat(p.parts.transfer_out)">
                <i>± 调拨</i><b>+{{ wan(p.parts.transfer_in) }} / −{{ wan(p.parts.transfer_out) }}</b></div>
              <div class="cpd-sep"></div>
              <div class="cpd-row out"><i>刚性待付：已到期</i><b style="color:#c62828">{{ wan(p.committed.overdue) }}</b></div>
              <div class="cpd-row out"><i>刚性待付：30/60/90天</i><b>{{ wan(p.committed.d30) }} / {{ wan(p.committed.d60) }} / {{ wan(p.committed.d90) }}</b></div>
              <div class="cpd-row"><i>管道：已批待排 / 审批中</i><b>{{ wan(p.pipeline.approved) }} / {{ wan(p.pipeline.pending) }}</b></div>
              <div class="cpd-row in"><i>预期回款：30/60/90天</i><b>{{ wan(p.expected_in.d30) }} / {{ wan(p.expected_in.d60) }} / {{ wan(p.expected_in.d90) }}</b></div>
              <div class="cpd-row"><i>逾期在外（催回即进水）</i><b style="color:#e65100">{{ wan(p.expected_in.overdue_outstanding) }}</b></div>
            </div>
          </template>
          <template v-else>
            <div class="cpc-dept">{{ p.dept }}</div>
            <div class="cpc-unconfigured">未配置期初基准
              <button v-if="auth.isSuperAdmin" class="cp-btn" style="margin-top:8px" @click="openConfig">去配置</button>
            </div>
          </template>
        </div>
      </div>

      <!-- 调拨表单 + 流水 -->
      <div v-if="showTransfer && auth.isSuperAdmin" class="cp-transfer-form">
        <select v-model="trForm.from_dept" class="cp-sel"><option value="">调出池</option>
          <option v-for="p in configured" :key="p.dept" :value="p.dept">{{ p.dept }}（{{ wan(p.balance) }}）</option></select>
        <span class="tr-arrow">→</span>
        <select v-model="trForm.to_dept" class="cp-sel"><option value="">调入池</option>
          <option v-for="p in configured" :key="p.dept" :value="p.dept">{{ p.dept }}</option></select>
        <input v-model="trForm.amount" type="number" min="0" placeholder="金额" class="cp-inp" style="width:120px" />
        <input v-model="trForm.transfer_date" type="date" class="cp-inp" />
        <input v-model="trForm.expected_return_date" type="date" class="cp-inp" title="约定归还日（可选）" />
        <input v-model="trForm.notes" placeholder="备注（如：拆借月息0.3%）" class="cp-inp" style="flex:1" />
        <button class="cp-btn primary" :disabled="trSaving" @click="saveTransfer">{{ trSaving ? '调拨中…' : '确认调拨' }}</button>
      </div>

      <div v-if="transfers.length" class="card cp-tr-card">
        <div class="section-title" style="margin-bottom:8px">池间调拨流水（内部拆借台账）</div>
        <table class="cp-table">
          <thead><tr><th>日期</th><th>调出 → 调入</th><th class="amt">金额</th><th>约定归还</th><th>备注</th><th>经办</th><th v-if="auth.isSuperAdmin"></th></tr></thead>
          <tbody>
            <tr v-for="t in transfers" :key="t.id">
              <td>{{ t.transfer_date }}</td>
              <td><b>{{ t.from_dept }}</b> → <b>{{ t.to_dept }}</b></td>
              <td class="amt">{{ wan(t.amount) }}</td>
              <td>{{ t.expected_return_date || '—' }}</td>
              <td class="muted">{{ t.notes || '—' }}</td>
              <td class="muted">{{ t.created_by_name }}</td>
              <td v-if="auth.isSuperAdmin"><button class="cp-del" @click="removeTransfer(t)">删</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- 池配置弹窗（超管） -->
    <div v-if="showConfig" class="cp-modal-mask" @click.self="showConfig = false">
      <div class="cp-modal">
        <div class="cp-modal-title">池配置 — 期初基准（该日终账面资金；之后流水推算水位）</div>
        <table class="cp-table">
          <thead><tr><th>事业部</th><th>期初基准日</th><th>期初金额(元)</th><th>警戒窗口(天)</th><th></th></tr></thead>
          <tbody>
            <tr v-for="row in cfgRows" :key="row.delivery_dept">
              <td><b>{{ row.delivery_dept }}</b> <span v-if="row.saved" style="color:#2e7d32">✓</span></td>
              <td><input v-model="row.initial_date" type="date" class="cp-inp" /></td>
              <td><input v-model="row.initial_amount" type="number" class="cp-inp" style="width:140px" /></td>
              <td><input v-model.number="row.warning_days" type="number" min="7" max="120" class="cp-inp" style="width:70px" /></td>
              <td><button class="cp-btn primary" :disabled="cfgSaving" @click="saveCfgRow(row)">保存</button></td>
            </tr>
          </tbody>
        </table>
        <div style="text-align:right;margin-top:10px"><button class="cp-btn" @click="showConfig = false">关闭</button></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cp-panel { padding: 16px 0; }
.cp-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
.cp-title { font-size: 16px; font-weight: 700; color: #4a3728; }
.cp-sub { display: block; font-size: 11px; font-weight: 400; color: #9b8070; margin-top: 2px; }
.cp-controls { display: flex; align-items: center; gap: 8px; }
.cp-pess { font-size: 12px; color: #6b5a4a; display: flex; align-items: center; gap: 4px; cursor: pointer; }
.cp-btn { padding: 5px 12px; border: 1px solid #d4b896; border-radius: 7px; background: #faf8f5; font-size: 12.5px; color: #4a3728; cursor: pointer; }
.cp-btn:hover { border-color: #4a3728; }
.cp-btn.primary { background: #4a3728; color: #fff; border-color: #4a3728; }
.cp-empty { text-align: center; padding: 40px; color: #9e9e9e; }
.cp-empty.err { color: #c62828; }

.cp-group { display: flex; gap: 0; margin-bottom: 14px; background: #fef9f5; border: 1px solid #e8ddd0; border-radius: 10px; overflow: hidden; flex-wrap: wrap; }
.cpg-item { flex: 1; min-width: 140px; padding: 12px 16px; text-align: center; border-right: 1px solid #e8ddd0; }
.cpg-item:last-child { border-right: none; }
.cpg-k { font-size: 11px; color: #9b8070; margin-bottom: 4px; }
.cpg-v { font-size: 18px; font-weight: 700; color: #2d2010; }
.cpg-mini { display: block; font-size: 10px; font-weight: 400; color: #9b8070; }

.cp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 12px; }
.cp-card { background: #fff; border: 1.5px solid #e8ddd0; border-radius: 12px; padding: 14px; }
.cp-card.st-danger { border-color: rgba(198,40,40,.55); background: rgba(198,40,40,.025); }
.cp-card.st-warn { border-color: rgba(230,81,0,.5); }
.cp-card.st-none { border-style: dashed; }
.cpc-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.cpc-dept { font-size: 14px; font-weight: 700; color: #4a3728; }
.cpc-badge { font-size: 11px; font-weight: 700; padding: 2px 10px; border-radius: 10px; }
.bg-ok { background: rgba(46,125,50,.12); color: #2e7d32; }
.bg-warn { background: rgba(230,81,0,.12); color: #e65100; }
.bg-danger { background: rgba(198,40,40,.14); color: #c62828; }
.cpc-body { display: flex; gap: 14px; align-items: stretch; }
.tank { position: relative; width: 56px; min-height: 110px; border: 2px solid #d4b896; border-radius: 8px 8px 10px 10px; background: #faf8f5; overflow: hidden; flex-shrink: 0; }
.tank-fill { position: absolute; bottom: 0; left: 0; right: 0; transition: height .5s; }
.fill-ok { background: linear-gradient(180deg, #4fc3f7, #1565c0); }
.fill-warn { background: linear-gradient(180deg, #ffb74d, #e65100); }
.fill-danger { background: linear-gradient(180deg, #e57373, #c62828); }
.tank-warnline { position: absolute; bottom: 33.3%; left: 0; right: 0; border-top: 2px dashed #c62828; }
.cpc-nums { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 4px; min-width: 0; }
.cpc-balance { font-size: 22px; font-weight: 800; color: #2d2010; }
.cpc-warn { font-size: 11px; color: #e65100; }
.cpc-proj { display: flex; gap: 6px; flex-wrap: wrap; }
.proj-chip { font-size: 11px; font-weight: 700; background: rgba(0,0,0,.04); padding: 2px 7px; border-radius: 8px; }
.cpc-health { display: flex; gap: 10px; font-size: 11px; color: #6b5a4a; }
.cpc-expand { margin-top: 10px; width: 100%; padding: 4px; border: none; background: none; font-size: 11.5px; color: #9b8070; cursor: pointer; }
.cpc-expand:hover { color: #4a3728; }
.cpc-detail { margin-top: 6px; border-top: 1px dashed #e8ddd0; padding-top: 8px; }
.cpd-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2.5px 0; color: #6b5a4a; }
.cpd-row b { color: #2d2010; font-weight: 600; }
.cpd-row.in b { color: #2e7d32; }
.cpd-row.out b { color: #c62828; }
.cpd-sep { border-top: 1px dashed #e8ddd0; margin: 6px 0; }
.cpc-unconfigured { text-align: center; padding: 30px 0; color: #9b8070; font-size: 13px; }

.cp-transfer-form { display: flex; gap: 8px; align-items: center; margin-top: 14px; padding: 12px; background: #fef9f5; border: 1px solid #e8ddd0; border-radius: 10px; flex-wrap: wrap; }
.tr-arrow { font-weight: 700; color: #4a3728; }
.cp-sel, .cp-inp { padding: 6px 8px; border: 1px solid #d4b896; border-radius: 7px; font-size: 12.5px; background: #fff; }
.cp-tr-card { margin-top: 14px; padding: 14px; }
.cp-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.cp-table th { background: #f3ede6; color: #6b5a4a; padding: 7px 10px; font-weight: 600; text-align: left; white-space: nowrap; }
.cp-table td { padding: 7px 10px; border-bottom: 1px solid #f0e8de; }
.cp-table .amt { text-align: right; font-weight: 600; }
.cp-table .muted { color: #9b8070; }
.cp-del { border: 1px solid rgba(198,40,40,.4); color: #c62828; background: none; border-radius: 6px; padding: 2px 8px; font-size: 11px; cursor: pointer; }

.cp-modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.cp-modal { background: #fff; border-radius: 12px; padding: 18px; width: min(680px, 94vw); max-height: 84vh; overflow-y: auto; }
.cp-modal-title { font-size: 14px; font-weight: 700; color: #4a3728; margin-bottom: 12px; }
@media (max-width: 768px) { .cpg-item { flex: 0 0 50%; border-bottom: 1px solid #e8ddd0; } }
</style>
