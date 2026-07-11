<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useToast } from '../../composables/useToast.js'
import { confirmDlg } from '../../composables/confirm.js'
import { useAuthStore } from '../../stores/auth.js'
import { todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import ContextMenu from '../../components/ContextMenu.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { useShiftSelect } from '../../composables/useShiftSelect.js'
import { useEscClearSelection } from '../../composables/useEscClearSelection.js'
import { copyText, copyRowTSV } from '../../utils/clipboard.js'
import PillPicker from '../../components/PillPicker.vue'
import ProjectShortNamePicker from '../../components/ProjectShortNamePicker.vue'
import { downloadBlob } from '../../utils/download.js'
import Amt from '../../components/Amt.vue'
import { useModalEsc } from '../../composables/useModalEsc.js'

const toast = useToast()
const auth = useAuthStore()
const canWrite = computed(() => auth.canArWrite)
const money = v => '¥' + Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })

// ── 日期范围（全套快捷）───────────────────────────────────────────────────────
function ymd(d) { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10) }
function todayD() { return new Date(todayCST() + 'T00:00:00') }
const DATE_PRESETS = [
  { k: 'today', l: '今天' }, { k: 'yesterday', l: '昨天' }, { k: 'thisweek', l: '本周' }, { k: 'lastweek', l: '上周' },
  { k: 'thismonth', l: '本月' }, { k: 'lastmonth', l: '上月' }, { k: 'thisquarter', l: '本季度' }, { k: 'lastquarter', l: '上季度' },
  { k: 'halfyear', l: '近半年' }, { k: 'thisyear', l: '本年' }, { k: 'lastyear', l: '去年' }, { k: 'year1', l: '近一年' },
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
function applyPreset(k) { _applying = true; const r = computePreset(k); filter.start = r.start; filter.end = r.end; _applying = false; activePreset.value = k; load() }

// ── 筛选 ────────────────────────────────────────────────────────────────────
const depts = ref([])
const _init = computePreset('thismonth')
const filter = reactive({ dept: '', source: '', method: '', start: _init.start, end: _init.end, q: '' })
watch([() => filter.start, () => filter.end], () => { if (!_applying) activePreset.value = '' }, { flush: 'sync' })

// ── 数据 ────────────────────────────────────────────────────────────────────
const loading = ref(false)
const items = ref([])
const total = ref('0')
const count = ref(0)
const byMethod = ref({})
const bySource = ref({})
// 收款方式分类汇总（底部）：金额降序 + 占比 + 配色
const METHOD_COLORS = ['#1565c0', '#2e9e6b', '#c47d0a', '#8e24aa', '#00897b', '#d64545', '#5c6bc0']
const methodStats = computed(() => {
  const tot = Number(total.value) || 0
  return Object.entries(byMethod.value)
    .map(([m, v]) => ({ method: m || '未填', amount: Number(v), pct: tot ? Number(v) / tot * 100 : 0 }))
    .sort((a, b) => b.amount - a.amount)
    .map((x, i) => ({ ...x, color: METHOD_COLORS[i % METHOD_COLORS.length] }))
})

async function load() {
  loading.value = true
  try {
    const p = { start_date: filter.start, end_date: filter.end, source: filter.source || undefined, method: filter.method || undefined, q: filter.q || undefined, depts: filter.dept || undefined }
    const d = (await ar.listDailyReceipts(p)).data || {}
    items.value = d.items || []
    total.value = d.total || '0'
    count.value = d.count || 0
    byMethod.value = d.by_method || {}
    bySource.value = d.by_source || {}
    if (d.departments?.length) depts.value = d.departments
    if (d.source_presets?.length) sourcePresets.value = d.source_presets
    if (d.method_presets?.length) methodPresets.value = d.method_presets
    // 清理已不存在的选择
    const live = new Set(items.value.map(i => i.id))
    selectedIds.value = new Set([...selectedIds.value].filter(id => live.has(id)))
  } catch (e) { toast.error(e?.msg || e?.error || '加载失败') }
  finally { loading.value = false }
}
useModalEsc([() => formOpen.value, () => (formOpen.value = false)])

onMounted(load)
watch(() => [filter.source, filter.method, filter.dept], load)

// ── 选择（单选/多选/Shift 连选）───────────────────────────────────────────────
const selectedIds = ref(new Set())
const selCount = computed(() => selectedIds.value.size)
const hasSel = computed(() => selCount.value > 0)
const pageAll = computed(() => items.value.length > 0 && items.value.every(r => selectedIds.value.has(r.id)))
function toggleRow(id) { const s = new Set(selectedIds.value); s.has(id) ? s.delete(id) : s.add(id); selectedIds.value = s }
function toggleAll() { const s = new Set(selectedIds.value); if (pageAll.value) items.value.forEach(r => s.delete(r.id)); else items.value.forEach(r => s.add(r.id)); selectedIds.value = s }
function clearSel() { selectedIds.value = new Set() }
const { onRowSelClick } = useShiftSelect({ items, selectedIds, toggleSingle: toggleRow })
useEscClearSelection(() => hasSel.value, clearSel)
const selectedItems = computed(() => items.value.filter(r => selectedIds.value.has(r.id)))
const selSum = computed(() => selectedItems.value.reduce((s, r) => s + Number(r.amount || 0), 0))

// ── 右键菜单 ─────────────────────────────────────────────────────────────────
const ctx = useContextMenu()
const ROW_COLS = [
  { key: 'receipt_date', label: '收款日期' }, { key: 'delivery_dept', label: '事业部' },
  { key: 'source', label: '来源' }, { key: 'project_name', label: '项目' },
  { key: 'method', label: '方式' }, { key: 'account', label: '账户' },
  { key: 'payer', label: '付款方' }, { key: 'amount', label: '金额' }, { key: 'notes', label: '摘要' },
]
async function copyRow(r) { (await copyRowTSV(r, ROW_COLS, { header: true })) ? toast.success('已复制整行') : toast.error('复制失败') }
const ctxItems = computed(() => {
  const r = ctx.menu.payload
  if (!r) return []
  const inSel = selectedIds.value.has(r.id)
  const multi = hasSel.value && selCount.value > 1 && inSel
  return [
    { key: 'edit', label: '编辑', icon: 'edit', hidden: !canWrite.value, action: rr => openEdit(rr) },
    { key: 'copy', label: '复制整行', icon: 'copy', action: rr => copyRow(rr) },
    { key: 'copy-amt', label: '复制金额', icon: 'copy', action: rr => copyText(String(rr.amount)).then(() => toast.success('已复制金额')) },
    { divider: true },
    multi
      ? { key: 'bulk-del', label: `批量删除选中 ${selCount.value} 条`, icon: 'trash', danger: true, hidden: !canWrite.value, action: () => bulkDelete() }
      : { key: 'del', label: '删除', icon: 'trash', danger: true, hidden: !canWrite.value, action: rr => remove(rr) },
  ]
})

// ── 新增 / 编辑弹窗 ──────────────────────────────────────────────────────────
const sourcePresets = ref(['项目收款', '预付退款'])
const methodPresets = ref(['现金', '微信', '银行转账'])
const formOpen = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = reactive({ delivery_dept: '', receipt_date: todayCST(), amount: '', source: '项目收款', project_id: '', advance_id: '', method: '现金', account: '', payer: '', notes: '' })
const isProjectSource = computed(() => form.source === '项目收款')
const isRefundSource = computed(() => form.source === '预付退款')
const projectKw = ref('')   // 关联项目模糊搜索输入的显示值
function onProjInput(v) { projectKw.value = v; form.project_id = '' }        // 改动清 id，待选中再设
function onProjPicked(p) { projectKw.value = p.short_name || p.customer_name || ''; form.project_id = p.id }
watch(() => form.source, v => {
  if (v !== '项目收款') { form.project_id = ''; projectKw.value = '' }
  if (v !== '预付退款') form.advance_id = ''
  else loadRefundAdvances()
})
// 预付退款可关联的预付（回冲其未核销余额）——独立于「预收预付」页面权限
const refundAdvances = ref([])
async function loadRefundAdvances() {
  try {
    const d = (await ar.listRefundableAdvances({ dept: form.delivery_dept || undefined })).data
    refundAdvances.value = d.items || []
  } catch { refundAdvances.value = [] }
}
watch(() => form.delivery_dept, () => { if (isRefundSource.value) { form.advance_id = ''; loadRefundAdvances() } })
function openCreate() {
  editingId.value = null
  projectKw.value = ''; refundAdvances.value = []
  Object.assign(form, { delivery_dept: filter.dept || depts.value[0] || '', receipt_date: todayCST(), amount: '', source: '项目收款', project_id: '', advance_id: '', method: '现金', account: '', payer: '', notes: '' })
  formOpen.value = true
}
function openEdit(r) {
  editingId.value = r.id
  projectKw.value = r.project_short_name || r.project_name || ''
  Object.assign(form, { delivery_dept: r.delivery_dept, receipt_date: r.receipt_date, amount: r.amount, source: r.source, project_id: r.project_id || '', advance_id: r.advance_record_id || '', method: r.method, account: r.account, payer: r.payer, notes: r.notes })
  formOpen.value = true
  if (r.source === '预付退款') {
    loadRefundAdvances().then(() => {
      // 已关联的预付若余额已为0不在候选里，补一条占位以正常回显
      if (r.advance_record_id && !refundAdvances.value.some(a => a.id === r.advance_record_id)) {
        refundAdvances.value.unshift({ id: r.advance_record_id, counterparty: r.advance_label || '原关联预付', occur_date: '', balance: r.amount })
      }
    })
  }
}
async function save() {
  if (!form.delivery_dept) { toast.error('请选择事业部'); return }
  if (!(Number(form.amount) > 0)) { toast.error('金额必须大于 0'); return }
  if (!form.source.trim()) { toast.error('请填写收款来源'); return }
  saving.value = true
  try {
    const body = { ...form, project_id: isProjectSource.value ? (form.project_id || null) : null,
                   advance_id: isRefundSource.value ? (form.advance_id || null) : null }
    if (editingId.value) await ar.updateDailyReceipt(editingId.value, body); else await ar.createDailyReceipt(body)
    toast.success('已保存'); formOpen.value = false; load()
  } catch (e) { toast.error(e?.msg || e?.error || '保存失败') } finally { saving.value = false }
}
async function remove(r) {
  if (!(await confirmDlg(`删除这笔收款「${r.source} · ${money(r.amount)}」？`))) return
  try { await ar.deleteDailyReceipt(r.id); toast.success('已删除'); load() } catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
}
async function bulkDelete() {
  if (!selCount.value) return
  if (!(await confirmDlg(`批量删除所选 ${selCount.value} 笔收款（合计 ${money(selSum.value)}）？此操作不可撤销。`))) return
  try { const d = (await ar.bulkDeleteDailyReceipts([...selectedIds.value])).data || {}; toast.success(`已删除 ${d.deleted ?? selCount.value} 笔`); clearSel(); load() }
  catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
}
function resetFilters() { filter.source = ''; filter.method = ''; filter.dept = ''; filter.q = ''; applyPreset('thismonth') }
const exporting = ref(false)
async function exportXlsx(selectedOnly = false) {
  if (!items.value.length && !selectedOnly) { toast.warn('无可导出的数据'); return }
  exporting.value = true
  try {
    const p = { start_date: filter.start, end_date: filter.end, source: filter.source || undefined, method: filter.method || undefined, q: filter.q || undefined, depts: filter.dept || undefined }
    if (selectedOnly && hasSel.value) p.ids = [...selectedIds.value].join(',')
    const res = await ar.exportDailyReceipts(p)
    const tag = selectedOnly ? `选中${selCount.value}笔` : `${filter.start}_${filter.end}`
    downloadBlob(res, `日常收款_${tag}.xlsx`)
  } catch (e) { toast.error(e?.msg || e?.error || '导出失败') }
  finally { exporting.value = false }
}
</script>

<template>
  <div class="dr fh-fill">
    <!-- 顶部：标题+筛选一行，时间快选独占一行 -->
    <div class="dr-top">
      <div class="dr-head">
        <div class="dr-title">日常收款<span class="dr-sub">计入现金流与资金池</span></div>
        <span class="grow"></span>
        <select v-model="filter.dept" class="inp mini"><option value="">全部事业部</option><option v-for="d in depts" :key="d" :value="d">{{ d }}</option></select>
        <select v-model="filter.source" class="inp mini"><option value="">全部来源</option><option v-for="s in Object.keys(bySource)" :key="s" :value="s">{{ s }}</option></select>
        <select v-model="filter.method" class="inp mini"><option value="">全部方式</option><option v-for="m in Object.keys(byMethod)" :key="m" :value="m">{{ m }}</option></select>
        <input v-model="filter.q" class="inp search" placeholder="搜付款方 / 摘要 / 项目" @keyup.enter="load" />
        <button class="btn ghost sm" :disabled="exporting" @click="exportXlsx(false)">{{ exporting ? '导出中…' : '导出' }}</button>
        <button v-if="canWrite" class="btn-hero" @click="openCreate"><span>＋</span> 新增收款</button>
      </div>
      <!-- 时间维度：单行，超宽横向滚动 -->
      <div class="dr-timebar">
        <button v-for="p in DATE_PRESETS" :key="p.k" class="pchip" :class="{ on: activePreset === p.k }" @click="applyPreset(p.k)">{{ p.l }}</button>
        <span class="fdiv"></span>
        <input v-model="filter.start" type="date" class="inp inp-date" @change="load" />
        <span class="tilde">~</span>
        <input v-model="filter.end" type="date" class="inp inp-date" @change="load" />
        <button class="btn ghost sm reset" @click="resetFilters">重置</button>
      </div>
    </div>

    <!-- 表格：主角，占据剩余空间 -->
    <div class="dr-tablewrap">
      <div v-if="loading" class="empty">⏳ 加载中…</div>
      <div v-else-if="!items.length" class="empty">
        <div class="empty-i">💰</div><div class="empty-t">此区间暂无收款记录</div>
        <div v-if="canWrite" class="empty-s">点右上「新增收款」录入第一笔。</div>
      </div>
      <table v-else class="dr-table">
        <thead>
          <tr>
            <th class="cb"><input type="checkbox" :checked="pageAll" :indeterminate.prop="hasSel && !pageAll" @change="toggleAll" /></th>
            <th>收款日期</th><th>事业部</th><th>来源</th><th>项目</th><th>方式</th><th>账户</th><th>付款方</th><th class="r">金额</th><th>摘要</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, idx) in items" :key="r.id" :class="{ sel: selectedIds.has(r.id) }"
              @contextmenu.prevent="ctx.open($event, r)" @dblclick="canWrite && openEdit(r)">
            <td class="cb" @click.stop><input type="checkbox" :checked="selectedIds.has(r.id)" @click="onRowSelClick($event, idx, r.id)" /></td>
            <td class="when">{{ r.receipt_date }}</td>
            <td>{{ r.delivery_dept }}</td>
            <td><span class="src">{{ r.source }}</span><span v-if="r.advance_record_id" class="adv-tag" :title="'已回冲预付：' + r.advance_label">↩冲预付</span></td>
            <td class="proj">{{ r.project_name || '—' }}</td>
            <td><span v-if="r.method" class="mtd">{{ r.method }}</span><span v-else class="dim">—</span></td>
            <td class="dim">{{ r.account || '—' }}</td>
            <td>{{ r.payer || '—' }}</td>
            <td class="r amt"><Amt :v="r.amount" :fmt="money" /></td>
            <td class="sumcell" :title="r.notes">{{ r.notes || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 底部汇总栏 -->
    <div class="dr-footer">
      <template v-if="hasSel">
        <span class="f-sel">已选 <b>{{ selCount }}</b> 笔 · 合计 <b class="hl"><Amt :v="selSum" :fmt="money" /></b></span>
        <button class="f-btn" :disabled="exporting" @click="exportXlsx(true)">导出选中</button>
        <button v-if="canWrite" class="f-btn del" @click="bulkDelete">批量删除</button>
        <button class="f-btn" @click="clearSel">取消选择</button>
        <span class="grow"></span>
      </template>
      <template v-else>
        <span class="f-total">
          <span class="ft-lbl">区间合计</span>
          <b class="ft-val"><Amt :v="total" :fmt="money" /></b>
          <span class="ft-cnt">{{ count }} 笔</span>
        </span>
        <!-- 收款方式分类汇总：占比条 + 图例 -->
        <div v-if="methodStats.length" class="f-methods">
          <div class="mstack">
            <i v-for="s in methodStats" :key="s.method" :style="{ width: s.pct + '%', background: s.color }" :title="`${s.method} ${money(s.amount)} · ${s.pct.toFixed(0)}%`"></i>
          </div>
          <div class="mlegend">
            <span v-for="s in methodStats" :key="s.method" class="mleg">
              <i :style="{ background: s.color }"></i>{{ s.method }}
              <b>{{ fmtCompact(s.amount) }}</b><em>{{ s.pct.toFixed(0) }}%</em>
            </span>
          </div>
        </div>
      </template>
    </div>

    <ContextMenu :ctx="ctx" :items="ctxItems" />

    <!-- 新增/编辑弹窗 -->
    <Teleport to="body">
      <div v-if="formOpen" class="scrim" @click.self="formOpen = false">
        <div class="dlg">
          <div class="d-head"><h3>{{ editingId ? '编辑收款' : '新增收款' }}</h3><button class="d-x" @click="formOpen = false">✕</button></div>
          <div class="d-body">
            <div class="grid2">
              <div class="frow"><label>事业部 <i>*</i></label><select v-model="form.delivery_dept" class="inp"><option value="" disabled>请选择</option><option v-for="d in depts" :key="d" :value="d">{{ d }}</option></select></div>
              <div class="frow"><label>收款日期 <i>*</i></label><input v-model="form.receipt_date" type="date" class="inp" /></div>
            </div>
            <div class="frow"><label>收款来源 <i>*</i></label>
              <PillPicker v-model="form.source" :presets="sourcePresets" placeholder="自定义来源，如 政府补贴" />
            </div>
            <div v-if="isProjectSource" class="frow"><label>关联项目</label>
              <ProjectShortNamePicker :modelValue="projectKw" placeholder="模糊搜索项目台账（留空=不关联）"
                                      @update:modelValue="onProjInput" @picked="onProjPicked" />
            </div>
            <div v-if="isRefundSource" class="frow"><label>关联预付 <span class="hint">选填 · 选中后回冲该预付未核销余额</span></label>
              <select v-model="form.advance_id" class="inp">
                <option value="">不关联（仅记为现金流入，不回冲预付）</option>
                <option v-for="a in refundAdvances" :key="a.id" :value="a.id">
                  {{ a.counterparty || '预付' }}<span v-if="a.occur_date"> · {{ a.occur_date }}</span> · 余额 <Amt :v="a.balance" :fmt="money" />{{ a.project_short_name ? ' · ' + a.project_short_name : '' }}
                </option>
              </select>
            </div>
            <div class="frow"><label>收款方式</label>
              <PillPicker v-model="form.method" :presets="methodPresets" placeholder="自定义方式，如 支付宝" />
            </div>
            <div class="grid2">
              <div class="frow"><label>收款金额 <i>*</i></label><input v-model="form.amount" type="number" step="0.01" class="inp big-amt" placeholder="0.00" /></div>
              <div class="frow"><label>收款账户</label><input v-model="form.account" class="inp" placeholder="如 微信-结算001" /></div>
            </div>
            <div class="frow"><label>付款方</label><input v-model="form.payer" class="inp" placeholder="选填" /></div>
            <div class="frow"><label>摘要/备注</label><textarea v-model="form.notes" class="inp" rows="2" placeholder="选填"></textarea></div>
          </div>
          <div class="d-foot"><button class="btn ghost" @click="formOpen = false">取消</button><button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存收款' }}</button></div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dr { display: flex; flex-direction: column; min-height: 0; height: 100%; padding: 0; }
/* 顶部紧凑区 */
.dr-top { flex: none; padding: 14px 20px 10px; border-bottom: 1px solid var(--border, #eadfd2); background: var(--glass, rgba(255,254,251,.6)); display: flex; flex-direction: column; gap: 10px; }
.dr-head { display: flex; align-items: center; gap: 12px;; flex-wrap: wrap; }
.dr-title { font-size: 19px; font-weight: 850; letter-spacing: -.01em; color: var(--text, #4a3322); }
.dr-sub { font-size: 12px; font-weight: 500; color: var(--muted, #9b8070); margin-left: 10px; }
.grow { flex: 1; }
.btn-hero { border: none; background: var(--grad); color: #fff; border-radius: 10px; padding: 9px 18px; font-size: 14px; font-weight: 750; cursor: pointer; font-family: inherit; box-shadow: 0 6px 18px -7px color-mix(in srgb, var(--primary) 60%, transparent); display: inline-flex; align-items: center; gap: 7px; transition: transform .16s; }
.btn-hero:hover { transform: translateY(-1px); } .btn-hero span { font-size: 17px; }
.dr-timebar { display: flex; align-items: center; gap: 6px; flex-wrap: nowrap; overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
.dr-timebar::-webkit-scrollbar { height: 5px; } .dr-timebar::-webkit-scrollbar-thumb { background: var(--border, #d8c9b8); border-radius: 3px; }
.pchip { flex: none; border: 1px solid var(--border, #e2d6c6); background-color: var(--card-bg, #fff); color: var(--text, #6a5641); border-radius: 20px; padding: 5px 13px; font-size: 12.5px; cursor: pointer; font-family: inherit; transition: .14s; white-space: nowrap; }
.pchip:hover { border-color: var(--primary); color: var(--primary); }
.pchip.on { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 650; box-shadow: 0 4px 12px -4px color-mix(in srgb, var(--primary) 55%, transparent); }
.fdiv { flex: none; width: 1px; height: 18px; background: var(--border, #e2d6c6); margin: 0 3px; }
.tilde { flex: none; color: var(--muted, #9b8070); }
.dr-timebar .inp-date { flex: none; } .dr-timebar .reset { flex: none; margin-left: 4px; }
.inp { border: 1px solid var(--border, #d8c9b8); border-radius: 8px; padding: 6px 10px; font-size: 13px; font-family: inherit; background-color: var(--card-bg, #fff); color: var(--text, #4a3322); outline: none; width: auto; transition: .14s; }
.inp:focus { border-color: var(--primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 14%, transparent); }
.inp-date { width: 138px; } .search { width: 200px;; flex: 1 1 160px; min-width: 120px; width: auto; } .inp.mini { font-size: 12.5px; padding: 6px 26px 6px 9px; }
.btn { border: 1px solid var(--border, #d8c9b8); background-color: var(--card-bg, #fff); color: var(--text, #4a3322); border-radius: 8px; padding: 6px 13px; font-size: 13px; font-weight: 650; cursor: pointer; font-family: inherit; }
.btn.ghost { background: none; } .btn.sm { padding: 6px 12px; }
.btn.primary { background: var(--primary); color: #fff; border-color: var(--primary); }
.btn:disabled { opacity: .6; cursor: default; }
/* 表格区（主角）*/
.dr-tablewrap { flex: 1; min-height: 0; overflow: auto; }
.empty { padding: 64px 20px; text-align: center; color: var(--muted, #9b8070); }
.empty-i { font-size: 42px; } .empty-t { font-size: 16px; font-weight: 700; color: var(--text, #4a3322); margin-top: 8px; } .empty-s { margin-top: 6px; font-size: 13px; }
.dr-table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.dr-table thead th { text-align: left; padding: 11px 14px; font-size: 11px; font-weight: 750; letter-spacing: .04em; text-transform: uppercase; color: var(--muted, #9b8070); background: var(--surface-2, rgba(160,120,80,.07)); white-space: nowrap; position: sticky; top: 0; z-index: 2; }
.dr-table th.r, .dr-table td.r { text-align: right; } .dr-table th.cb, .dr-table td.cb { width: 40px; text-align: center; }
.dr-table tbody td { padding: 10px 14px; border-top: 1px solid var(--border, #eadfd2); white-space: nowrap; }
.dr-table tbody tr:nth-child(even) { background: color-mix(in srgb, var(--muted, #9b8070) 3.5%, transparent); }
.dr-table tbody tr:hover { background: var(--surface-2, rgba(160,120,80,.1)); cursor: default; }
.dr-table tbody tr.sel { background: color-mix(in srgb, var(--primary) 10%, transparent) !important; }
.amt { font-variant-numeric: tabular-nums; font-weight: 800; color: var(--primary); }
.src { background: var(--primary-weak, #e8f1fb); color: var(--primary); border-radius: 8px; padding: 2px 9px; font-size: 12px; font-weight: 600; }
.mtd { background: var(--surface-2, rgba(160,120,80,.12)); color: var(--text, #6a5641); border-radius: 7px; padding: 1px 8px; font-size: 12px; }
.adv-tag { margin-left: 6px; font-size: 10.5px; color: var(--c-success, #2e7d32); background: rgba(46,125,50,.1); border-radius: 6px; padding: 1px 6px; white-space: nowrap; }
.hint { font-weight: 400; font-size: 11px; color: var(--muted, #999); }
.proj { color: var(--text, #4a3322); } .dim, .when { color: var(--muted, #7a6550); }
.sumcell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; color: var(--muted, #7a6550); }
input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--primary); cursor: pointer; }
/* 底部汇总栏 */
.dr-footer { flex: none; display: flex; align-items: center; gap: 18px; padding: 10px 20px; border-top: 1px solid var(--border, #eadfd2); background: var(--glass, rgba(255,254,251,.7)); backdrop-filter: blur(6px); min-height: 30px; }
.hl { color: var(--primary); }
.f-total { display: flex; align-items: baseline; gap: 8px; flex: none; }
.ft-lbl { font-size: 11.5px; font-weight: 700; letter-spacing: .04em; color: var(--muted, #9b8070); text-transform: uppercase; }
.ft-val { font-size: 20px; font-weight: 850; color: var(--primary); font-variant-numeric: tabular-nums; }
.ft-cnt { font-size: 12px; color: var(--muted, #9b8070); }
.f-methods { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 0; }
.mstack { display: flex; height: 9px; width: 150px; flex: none; border-radius: 5px; overflow: hidden; background: var(--surface-2, rgba(160,120,80,.14)); }
.mstack i { height: 100%; }
.mlegend { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; min-width: 0; }
.mleg { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--text, #6a5641); }
.mleg i { width: 9px; height: 9px; border-radius: 3px; flex: none; }
.mleg b { font-weight: 800; color: var(--text, #4a3322); font-variant-numeric: tabular-nums; }
.mleg em { font-style: normal; color: var(--muted, #9b8070); font-size: 11.5px; }
.f-sel { font-size: 13.5px; color: var(--text, #4a3322); } .f-sel b { font-weight: 800; }
.f-btn { border: 1px solid var(--border, #d8c9b8); background-color: var(--card-bg, #fff); color: var(--text, #4a3322); border-radius: 8px; padding: 5px 14px; font-size: 13px; font-weight: 650; cursor: pointer; font-family: inherit; }
.f-btn.del { border-color: var(--danger, #d64545); color: var(--danger, #d64545); }
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
.frow .inp { width: 100%; box-sizing: border-box; } .big-amt { font-size: 16px; font-weight: 700; }
.seg-wrap { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.preset { border: 1px solid var(--border, #d8c9b8); background-color: var(--card-bg, #fff); color: var(--text, #4a3322); border-radius: 9px; padding: 7px 14px; font-size: 13px; cursor: pointer; font-family: inherit; }
.preset.on { background: var(--primary-weak, #e8f1fb); border-color: var(--primary); color: var(--primary); font-weight: 650; }
.custom { min-width: 130px; flex: 1; }
.d-foot { padding: 14px 22px; border-top: 1px solid var(--border, #eadfd2); display: flex; justify-content: flex-end; gap: 10px; }
@media (max-width: 640px) { .grid2 { grid-template-columns: 1fr; } }
</style>
