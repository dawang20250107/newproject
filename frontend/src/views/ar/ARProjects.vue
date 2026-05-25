<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const size = 50

const filters = reactive({ q: '', dept: '', manager: '', is_shared: '' })
const showModal = ref(false)
const editItem = ref(null)
const showExtra = ref(false)
const saving = ref(false)
const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)

const form = reactive({
  contract_name: '', short_name: '', delivery_dept: '', sub_dept: '',
  business_mode: '', customer_level: '', sales_contact: '', project_manager: '',
  has_contract: '无', contract_date: '', reconciliation_days: 0,
  invoice_wait_days: 0, settlement_wait_days: 0, invoice_mode: '全额',
  invoice_type: '专票', tax_rate: '0.06', notes: '',
})

const totalDays = computed(() =>
  (parseInt(form.reconciliation_days) || 0) +
  (parseInt(form.invoice_wait_days) || 0) +
  (parseInt(form.settlement_wait_days) || 0))

const isShared = computed(() =>
  form.sales_contact && form.project_manager &&
  form.sales_contact !== form.project_manager)

const accessibleDepts = computed(() =>
  auth.isSuperAdmin ? DEPARTMENTS : (auth.user?.departments || []).filter(d => DEPARTMENTS.includes(d)))

const stats = computed(() => {
  const total_outstanding = items.value.reduce((s, i) => s + (parseFloat(i.total_outstanding) || 0), 0)
  const shared = items.value.filter(i => i.is_shared).length
  return { total: total.value, total_outstanding, shared }
})

function fmtAmt(v) {
  const n = parseFloat(v) || 0
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toFixed(2)
}

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const res = await ar.listProjects({ ...filters, page: page.value, size })
    items.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}

function openCreate() {
  editItem.value = null; showExtra.value = false
  Object.assign(form, {
    contract_name: '', short_name: '', delivery_dept: accessibleDepts.value[0] || '',
    sub_dept: '', business_mode: '', customer_level: '',
    sales_contact: '', project_manager: '', has_contract: '无', contract_date: '',
    reconciliation_days: 0, invoice_wait_days: 0, settlement_wait_days: 0,
    invoice_mode: '全额', invoice_type: '专票', tax_rate: '0.06', notes: '',
  })
  showModal.value = true
}

function openEdit(item) {
  editItem.value = item; showExtra.value = false
  Object.assign(form, {
    contract_name: item.contract_name, short_name: item.short_name,
    delivery_dept: item.delivery_dept, sub_dept: item.sub_dept,
    business_mode: item.business_mode, customer_level: item.customer_level,
    sales_contact: item.sales_contact, project_manager: item.project_manager,
    has_contract: item.has_contract, contract_date: item.contract_date || '',
    reconciliation_days: item.reconciliation_days,
    invoice_wait_days: item.invoice_wait_days,
    settlement_wait_days: item.settlement_wait_days,
    invoice_mode: item.invoice_mode, invoice_type: item.invoice_type,
    tax_rate: item.tax_rate, notes: item.notes,
  })
  showModal.value = true
}

async function save() {
  if (!form.contract_name || !form.delivery_dept || !form.sales_contact || !form.project_manager) {
    alert('请填写必填字段（合同名称、交付部门、销售对接人、项目负责人）'); return
  }
  saving.value = true
  try {
    if (editItem.value) await ar.updateProject(editItem.value.id, form)
    else await ar.createProject(form)
    showModal.value = false
    await load()
  } catch (e) {
    alert(e?.response?.data?.msg || '保存失败')
  } finally { saving.value = false }
}

async function remove(item) {
  if (!confirm(`确定删除项目「${item.short_name || item.contract_name}」？`)) return
  try { await ar.deleteProject(item.id); await load() }
  catch (e) { alert(e?.response?.data?.msg || '删除失败') }
}

async function downloadTemplate() {
  const res = await ar.projectTemplate()
  const url = URL.createObjectURL(res)
  const a = document.createElement('a'); a.href = url; a.download = '项目信息导入模板.xlsx'; a.click()
  URL.revokeObjectURL(url)
}

async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importProjects(fd); const d = res.data
    alert(`导入完成：创建 ${d.created} 条${d.errors?.length ? `，错误 ${d.errors.length} 条` : ''}`)
    await load()
  } catch (e) { alert(e?.response?.data?.msg || '导入失败')
  } finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportProjects(filters)
    const url = URL.createObjectURL(res)
    const a = document.createElement('a'); a.href = url; a.download = '项目信息.xlsx'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { alert(e?.response?.data?.msg || '导出失败')
  } finally { exporting.value = false }
}

onMounted(load)
</script>

<template>
  <div>
    <!-- Header -->
    <div class="topbar">
      <div>
        <h1>项目台账</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">管理应收账款关联项目 · 合同账期 · 开票配置</div>
      </div>
      <div class="ctrl-row" style="flex-wrap:wrap">
        <input v-model="filters.q" placeholder="搜索编号 / 合同 / 负责人" class="search-input" @input="load(true)" />
        <select v-model="filters.dept" class="sel-bu" @change="load(true)">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="filters.is_shared" class="sel-mo" @change="load(true)">
          <option value="">全部</option>
          <option value="true">共享业务</option>
          <option value="false">非共享</option>
        </select>
      </div>
    </div>

    <!-- Stats strip -->
    <div class="stats-strip">
      <div class="stat-pill">
        <div class="stat-label">项目总数</div>
        <div class="stat-value">{{ stats.total }}</div>
      </div>
      <div class="stat-pill stat-pill-warn">
        <div class="stat-label">未回款合计</div>
        <div class="stat-value">{{ fmtAmt(stats.total_outstanding) }}</div>
      </div>
      <div class="stat-pill stat-pill-purple">
        <div class="stat-label">共享业务</div>
        <div class="stat-value">{{ stats.shared }}</div>
      </div>
      <div class="stat-actions">
        <button class="act-btn" @click="downloadTemplate" title="下载模板">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          下载模板
        </button>
        <label class="act-btn" style="cursor:pointer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          {{ importing ? '导入中…' : '导入' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" :disabled="importing" />
        </label>
        <button class="act-btn" :disabled="exporting" @click="exportData">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          {{ exporting ? '导出中…' : '导出' }}
        </button>
        <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="margin-right:4px"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新增项目
        </button>
      </div>
    </div>

    <!-- Table card -->
    <div class="card" :class="{ 'card-loading': loading && items.length }">
      <div class="table-wrap">
        <table class="proj-table">
          <thead>
            <tr>
              <th>项目编号</th>
              <th>合同名称</th>
              <th>事业部</th>
              <th>负责人</th>
              <th>销售</th>
              <th class="ctr">总账期</th>
              <th class="ctr">开票</th>
              <th class="ctr">应收笔数</th>
              <th class="amt">未回款</th>
              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length">
              <td colspan="10" class="empty-cell"><div class="empty-inner">⏳ 加载中…</div></td>
            </tr>
            <tr v-else-if="!items.length">
              <td colspan="10" class="empty-cell"><div class="empty-inner">暂无项目数据，点击「新增项目」开始</div></td>
            </tr>
            <tr v-for="item in items" :key="item.id" class="data-row">
              <td><span class="proj-no-tag">{{ item.project_no }}</span></td>
              <td>
                <div class="contract-name">{{ item.contract_name }}</div>
                <div v-if="item.short_name" class="short-name">{{ item.short_name }}</div>
              </td>
              <td><span class="dept-chip">{{ item.delivery_dept }}</span></td>
              <td class="person">{{ item.project_manager }}</td>
              <td class="person">
                {{ item.sales_contact }}
                <span v-if="item.is_shared" class="badge-shared">共享</span>
              </td>
              <td class="ctr">
                <span class="days-chip">{{ item.total_days }}天</span>
              </td>
              <td class="ctr">
                <span class="invoice-mode" :class="item.invoice_mode === '全额' ? 'mode-full' : 'mode-diff'">{{ item.invoice_mode }}</span>
              </td>
              <td class="ctr">
                <span class="count-badge">{{ item.record_count || 0 }}</span>
              </td>
              <td class="amt">
                <span :class="parseFloat(item.total_outstanding) > 0 ? 'amount-warn' : 'amount-zero'">
                  {{ parseFloat(item.total_outstanding) > 0 ? fmtAmt(item.total_outstanding) : '—' }}
                </span>
              </td>
              <td class="ctr">
                <div class="row-actions">
                  <button class="icon-btn" @click="openEdit(item)" title="编辑">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button v-if="auth.canDelete" class="icon-btn icon-btn-danger" @click="remove(item)" title="删除">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
        <span class="page-info">第 {{ page }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
      </div>
    </div>

    <!-- Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
        <div class="modal-box" style="max-width:700px">
          <div class="modal-header">
            <div>
              <h3>{{ editItem ? '编辑项目' : '新增项目' }}</h3>
              <div class="modal-subtitle">{{ editItem ? editItem.project_no : '编号将自动生成' }}</div>
            </div>
            <button class="modal-close" @click="showModal = false">✕</button>
          </div>

          <!-- Derived info bar -->
          <div class="derived-bar">
            <div class="derived-item">
              <span class="derived-label">总账期</span>
              <span class="derived-value">{{ totalDays }} 天</span>
            </div>
            <div class="derived-item" v-if="form.reconciliation_days">
              <span class="derived-label">对账期</span>
              <span class="derived-value">{{ form.reconciliation_days }}d</span>
            </div>
            <div class="derived-item" v-if="form.invoice_wait_days">
              <span class="derived-label">开票等待</span>
              <span class="derived-value">{{ form.invoice_wait_days }}d</span>
            </div>
            <div class="derived-item" v-if="form.settlement_wait_days">
              <span class="derived-label">结算等待</span>
              <span class="derived-value">{{ form.settlement_wait_days }}d</span>
            </div>
            <span v-if="isShared" class="badge-shared" style="font-size:12px;padding:3px 10px">共享业务</span>
          </div>

          <div class="modal-body">
            <div class="form-section-title">基本信息</div>
            <div class="form-grid">
              <label class="form-field span2">
                <span>合同名称 <em>*</em></span>
                <input v-model="form.contract_name" placeholder="请输入合同全称" />
              </label>
              <label class="form-field">
                <span>项目简称</span>
                <input v-model="form.short_name" placeholder="可选，显示在明细中" />
              </label>
              <label class="form-field">
                <span>交付部门 <em>*</em></span>
                <select v-model="form.delivery_dept">
                  <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>销售对接人 <em>*</em></span>
                <input v-model="form.sales_contact" />
              </label>
              <label class="form-field">
                <span>项目负责人 <em>*</em></span>
                <input v-model="form.project_manager" />
              </label>
            </div>

            <div class="form-section-title" style="margin-top:20px">账期与开票</div>
            <div class="form-grid">
              <label class="form-field">
                <span>合同对账期（天）</span>
                <input v-model.number="form.reconciliation_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>开票等待期（天）</span>
                <input v-model.number="form.invoice_wait_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>结算等待期（天）</span>
                <input v-model.number="form.settlement_wait_days" type="number" min="0" />
              </label>
              <label class="form-field">
                <span>开票模式</span>
                <select v-model="form.invoice_mode">
                  <option>全额</option><option>差额</option>
                </select>
              </label>
              <label class="form-field">
                <span>税率（如 0.06 = 6%）</span>
                <input v-model="form.tax_rate" placeholder="0.06" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="form.notes" />
              </label>
            </div>

            <div class="extra-toggle" @click="showExtra = !showExtra">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" :style="showExtra ? 'transform:rotate(90deg)' : ''"><path d="M9 18l6-6-6-6"/></svg>
              {{ showExtra ? '收起次要信息' : '展开次要信息（部门 / 业务类型 / 合同）' }}
            </div>
            <div v-show="showExtra" class="form-grid" style="margin-top:10px">
              <label class="form-field">
                <span>二级部门</span>
                <input v-model="form.sub_dept" />
              </label>
              <label class="form-field">
                <span>业务模式</span>
                <input v-model="form.business_mode" />
              </label>
              <label class="form-field">
                <span>客户等级</span>
                <input v-model="form.customer_level" />
              </label>
              <label class="form-field">
                <span>有无合同</span>
                <select v-model="form.has_contract"><option>有</option><option>无</option></select>
              </label>
              <label class="form-field">
                <span>签订日期</span>
                <input v-model="form.contract_date" type="date" />
              </label>
              <label class="form-field">
                <span>发票类型</span>
                <select v-model="form.invoice_type">
                  <option value="">不限</option><option>专票</option><option>普票</option>
                </select>
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存项目' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* Stats strip */
.stats-strip {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-bottom: 16px;
}
.stat-pill {
  display: flex; flex-direction: column; gap: 2px;
  padding: 10px 20px; border-radius: 12px;
  background: rgba(255,255,255,0.7); border: 1px solid rgba(255,255,255,0.8);
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  backdrop-filter: blur(10px);
  min-width: 90px;
}
.stat-pill-warn { border-left: 3px solid #f57f17; }
.stat-pill-purple { border-left: 3px solid #6a1b9a; }
.stat-label { font-size: 11px; color: var(--muted); font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; }
.stat-value { font-size: 20px; font-weight: 700; color: var(--text); line-height: 1.2; }
.stat-actions { display: flex; gap: 6px; align-items: center; margin-left: auto; flex-wrap: wrap; }
.act-btn {
  display: flex; align-items: center; gap: 5px;
  padding: 7px 13px; border-radius: 8px; font-size: 12.5px; font-weight: 500;
  border: 1px solid var(--border); background: rgba(255,252,250,0.8); color: var(--muted);
  cursor: pointer; transition: all 0.15s; white-space: nowrap;
}
.act-btn:hover { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.07); }
.act-btn:disabled { opacity: 0.45; cursor: default; }

/* Table */
.card-loading { opacity: 0.7; pointer-events: none; }
.proj-table { width: 100%; }
.proj-table th { font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); padding: 10px 12px; }
.proj-table td { padding: 11px 12px; vertical-align: middle; }
.proj-table .data-row { transition: background 0.12s; }
.proj-table .data-row:hover { background: rgba(201,99,66,0.04); }
.proj-table .data-row:not(:last-child) td { border-bottom: 1px solid rgba(0,0,0,0.04); }

.empty-cell { padding: 48px !important; text-align: center; }
.empty-inner { color: var(--muted); font-size: 14px; }

.proj-no-tag { font-family: monospace; font-size: 11.5px; color: var(--muted); background: rgba(0,0,0,0.04); padding: 2px 7px; border-radius: 5px; }
.contract-name { font-weight: 600; font-size: 13.5px; color: var(--text); }
.short-name { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.dept-chip { font-size: 11.5px; padding: 2px 9px; border-radius: 10px; background: rgba(201,99,66,0.1); color: var(--primary); font-weight: 600; }
.person { font-size: 13px; color: var(--text); }
.badge-shared { font-size: 10px; padding: 1px 7px; border-radius: 8px; background: rgba(106,27,154,0.1); color: #6a1b9a; font-weight: 600; margin-left: 5px; }
.days-chip { font-size: 12px; padding: 2px 8px; border-radius: 8px; background: rgba(21,101,192,0.08); color: #1565c0; font-weight: 600; }
.invoice-mode { font-size: 12px; padding: 2px 8px; border-radius: 8px; font-weight: 600; }
.mode-full { background: rgba(46,125,50,0.1); color: #2e7d32; }
.mode-diff { background: rgba(245,127,23,0.1); color: #f57f17; }
.count-badge { font-size: 13px; font-weight: 700; color: var(--text); }
.amount-warn { color: #e65100; font-weight: 700; font-size: 13.5px; }
.amount-zero { color: var(--muted); }
.ctr { text-align: center; }
.amt { text-align: right; }

.row-actions { display: flex; gap: 4px; justify-content: center; }
.icon-btn {
  width: 28px; height: 28px; border-radius: 7px; border: 1px solid var(--border);
  background: rgba(255,252,250,0.7); display: flex; align-items: center; justify-content: center;
  color: var(--muted); cursor: pointer; transition: all 0.14s;
}
.icon-btn:hover { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.08); }
.icon-btn-danger:hover { border-color: var(--danger); color: var(--danger); background: rgba(198,40,40,0.07); }

.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 16px 0 4px; }
.page-btn { padding: 5px 14px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,252,250,0.7); color: var(--text); font-size: 13px; cursor: pointer; transition: all 0.14s; }
.page-btn:hover { border-color: var(--primary); color: var(--primary); }
.page-btn:disabled { opacity: 0.35; cursor: default; }
.page-info { font-size: 13px; color: var(--muted); }

/* Modal */
.modal-subtitle { font-size: 12px; color: var(--muted); margin-top: 3px; font-family: monospace; }
.derived-bar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 12px 20px; background: linear-gradient(135deg, rgba(201,99,66,0.06), rgba(201,99,66,0.02));
  border-bottom: 1px solid rgba(201,99,66,0.1);
}
.derived-item { display: flex; align-items: baseline; gap: 5px; }
.derived-label { font-size: 11px; color: var(--muted); font-weight: 500; }
.derived-value { font-size: 16px; font-weight: 700; color: var(--primary); }
.form-section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.extra-toggle {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 12.5px; color: var(--primary); cursor: pointer; margin: 12px 0 4px;
  user-select: none; padding: 4px 8px; border-radius: 6px; transition: background 0.14s;
}
.extra-toggle:hover { background: rgba(201,99,66,0.08); }
.search-input { padding: 7px 12px; border: 1px solid var(--border); border-radius: 9px; font-size: 13px; min-width: 220px; background: rgba(255,252,250,0.8); }
</style>
