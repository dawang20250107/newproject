<script setup>
import { confirmDlg } from '../composables/confirm.js'
import { resultDlg } from '../composables/bulkResult.js'
import { ref, computed, onMounted } from 'vue'
import api from '../api/index.js'
import { cachedGet } from '../api/refCache.js'
import { useAuthStore } from '../stores/auth.js'
import { useToast } from '../composables/useToast.js'
import { useShiftSelect } from '../composables/useShiftSelect.js'
import { useEscClearSelection } from '../composables/useEscClearSelection.js'
import Pager from '../components/Pager.vue'

const auth = useAuthStore()
const toast = useToast()

const SELECT_ALL_CAP = 5000  // 与后端单次处理上限对齐
const activeTab = ref('approvals') // 'approvals' | 'payments' | 'records'
// 各页签的回收站接口:审批/付款在 /trash/*;应收在 AR 域 /ar/records/trash
const TRASH_URL = { approvals: '/trash/approvals', payments: '/trash/payments', records: '/ar/records/trash' }
const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(50)
const selectedIds = ref(new Set())
const allAcross = ref(false)   // 跨页全选：作用于全部软删记录
const deptFilter = ref('')     // 页内事业部筛选（'' = 全部）
const depts = ref([])

async function loadDepts() {
  try { const r = await cachedGet('/departments'); depts.value = r.data || [] } catch {}
}

const pageAllSelected = computed(() =>
  items.value.length > 0 && selectedIds.value.size === items.value.length)
const selectedCount = computed(() => allAcross.value ? total.value : selectedIds.value.size)
const hasMorePages = computed(() => total.value > items.value.length)

// 单调递增请求序号：只采纳「最新一次」请求的响应，丢弃过期响应，
// 杜绝快速切换事业部/标签时旧响应后到覆盖新数据（表现为「卡在某个事业部」）。
let reqSeq = 0
async function load() {
  const seq = ++reqSeq
  loading.value = true
  selectedIds.value = new Set()
  allAcross.value = false
  try {
    const params = { page: page.value, size: size.value }
    if (deptFilter.value) params.dept = deptFilter.value
    const r = await api.get(TRASH_URL[activeTab.value], { params })
    if (seq !== reqSeq) return   // 已有更新的请求在途，丢弃本次过期响应
    items.value = r.data.items || []
    total.value = r.data.total || 0
    resetAnchor()
    // 末页整页被还原/删除后本页为空但仍有数据 → 自动回退一页，避免死在空页
    if (!items.value.length && total.value > 0 && page.value > 1) {
      page.value -= 1
      load()
      return
    }
  } catch (e) {
    if (seq !== reqSeq) return
    toast.error(e?.msg || '加载失败')
  } finally {
    if (seq === reqSeq) loading.value = false
  }
}

function switchTab(t) { activeTab.value = t; page.value = 1; load() }
function onDeptChange() { page.value = 1; load() }
onMounted(() => { loadDepts(); load() })

function toggleSel(id) {
  allAcross.value = false   // 手动改选 → 退出跨页全选
  if (selectedIds.value.has(id)) selectedIds.value.delete(id)
  else selectedIds.value.add(id)
}
function toggleAll() {
  allAcross.value = false
  if (selectedIds.value.size === items.value.length) selectedIds.value = new Set()
  else selectedIds.value = new Set(items.value.map(i => i.id))
}
function selectAllAcross() {
  allAcross.value = true
  selectedIds.value = new Set(items.value.map(i => i.id))  // 视觉上本页也勾上
}
function clearSelection() { allAcross.value = false; selectedIds.value = new Set() }
useEscClearSelection(() => allAcross.value || selectedIds.value.size > 0, clearSelection)   // ESC 退出勾选
// Excel 式 Shift 区间勾选（系统级复用）；区间选择也退出「跨页全选」态
const { onRowSelClick, resetAnchor } = useShiftSelect({ items, selectedIds, toggleSingle: toggleSel, onManual: () => { allAcross.value = false } })

const busy = ref(false)
async function doAction(action) {
  if (!selectedCount.value) { toast.warn('请先选择记录'); return }
  const label = action === 'restore' ? '还原' : '彻底删除'
  if (action === 'purge') {
    // 影响面前置展示 + 输入式确认：彻底删除不可恢复，必须让操作者看清删的是多少钱
    const sel = items.value.filter(i => selectedIds.value.has(i.id))
    const amtSum = sel.reduce((a, i) => a + (parseFloat(activeTab.value === 'approvals' ? i.amount : (activeTab.value === 'records' ? i.estimated_amount : i.total_amount)) || 0), 0)
    const paidSum = activeTab.value === 'payments'
      ? sel.reduce((a, i) => a + (parseFloat(i.total_paid) || 0), 0) : 0
    const detail = [
      allAcross.value ? `范围：当前筛选下全部 ${total.value} 条（跨页全选）` : `范围：勾选的 ${selectedCount.value} 条`,
      `金额合计：¥${amtSum.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}` + (allAcross.value ? '（仅当前页可见部分）' : ''),
    ]
    if (paidSum > 0) detail.push(`⚠ 其中已实付 ¥${paidSum.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}：彻删将连同付款流水一并抹除，审计痕迹不可恢复`)
    detail.push('彻底删除后无法通过任何方式找回。')
    if (!(await confirmDlg({
      title: '彻底删除（不可恢复）', danger: true,
      message: `即将彻底删除 ${allAcross.value ? total.value : selectedCount.value} 条${({approvals:'审批',payments:'付款',records:'应收'})[activeTab.value]}记录`,
      detail, requireText: '删除', confirmText: '彻底删除',
    }))) return
  }
  busy.value = true
  try {
    const body = allAcross.value ? { action, all: true } : { action, ids: [...selectedIds.value] }
    // dept 作为 query 参数传给后端，使跨页 all 操作同样限定在当前事业部筛选内
    const cfg = deptFilter.value ? { params: { dept: deptFilter.value } } : {}
    const r = await api.post(TRASH_URL[activeTab.value], body, cfg)
    const n = r.data.count
    const skipped = r.data.skipped || []
    if (n) toast.success(`已${label} ${n} 条` + (allAcross.value && total.value > n ? `（单次上限 ${SELECT_ALL_CAP}，剩余请再次操作）` : ''))
    // 审批彻底删除被关联付款拦下 → 交给用户决定是否级联删除（明确提示，不可撤销）
    const cascadable = (action === 'purge' && activeTab.value === 'approvals')
      ? skipped.filter(s => s.linked_payments > 0) : []
    if (cascadable.length) {
      const totalPay = cascadable.reduce((a, s) => a + (s.linked_payments || 0), 0)
      if (await confirmDlg({
        title: '级联彻底删除（不可恢复）', danger: true,
        message: `${cascadable.length} 条审批仍关联 ${totalPay} 笔付款，无法单独彻底删除`,
        detail: ['继续将【连同这些关联付款（含全部付款流水）】一并彻底删除',
                 '付款的实付分期记录也会被永久抹除，审计痕迹不可恢复'],
        requireText: '级联删除', confirmText: '级联彻底删除',
      })) {
        const r2 = await api.post(TRASH_URL[activeTab.value],
          { action: 'purge', ids: cascadable.map(s => s.id), cascade: true }, cfg)
        const n2 = r2.data.count, sk2 = r2.data.skipped || []
        if (n2) toast.success(`已连同关联付款彻底删除 ${n2} 条审批`)
        if (sk2.length) toast.warn(`${sk2.length} 条仍未删除：${sk2[0].reason}`)
        load()
        return
      }
    }
    if (skipped.length) {
      resultDlg({ title: `${label}结果`, okLine: n ? `已${label} ${n} 条` : '', skipped })
    } else if (!n) {
      toast.warn(`没有可${label}的记录`)
    }
    load()
  } catch (e) {
    toast.error(e?.msg || '操作失败')
  } finally {
    busy.value = false }
}

function fmtDate(s) {
  if (!s) return '-'
  return s.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div class="trash-page">
    <div class="trash-header">
      <h2 class="trash-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--c-danger)">
          <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
        </svg>
        回收站
      </h2>
      <div class="trash-tabs">
        <button :class="['ttab', activeTab === 'approvals' ? 'active' : '']" @click="switchTab('approvals')">审批管理</button>
        <button :class="['ttab', activeTab === 'payments' ? 'active' : '']" @click="switchTab('payments')">付款管理</button>
        <button :class="['ttab', activeTab === 'records' ? 'active' : '']" @click="switchTab('records')">应收记录</button>
      </div>
      <select v-model="deptFilter" class="trash-dept" @change="onDeptChange" title="按事业部筛选">
        <option value="">全部事业部</option>
        <option v-for="d in depts" :key="d" :value="d">{{ d }}</option>
      </select>
      <div class="trash-actions" v-if="auth.canDelete">
        <span v-if="selectedCount" class="trash-selcount">已选 {{ selectedCount }} 条</span>
        <button class="tact-btn restore" :disabled="!selectedCount || busy" @click="doAction('restore')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 109-9H3"/><polyline points="3 3 3 9 9 9"/></svg>
          还原
        </button>
        <button class="tact-btn purge" :disabled="!selectedCount || busy" @click="doAction('purge')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
          彻底删除
        </button>
      </div>
    </div>
    <div class="trash-hint">回收站内的记录不计入列表和统计；可还原恢复，或彻底删除永久清除。</div>

    <!-- 跨页全选条：本页全选且有更多页时出现 -->
    <div v-if="auth.canDelete && (pageAllSelected || allAcross) && hasMorePages" class="trash-selbar">
      <template v-if="!allAcross">
        已选本页 {{ selectedIds.size }} 条。
        <button class="trash-selink" @click="selectAllAcross">选择全部 {{ total }} 条（跨页）</button>
      </template>
      <template v-else>
        已选择<b>全部 {{ total }} 条</b>软删记录{{ total > SELECT_ALL_CAP ? `（单次最多处理 ${SELECT_ALL_CAP} 条，可重复操作）` : '' }}。
        <button class="trash-selink" @click="clearSelection">清除选择</button>
      </template>
    </div>

    <div class="trash-card fh-fill">
      <div v-if="loading" class="trash-loading">加载中…</div>
      <div v-else-if="!items.length" class="trash-empty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" style="color:var(--muted-light)">
          <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
        </svg>
        <p>回收站为空</p>
      </div>
      <template v-else>
        <div class="table-wrap page-scroll">
        <table class="trash-tbl">
          <thead>
            <tr>
              <th class="sel-col"><input type="checkbox" :checked="pageAllSelected" :indeterminate.prop="selectedIds.size > 0 && !pageAllSelected" @change="toggleAll"/></th>
              <th v-if="activeTab === 'approvals'">申请人</th>
              <th>部门</th>
              <th v-if="activeTab === 'approvals'">审批编号</th>
              <th v-if="activeTab === 'approvals'">摘要</th>
              <th v-if="activeTab === 'payments'">付款事项</th>
              <th v-if="activeTab === 'payments'">收款方</th>
              <th v-if="activeTab === 'records'">项目</th>
              <th v-if="activeTab === 'records'">运作日期</th>
              <th v-if="activeTab === 'records'">未收</th>
              <th>金额</th>
              <th>删除时间</th>
              <th>删除人</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(it, idx) in items" :key="it.id" :class="{ 'row-sel': selectedIds.has(it.id) }" @click="onRowSelClick($event, idx, it.id)" style="cursor:pointer" title="按住 Shift 点击可区间勾选">
              <td class="sel-col" @click.stop><input type="checkbox" :checked="selectedIds.has(it.id)" @click.stop="onRowSelClick($event, idx, it.id)"/></td>
              <td v-if="activeTab === 'approvals'">{{ it.applicant }}</td>
              <td>{{ it.department }}</td>
              <td v-if="activeTab === 'approvals'">{{ it.approval_number }}</td>
              <td v-if="activeTab === 'approvals'" class="ellipsis" :title="it.summary">{{ it.summary }}</td>
              <td v-if="activeTab === 'payments'" class="ellipsis" :title="it.project_desc">{{ it.project_desc }}</td>
              <td v-if="activeTab === 'payments'" class="ellipsis">{{ it.payee }}</td>
              <td v-if="activeTab === 'records'" class="ellipsis" :title="it.short_name || it.customer_name">{{ it.short_name || it.customer_name }}</td>
              <td v-if="activeTab === 'records'" class="mono">{{ it.operation_date || (it.operation_year + '-' + String(it.operation_month).padStart(2, '0')) }}</td>
              <td v-if="activeTab === 'records'" class="mono">{{ it.outstanding_amount }}</td>
              <td class="mono">{{ activeTab === 'approvals' ? it.amount : (activeTab === 'records' ? it.estimated_amount : it.total_amount) }}</td>
              <td class="mono muted">{{ fmtDate(it.deleted_at) }}</td>
              <td class="muted">{{ it.deleted_by_name || '-' }}</td>
            </tr>
          </tbody>
        </table>
        </div>
        <div class="trash-footer">
          <span class="trash-count">共 {{ total }} 条</span>
          <Pager v-model:page="page" v-model:size="size" :total="total" storage-key="trash" @change="load()" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.trash-page { padding: 24px; max-width: 1100px; }
.trash-header { display: flex; align-items: center; gap: 16px; margin-bottom: 6px; flex-wrap: wrap; }
.trash-title { display: flex; align-items: center; gap: 8px; font-size: 20px; font-weight: 700; color: var(--text); }
.trash-tabs { display: flex; gap: 4px; background: rgba(0,0,0,0.05); border-radius: 10px; padding: 3px; }
.ttab { border: none; background: none; padding: 5px 16px; border-radius: 8px; font-size: 13px; font-weight: 600;
  color: var(--muted); cursor: pointer; transition: all 0.16s; }
.ttab.active { background: var(--row-bg); color: var(--text); box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
.trash-dept { height: 32px; padding: 0 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--row-bg); font-size: 13px; color: var(--text); cursor: pointer; }
.trash-dept:focus { outline: none; border-color: var(--primary); }
.trash-actions { display: flex; gap: 8px; margin-left: auto; }
.tact-btn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 8px;
  font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all 0.16s; }
.tact-btn:disabled { opacity: .45; cursor: default; }
.tact-btn.restore { background: var(--c-success-bg); color: var(--c-success); border: 1px solid var(--c-success-bdr); }
.tact-btn.restore:hover:not(:disabled) { background: var(--c-success); color: #fff; }
.tact-btn.purge { background: var(--c-danger-bg); color: var(--c-danger); border: 1px solid var(--c-danger-bdr); }
.tact-btn.purge:hover:not(:disabled) { background: var(--c-danger); color: #fff; }

.trash-hint { font-size: 12.5px; color: var(--muted); margin-bottom: 16px; }
.trash-selcount { font-size: 12.5px; color: var(--text-2); font-weight: 600; align-self: center; margin-right: 2px; }
.trash-selbar {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 12.5px; color: var(--text-2); margin: -6px 0 14px;
  background: rgba(201,99,66,0.06); border: 1px solid rgba(201,99,66,0.2);
  border-radius: 9px; padding: 8px 14px;
}
.trash-selbar b { color: var(--primary); }
.trash-selink { border: none; background: none; color: var(--primary); font-weight: 700;
  font-size: 12.5px; cursor: pointer; padding: 0; text-decoration: underline; }
.trash-selink:hover { color: var(--primary-dark); }
.trash-card { background: rgba(255,253,250,0.90); border-radius: var(--radius); border: 1px solid rgba(255,255,255,0.65);
  box-shadow: 0 2px 12px rgba(100,60,30,0.09); overflow-x: auto; }
@media (max-width: 768px) {
  .trash-page { padding: 14px; }
  .trash-header { gap: 10px; }
  .trash-actions { width: 100%; margin-left: 0; }
}

.trash-loading, .trash-empty { text-align: center; padding: 60px 20px; color: var(--muted); }
.trash-empty { display: flex; flex-direction: column; align-items: center; gap: 12px; }
.trash-empty p { font-size: 14px; }

.trash-tbl { width: 100%; border-collapse: collapse; table-layout: auto; }
.trash-tbl th, .trash-tbl td { padding: var(--td-py) var(--td-px); font-size: var(--td-fs); border-bottom: 1px solid var(--border-soft);
  text-align: left; white-space: nowrap; }
.trash-tbl th { background: #f4f1ef; font-weight: 600; font-size: 12px; color: var(--text-2); }
.trash-tbl tr:last-child td { border-bottom: none; }
.trash-tbl tr.row-sel td { background: rgba(201,99,66,0.06); }
.sel-col { width: 34px; text-align: center !important; }
.ellipsis { max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.mono { font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); font-size: 12px; }

.trash-footer { display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; background: rgba(0,0,0,0.02); border-top: 1px solid var(--border-soft); }
.trash-count { font-size: 12.5px; color: var(--muted); }
.trash-pg { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.trash-pg button { padding: 3px 10px; border: 1px solid var(--border); border-radius: 6px; background: none;
  cursor: pointer; font-size: 12.5px; }
.trash-pg button:disabled { opacity: .4; cursor: default; }
</style>
