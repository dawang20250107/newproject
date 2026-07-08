<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useToast } from '../../composables/useToast.js'
import { confirmDlg } from '../../composables/confirm.js'
import { useAuthStore } from '../../stores/auth.js'
import { todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'

const toast = useToast()
const auth = useAuthStore()
const canWrite = computed(() => auth.canArWrite)
const money = v => '¥' + Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })

// ── 日期范围（全套快捷）───────────────────────────────────────────────────────
function ymd(d) { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10) }
function todayD() { return new Date(todayCST() + 'T00:00:00') }
const DATE_PRESETS = [
  { k: 'today', l: '今天' }, { k: 'yesterday', l: '昨天' },
  { k: 'thisweek', l: '本周' }, { k: 'lastweek', l: '上周' },
  { k: 'thismonth', l: '本月' }, { k: 'lastmonth', l: '上月' },
  { k: 'thisquarter', l: '本季度' }, { k: 'lastquarter', l: '上季度' },
  { k: 'halfyear', l: '近半年' }, { k: 'thisyear', l: '本年' },
  { k: 'lastyear', l: '去年' }, { k: 'year1', l: '近一年' },
  { k: 'd7', l: '近7天' }, { k: 'd30', l: '近30天' }, { k: 'd90', l: '近90天' },
]
function computePreset(k) {
  const t = todayD(), y = t.getFullYear(), m = t.getMonth(), d = t.getDate(), day = t.getDay()
  const monOff = day === 0 ? 6 : day - 1
  const back = n => { const x = new Date(t); x.setDate(d - n); return x }
  const mk = (a, b) => ({ start: ymd(a), end: ymd(b) })
  switch (k) {
    case 'today': return mk(t, t)
    case 'yesterday': { const yd = back(1); return mk(yd, yd) }
    case 'thisweek': { const mo = new Date(t); mo.setDate(d - monOff); return mk(mo, t) }
    case 'lastweek': { const mo = new Date(t); mo.setDate(d - monOff - 7); const su = new Date(mo); su.setDate(mo.getDate() + 6); return mk(mo, su) }
    case 'thismonth': return mk(new Date(y, m, 1), t)
    case 'lastmonth': return mk(new Date(y, m - 1, 1), new Date(y, m, 0))
    case 'thisquarter': return mk(new Date(y, Math.floor(m / 3) * 3, 1), t)
    case 'lastquarter': { const qm = Math.floor(m / 3) * 3 - 3; return mk(new Date(y, qm, 1), new Date(y, qm + 3, 0)) }
    case 'halfyear': return mk(back(182), t)
    case 'thisyear': return mk(new Date(y, 0, 1), t)
    case 'lastyear': return mk(new Date(y - 1, 0, 1), new Date(y - 1, 11, 31))
    case 'year1': return mk(back(365), t)
    case 'd7': return mk(back(6), t)
    case 'd30': return mk(back(29), t)
    case 'd90': return mk(back(89), t)
  }
  return mk(new Date(y, m, 1), t)
}
const activePreset = ref('thismonth')
let _applying = false
function applyPreset(k) {
  _applying = true
  const r = computePreset(k); filter.start = r.start; filter.end = r.end
  _applying = false
  activePreset.value = k
  load()
}

// ── 筛选 ────────────────────────────────────────────────────────────────────
const depts = ref([])
const sourcePresets = ref(['项目收款', '预付退款'])
const methodPresets = ref(['现金', '微信', '银行转账'])
const _init = computePreset('thismonth')
const filter = reactive({ dept: '', source: '', method: '', start: _init.start, end: _init.end, q: '' })
// 手动改日期 → 取消预设高亮（预设应用时 _applying 置真，跳过清除）；sync 保证在赋值当刻触发
watch([() => filter.start, () => filter.end], () => { if (!_applying) activePreset.value = '' }, { flush: 'sync' })

// ── 数据 ────────────────────────────────────────────────────────────────────
const loading = ref(false)
const items = ref([])
const total = ref('0')
const count = ref(0)
const byMethod = ref({})
const bySource = ref({})
const topMethods = computed(() => Object.entries(byMethod.value).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 3))
const avg = computed(() => count.value ? Number(total.value) / count.value : 0)

async function load() {
  loading.value = true
  try {
    const p = {
      start_date: filter.start, end_date: filter.end,
      source: filter.source || undefined, method: filter.method || undefined,
      q: filter.q || undefined, depts: filter.dept || undefined,
    }
    const d = (await ar.listDailyReceipts(p)).data || {}
    items.value = d.items || []
    total.value = d.total || '0'
    count.value = d.count || 0
    byMethod.value = d.by_method || {}
    bySource.value = d.by_source || {}
    if (d.departments?.length) depts.value = d.departments
    if (d.source_presets?.length) sourcePresets.value = d.source_presets
    if (d.method_presets?.length) methodPresets.value = d.method_presets
  } catch (e) { toast.error(e?.msg || e?.error || '加载失败') }
  finally { loading.value = false }
}
onMounted(load)
watch(() => [filter.source, filter.method, filter.dept], load)

// ── 新增 / 编辑弹窗 ──────────────────────────────────────────────────────────
const formOpen = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = reactive({
  delivery_dept: '', receipt_date: todayCST(), amount: '', source: '项目收款',
  project_id: '', method: '现金', account: '', payer: '', notes: '',
})
const isProjectSource = computed(() => form.source === '项目收款')
const projects = ref([])
async function loadProjects() {
  if (!form.delivery_dept) { projects.value = []; return }
  try {
    const d = (await ar.listProjects({ delivery_dept: form.delivery_dept, page_size: 500 })).data || {}
    projects.value = d.items || d.results || []
  } catch { projects.value = [] }
}
watch(() => form.delivery_dept, () => { if (isProjectSource.value) loadProjects() })
watch(() => form.source, v => { if (v === '项目收款') loadProjects(); else form.project_id = '' })

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    delivery_dept: filter.dept || depts.value[0] || '', receipt_date: todayCST(), amount: '',
    source: '项目收款', project_id: '', method: '现金', account: '', payer: '', notes: '',
  })
  formOpen.value = true
  if (isProjectSource.value) loadProjects()
}
function openEdit(r) {
  editingId.value = r.id
  Object.assign(form, {
    delivery_dept: r.delivery_dept, receipt_date: r.receipt_date, amount: r.amount,
    source: r.source, project_id: r.project_id || '', method: r.method, account: r.account,
    payer: r.payer, notes: r.notes,
  })
  formOpen.value = true
  if (isProjectSource.value) loadProjects()
}
async function save() {
  if (!form.delivery_dept) { toast.error('请选择事业部'); return }
  if (!(Number(form.amount) > 0)) { toast.error('金额必须大于 0'); return }
  if (!form.source.trim()) { toast.error('请填写收款来源'); return }
  saving.value = true
  try {
    const body = { ...form, project_id: isProjectSource.value ? (form.project_id || null) : null }
    if (editingId.value) await ar.updateDailyReceipt(editingId.value, body)
    else await ar.createDailyReceipt(body)
    toast.success('已保存'); formOpen.value = false; load()
  } catch (e) { toast.error(e?.msg || e?.error || '保存失败') }
  finally { saving.value = false }
}
async function remove(r) {
  if (!(await confirmDlg(`删除这笔收款「${r.source} · ${money(r.amount)}」？`))) return
  try { await ar.deleteDailyReceipt(r.id); toast.success('已删除'); load() }
  catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
}
function resetFilters() {
  filter.source = ''; filter.method = ''; filter.dept = ''; filter.q = ''
  applyPreset('thismonth')
}
</script>

<template>
  <div class="dr fh-fill">
    <!-- 标题 -->
    <header class="dr-head">
      <div>
        <h1>日常收款</h1>
        <p>项目收款 · 预付退款 · 其他来源，实时计入现金流与资金池</p>
      </div>
      <button v-if="canWrite" class="btn-hero" @click="openCreate"><span>＋</span> 新增收款</button>
    </header>

    <!-- KPI -->
    <div class="kpi-grid">
      <div class="kpi-card accent">
        <div class="label">区间合计收款</div>
        <div class="value">{{ money(total) }}</div>
        <div class="sub">{{ filter.start }} ~ {{ filter.end }}</div>
      </div>
      <div class="kpi-card">
        <div class="label">收款笔数</div>
        <div class="value">{{ count }}</div>
        <div class="sub">笔均 {{ fmtCompact(avg) }}</div>
      </div>
      <div class="kpi-card">
        <div class="label">按方式分布</div>
        <div class="mini-bars">
          <div v-for="[m, v] in topMethods" :key="m" class="mini-bar">
            <span class="mb-name">{{ m }}</span>
            <span class="mb-track"><i :style="{ width: (Number(total) ? Number(v) / Number(total) * 100 : 0) + '%' }"></i></span>
            <span class="mb-val">{{ fmtCompact(v) }}</span>
          </div>
          <div v-if="!topMethods.length" class="mb-empty">暂无数据</div>
        </div>
      </div>
    </div>

    <!-- 筛选卡 -->
    <div class="filter-card card">
      <div class="fc-row dates">
        <span class="fc-lbl">时间</span>
        <div class="preset-chips">
          <button v-for="p in DATE_PRESETS" :key="p.k" class="pchip" :class="{ on: activePreset === p.k }" @click="applyPreset(p.k)">{{ p.l }}</button>
        </div>
        <div class="date-inputs">
          <input v-model="filter.start" type="date" class="inp inp-date" @change="load" />
          <span class="tilde">~</span>
          <input v-model="filter.end" type="date" class="inp inp-date" @change="load" />
        </div>
      </div>
      <div class="fc-row">
        <span class="fc-lbl">事业部</span>
        <div class="seg">
          <button :class="{ on: !filter.dept }" @click="filter.dept = ''">全部</button>
          <button v-for="d in depts" :key="d" :class="{ on: filter.dept === d }" @click="filter.dept = d">{{ d }}</button>
        </div>
      </div>
      <div class="fc-row">
        <span class="fc-lbl">来源</span>
        <div class="seg soft">
          <button :class="{ on: !filter.source }" @click="filter.source = ''">全部</button>
          <button v-for="s in Object.keys(bySource)" :key="s" :class="{ on: filter.source === s }" @click="filter.source = s">{{ s }}</button>
        </div>
        <span class="fc-lbl mid">方式</span>
        <div class="seg soft">
          <button :class="{ on: !filter.method }" @click="filter.method = ''">全部</button>
          <button v-for="m in Object.keys(byMethod)" :key="m" :class="{ on: filter.method === m }" @click="filter.method = m">{{ m }}</button>
        </div>
        <span class="grow"></span>
        <input v-model="filter.q" class="inp search" placeholder="搜付款方 / 摘要 / 项目" @keyup.enter="load" />
        <button class="btn ghost" @click="resetFilters">重置</button>
      </div>
    </div>

    <!-- 台账 -->
    <div class="ledger card">
      <div v-if="loading" class="empty">⏳ 加载中…</div>
      <div v-else-if="!items.length" class="empty">
        <div class="empty-i">💰</div>
        <div class="empty-t">此区间暂无收款记录</div>
        <div v-if="canWrite" class="empty-s">点右上「新增收款」录入第一笔。</div>
      </div>
      <div v-else class="tablewrap">
        <table>
          <thead>
            <tr><th>收款日期</th><th>事业部</th><th>来源</th><th>项目</th><th>方式</th><th>账户</th><th>付款方</th><th class="r">金额</th><th>摘要</th><th v-if="canWrite" class="ac"></th></tr>
          </thead>
          <tbody>
            <tr v-for="r in items" :key="r.id">
              <td class="when">{{ r.receipt_date }}</td>
              <td>{{ r.delivery_dept }}</td>
              <td><span class="src">{{ r.source }}</span></td>
              <td class="proj">{{ r.project_name || '—' }}</td>
              <td><span v-if="r.method" class="mtd">{{ r.method }}</span><span v-else>—</span></td>
              <td class="dim">{{ r.account || '—' }}</td>
              <td>{{ r.payer || '—' }}</td>
              <td class="r amt">{{ money(r.amount) }}</td>
              <td class="sumcell" :title="r.notes">{{ r.notes || '—' }}</td>
              <td v-if="canWrite" class="ops">
                <button class="op" @click="openEdit(r)">编辑</button>
                <button class="op del" @click="remove(r)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 新增/编辑弹窗 -->
    <Teleport to="body">
      <div v-if="formOpen" class="scrim" @click.self="formOpen = false">
        <div class="dlg">
          <div class="d-head"><h3>{{ editingId ? '编辑收款' : '新增收款' }}</h3><button class="d-x" @click="formOpen = false">✕</button></div>
          <div class="d-body">
            <div class="grid2">
              <div class="frow">
                <label>事业部 <i>*</i></label>
                <select v-model="form.delivery_dept" class="inp"><option value="" disabled>请选择</option><option v-for="d in depts" :key="d" :value="d">{{ d }}</option></select>
              </div>
              <div class="frow">
                <label>收款日期 <i>*</i></label>
                <input v-model="form.receipt_date" type="date" class="inp" />
              </div>
            </div>
            <div class="frow">
              <label>收款来源 <i>*</i></label>
              <div class="seg-wrap">
                <button v-for="s in sourcePresets" :key="s" class="preset" :class="{ on: form.source === s }" @click="form.source = s">{{ s }}</button>
                <input v-model="form.source" class="inp custom" placeholder="或自定义来源" />
              </div>
            </div>
            <div v-if="isProjectSource" class="frow">
              <label>关联项目</label>
              <select v-model="form.project_id" class="inp">
                <option value="">（不关联）</option>
                <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.short_name || p.customer_name }}</option>
              </select>
            </div>
            <div class="frow">
              <label>收款方式</label>
              <div class="seg-wrap">
                <button v-for="m in methodPresets" :key="m" class="preset" :class="{ on: form.method === m }" @click="form.method = m">{{ m }}</button>
                <input v-model="form.method" class="inp custom" placeholder="或自定义方式" />
              </div>
            </div>
            <div class="grid2">
              <div class="frow">
                <label>收款金额 <i>*</i></label>
                <input v-model="form.amount" type="number" step="0.01" class="inp big-amt" placeholder="0.00" />
              </div>
              <div class="frow">
                <label>收款账户</label>
                <input v-model="form.account" class="inp" placeholder="如 微信-结算001" />
              </div>
            </div>
            <div class="frow">
              <label>付款方</label>
              <input v-model="form.payer" class="inp" placeholder="选填" />
            </div>
            <div class="frow">
              <label>摘要/备注</label>
              <textarea v-model="form.notes" class="inp" rows="2" placeholder="选填"></textarea>
            </div>
          </div>
          <div class="d-foot">
            <button class="btn ghost" @click="formOpen = false">取消</button>
            <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存收款' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dr { display: flex; flex-direction: column; min-height: 0; gap: 18px; padding: 22px 26px; overflow: auto; }
/* 标题 */
.dr-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.dr-head h1 { margin: 0; font-size: 25px; font-weight: 850; letter-spacing: -.02em; color: var(--text, #4a3322); }
.dr-head p { margin: 6px 0 0; font-size: 13px; color: var(--muted, #9b8070); }
.btn-hero { border: none; background: linear-gradient(135deg, var(--primary, #1565c0), color-mix(in srgb, var(--primary, #1565c0) 78%, #000)); color: #fff; border-radius: 12px; padding: 11px 22px; font-size: 14.5px; font-weight: 750; cursor: pointer; font-family: inherit; box-shadow: 0 8px 22px -8px color-mix(in srgb, var(--primary, #1565c0) 60%, transparent); display: inline-flex; align-items: center; gap: 8px; transition: transform .16s; }
.btn-hero:hover { transform: translateY(-2px); }
.btn-hero span { font-size: 18px; }
/* KPI */
.kpi-grid { margin-bottom: 0; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.kpi-card.accent { background: linear-gradient(135deg, color-mix(in srgb, var(--primary, #1565c0) 12%, var(--glass, #fff)), var(--glass, #fff)); }
.kpi-card.accent .value { font-size: 30px; }
.mini-bars { display: flex; flex-direction: column; gap: 7px; margin-top: 4px; }
.mini-bar { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.mb-name { width: 46px; color: var(--text, #4a3322); font-weight: 650; flex: none; }
.mb-track { flex: 1; height: 7px; border-radius: 4px; background: var(--surface-2, rgba(160,120,80,.14)); overflow: hidden; }
.mb-track i { display: block; height: 100%; border-radius: 4px; background: var(--primary, #1565c0); }
.mb-val { width: 52px; text-align: right; color: var(--muted, #9b8070); flex: none; }
.mb-empty { font-size: 12px; color: var(--muted, #9b8070); }
/* 筛选卡 */
.filter-card { padding: 14px 18px; display: flex; flex-direction: column; gap: 12px; }
.fc-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.fc-lbl { font-size: 11.5px; font-weight: 750; letter-spacing: .05em; color: var(--muted, #9b8070); text-transform: uppercase; flex: none; }
.fc-lbl.mid { margin-left: 12px; }
.preset-chips { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }
.pchip { border: 1px solid var(--border, #e2d6c6); background: var(--card-bg, #fff); color: var(--text, #6a5641); border-radius: 20px; padding: 5px 13px; font-size: 12.5px; cursor: pointer; font-family: inherit; transition: .14s; }
.pchip:hover { border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); }
.pchip.on { background: var(--primary, #1565c0); border-color: var(--primary, #1565c0); color: #fff; font-weight: 650; box-shadow: 0 4px 12px -4px color-mix(in srgb, var(--primary, #1565c0) 55%, transparent); }
.date-inputs { display: flex; align-items: center; gap: 7px; }
.tilde { color: var(--muted, #9b8070); }
.inp { border: 1px solid var(--border, #d8c9b8); border-radius: 9px; padding: 7px 11px; font-size: 13px; font-family: inherit; background: var(--card-bg, #fff); color: var(--text, #4a3322); outline: none; transition: .14s; }
.inp:focus { border-color: var(--primary, #1565c0); box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary, #1565c0) 14%, transparent); }
.inp-date { width: 144px; } .search { width: 190px; }
.seg { display: inline-flex; background: var(--surface-2, rgba(160,120,80,.09)); border-radius: 10px; padding: 3px; gap: 2px; flex-wrap: wrap; }
.seg button { border: none; background: none; padding: 6px 13px; border-radius: 8px; font-size: 13px; font-weight: 600; color: var(--muted, #9b8070); cursor: pointer; font-family: inherit; }
.seg button.on { background: var(--card-bg, #fff); color: var(--primary, #1565c0); box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.seg.soft button.on { background: var(--primary-weak, #e8f1fb); }
.btn { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--text, #4a3322); border-radius: 9px; padding: 7px 15px; font-size: 13px; font-weight: 650; cursor: pointer; font-family: inherit; }
.btn.ghost { background: none; }
.btn.primary { background: var(--primary, #1565c0); color: #fff; border-color: var(--primary, #1565c0); }
.btn:disabled { opacity: .6; cursor: default; }
.grow { flex: 1; }
/* 台账 */
.ledger { flex: 1; min-height: 220px; padding: 0; overflow: hidden; display: flex; flex-direction: column; }
.empty { padding: 60px 20px; text-align: center; color: var(--muted, #9b8070); }
.empty-i { font-size: 42px; } .empty-t { font-size: 16px; font-weight: 700; color: var(--text, #4a3322); margin-top: 8px; } .empty-s { margin-top: 6px; font-size: 13px; }
.tablewrap { overflow: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
thead th { text-align: left; padding: 12px 14px; font-size: 11px; font-weight: 750; letter-spacing: .04em; text-transform: uppercase; color: var(--muted, #9b8070); background: var(--surface-2, rgba(160,120,80,.06)); white-space: nowrap; position: sticky; top: 0; z-index: 1; }
thead th.r, td.r { text-align: right; } th.ac { width: 120px; }
tbody td { padding: 11px 14px; border-top: 1px solid var(--border, #eadfd2); white-space: nowrap; }
tbody tr:nth-child(even) { background: color-mix(in srgb, var(--muted, #9b8070) 3.5%, transparent); }
tbody tr:hover { background: var(--surface-2, rgba(160,120,80,.09)); }
.amt { font-variant-numeric: tabular-nums; font-weight: 800; color: var(--primary, #1565c0); }
.src { background: var(--primary-weak, #e8f1fb); color: var(--primary, #1565c0); border-radius: 8px; padding: 2px 9px; font-size: 12px; font-weight: 600; }
.mtd { background: var(--surface-2, rgba(160,120,80,.12)); color: var(--text, #6a5641); border-radius: 7px; padding: 1px 8px; font-size: 12px; }
.proj { color: var(--text, #4a3322); } .dim, .when { color: var(--muted, #7a6550); }
.sumcell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; color: var(--muted, #7a6550); }
.ops { white-space: nowrap; }
.op { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--primary, #1565c0); font-size: 12px; padding: 4px 10px; border-radius: 7px; cursor: pointer; font-family: inherit; margin-right: 5px; }
.op:hover { border-color: var(--primary, #1565c0); }
.op.del { color: var(--danger, #d64545); } .op.del:hover { border-color: var(--danger, #d64545); }
/* 弹窗 */
.scrim { position: fixed; inset: 0; background: rgba(30,20,10,.42); backdrop-filter: blur(2px); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 20px; }
.dlg { background: var(--card-bg, #fff); border-radius: 16px; width: min(540px, 96vw); max-height: 92vh; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 24px 70px rgba(0,0,0,.34); }
.d-head { position: relative; padding: 18px 22px; border-bottom: 1px solid var(--border, #eadfd2); background: linear-gradient(180deg, var(--primary-weak, #e8f1fb), transparent); }
.d-head h3 { margin: 0; font-size: 17px; font-weight: 800; color: var(--text, #4a3322); }
.d-x { position: absolute; right: 16px; top: 16px; border: none; background: none; font-size: 16px; color: var(--muted, #9b8070); cursor: pointer; }
.d-body { padding: 18px 22px; overflow-y: auto; display: flex; flex-direction: column; gap: 13px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 13px; }
.frow { display: flex; flex-direction: column; gap: 6px; }
.frow > label { font-size: 12px; font-weight: 650; color: var(--muted, #9b8070); } .frow label i { color: var(--danger, #d64545); font-style: normal; }
.frow .inp { width: 100%; box-sizing: border-box; }
.big-amt { font-size: 16px; font-weight: 700; }
.seg-wrap { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.preset { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--text, #4a3322); border-radius: 9px; padding: 7px 14px; font-size: 13px; cursor: pointer; font-family: inherit; }
.preset.on { background: var(--primary-weak, #e8f1fb); border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); font-weight: 650; }
.custom { min-width: 130px; flex: 1; }
.d-foot { padding: 14px 22px; border-top: 1px solid var(--border, #eadfd2); display: flex; justify-content: flex-end; gap: 10px; }
@media (max-width: 640px) { .grid2 { grid-template-columns: 1fr; } .dr { padding: 16px; } }
</style>
