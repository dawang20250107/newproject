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

// ── 筛选 ────────────────────────────────────────────────────────────────────
const depts = ref([])          // 可见事业部（后端返回）
const sourcePresets = ref(['项目收款', '预付退款'])
const methodPresets = ref(['现金', '微信', '银行转账'])
function monthStart() { const t = todayCST(); return t.slice(0, 8) + '01' }
const filter = reactive({ dept: '', source: '', method: '', start: monthStart(), end: todayCST(), q: '' })

// ── 数据 ────────────────────────────────────────────────────────────────────
const loading = ref(false)
const items = ref([])
const total = ref('0')
const byMethod = ref({})
const bySource = ref({})

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

const money = v => '¥' + Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })

// ── 新增 / 编辑弹窗 ──────────────────────────────────────────────────────────
const formOpen = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = reactive({
  delivery_dept: '', receipt_date: todayCST(), amount: '', source: '项目收款',
  project_id: '', method: '现金', account: '', payer: '', notes: '',
})
const isProjectSource = computed(() => form.source === '项目收款')
const projects = ref([])          // 该部门项目（来源=项目收款时用）
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
    toast.success('已保存')
    formOpen.value = false
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '保存失败') }
  finally { saving.value = false }
}
async function remove(r) {
  if (!(await confirmDlg(`删除这笔收款「${r.source} · ${money(r.amount)}」？`))) return
  try { await ar.deleteDailyReceipt(r.id); toast.success('已删除'); load() }
  catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
}
</script>

<template>
  <div class="dr card fh-fill">
    <!-- 工具条 -->
    <div class="dr-bar">
      <div class="dr-title">日常收款<span class="dr-sub">项目收款 / 预付退款 / 其他 —— 计入现金流与资金池</span></div>
      <span class="grow"></span>
      <button v-if="canWrite" class="btn primary" @click="openCreate">＋ 新增收款</button>
    </div>

    <!-- 筛选 -->
    <div class="dr-filters">
      <select v-model="filter.dept" class="inp"><option value="">全部事业部</option><option v-for="d in depts" :key="d" :value="d">{{ d }}</option></select>
      <select v-model="filter.source" class="inp"><option value="">全部来源</option><option v-for="s in Object.keys(bySource)" :key="s" :value="s">{{ s }}</option></select>
      <select v-model="filter.method" class="inp"><option value="">全部方式</option><option v-for="m in Object.keys(byMethod)" :key="m" :value="m">{{ m }}</option></select>
      <input v-model="filter.start" type="date" class="inp inp-date" />
      <span class="sep">→</span>
      <input v-model="filter.end" type="date" class="inp inp-date" />
      <input v-model="filter.q" class="inp" placeholder="搜付款方/摘要/项目" @keyup.enter="load" />
      <button class="btn" @click="load">查询</button>
    </div>

    <!-- 汇总 -->
    <div class="dr-summary">
      <span class="s big">合计收款 <b>{{ money(total) }}</b></span>
      <span class="grow"></span>
      <span v-for="(v, m) in byMethod" :key="m" class="chip">{{ m }} {{ fmtCompact(v) }}</span>
    </div>

    <!-- 表 -->
    <div class="dr-body">
      <div v-if="loading" class="empty">⏳ 加载中…</div>
      <div v-else-if="!items.length" class="empty">此范围暂无收款记录，点右上「新增收款」录入。</div>
      <div v-else class="tablewrap">
        <table>
          <thead>
            <tr><th>收款日期</th><th>事业部</th><th>来源</th><th>项目</th><th>方式</th><th>账户</th><th>付款方</th><th class="r">金额</th><th>摘要</th><th v-if="canWrite"></th></tr>
          </thead>
          <tbody>
            <tr v-for="r in items" :key="r.id">
              <td class="when">{{ r.receipt_date }}</td>
              <td>{{ r.delivery_dept }}</td>
              <td><span class="src">{{ r.source }}</span></td>
              <td>{{ r.project_name || '—' }}</td>
              <td>{{ r.method || '—' }}</td>
              <td>{{ r.account || '—' }}</td>
              <td>{{ r.payer || '—' }}</td>
              <td class="r amt">{{ money(r.amount) }}</td>
              <td class="sumcell">{{ r.notes || '—' }}</td>
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
        <div class="modal">
          <div class="m-head"><h3>{{ editingId ? '编辑收款' : '新增收款' }}</h3></div>
          <div class="m-body">
            <div class="frow">
              <label>事业部 *</label>
              <select v-model="form.delivery_dept" class="inp"><option value="" disabled>请选择</option><option v-for="d in depts" :key="d" :value="d">{{ d }}</option></select>
            </div>
            <div class="frow">
              <label>收款日期 *</label>
              <input v-model="form.receipt_date" type="date" class="inp" />
            </div>
            <div class="frow">
              <label>收款来源 *</label>
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
            <div class="frow">
              <label>收款金额 *</label>
              <input v-model="form.amount" type="number" step="0.01" class="inp" placeholder="0.00" />
            </div>
            <div class="frow">
              <label>收款账户</label>
              <input v-model="form.account" class="inp" placeholder="如 微信-结算001（选填）" />
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
          <div class="m-foot">
            <button class="btn" @click="formOpen = false">取消</button>
            <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dr { display: flex; flex-direction: column; min-height: 0; padding: 0; }
.dr-bar { display: flex; align-items: center; gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--border, #eadfd2); }
.dr-title { font-size: 17px; font-weight: 800; color: var(--text, #4a3322); }
.dr-sub { font-size: 12px; font-weight: 500; color: var(--muted, #9b8070); margin-left: 10px; }
.dr-filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 18px; border-bottom: 1px solid var(--border, #eadfd2); background: var(--panel-2, #faf6f0); }
.inp { border: 1px solid var(--border, #d8c9b8); border-radius: 7px; padding: 6px 9px; font-size: 13px; font-family: inherit; background: var(--card-bg, #fff); color: var(--text, #4a3322); outline: none; }
.inp-date { width: 140px; } .sep { color: var(--muted, #9b8070); }
.btn { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--text, #4a3322); border-radius: 8px; padding: 7px 15px; font-size: 13px; font-weight: 650; cursor: pointer; font-family: inherit; }
.btn.primary { background: var(--primary, #1565c0); color: #fff; border-color: var(--primary, #1565c0); }
.btn:disabled { opacity: .6; cursor: default; }
.grow { flex: 1; }
.dr-summary { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px 18px; border-bottom: 1px solid var(--border, #eadfd2); }
.dr-summary .big b { font-size: 18px; font-weight: 800; color: var(--primary, #1565c0); }
.chip { font-size: 12px; background: var(--surface-2, rgba(160,120,80,.1)); color: var(--text, #6a5641); border-radius: 12px; padding: 2px 10px; }
.dr-body { flex: 1; min-height: 0; overflow: auto; }
.empty { padding: 50px; text-align: center; color: var(--muted, #9b8070); font-size: 13.5px; }
.tablewrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
thead th { text-align: left; padding: 10px 12px; font-size: 11.5px; font-weight: 700; color: var(--muted, #9b8070); background: var(--surface-2, rgba(160,120,80,.06)); white-space: nowrap; position: sticky; top: 0; }
thead th.r, td.r { text-align: right; }
tbody td { padding: 9px 12px; border-top: 1px solid var(--border, #eadfd2); white-space: nowrap; }
tbody tr:nth-child(even) { background: color-mix(in srgb, var(--muted, #9b8070) 4%, transparent); }
tbody tr:hover { background: var(--surface-2, rgba(160,120,80,.08)); }
.amt { font-variant-numeric: tabular-nums; font-weight: 700; color: var(--primary, #1565c0); }
.src { background: var(--primary-weak, #e8f1fb); color: var(--primary, #1565c0); border-radius: 8px; padding: 1px 8px; font-size: 12px; }
.sumcell { max-width: 240px; overflow: hidden; text-overflow: ellipsis; color: var(--muted, #7a6550); }
.when { color: var(--muted, #7a6550); }
.ops { white-space: nowrap; }
.op { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--primary, #1565c0); font-size: 12px; padding: 3px 9px; border-radius: 6px; cursor: pointer; font-family: inherit; margin-right: 5px; }
.op.del { color: var(--danger, #d64545); }
/* 弹窗 */
.scrim { position: fixed; inset: 0; background: rgba(30,20,10,.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: var(--card-bg, #fff); border-radius: 14px; width: min(480px, 94vw); max-height: 90vh; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,.3); }
.m-head { padding: 16px 20px; border-bottom: 1px solid var(--border, #eadfd2); } .m-head h3 { margin: 0; font-size: 16px; color: var(--text, #4a3322); }
.m-body { padding: 14px 20px; overflow-y: auto; }
.frow { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 11px; }
.frow > label { flex: none; width: 76px; font-size: 12.5px; color: var(--muted, #9b8070); padding-top: 7px; }
.frow .inp { flex: 1; }
.seg-wrap { flex: 1; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.preset { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--text, #4a3322); border-radius: 7px; padding: 6px 12px; font-size: 12.5px; cursor: pointer; font-family: inherit; }
.preset.on { background: var(--primary-weak, #e8f1fb); border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); }
.custom { min-width: 120px; }
.m-foot { padding: 12px 20px; border-top: 1px solid var(--border, #eadfd2); display: flex; justify-content: flex-end; gap: 10px; }
</style>
