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
    const res = await ar.listProjects({
      ...filters, page: page.value, size,
    })
    items.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false }
}

function openCreate() {
  editItem.value = null
  showExtra.value = false
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
  editItem.value = item
  showExtra.value = false
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
    alert('请填写必填字段（合同名称、交付部门、销售对接人、项目负责人）')
    return
  }
  saving.value = true
  try {
    if (editItem.value) {
      await ar.updateProject(editItem.value.id, form)
    } else {
      await ar.createProject(form)
    }
    showModal.value = false
    await load()
  } catch (e) {
    alert(e?.response?.data?.msg || '保存失败')
  } finally {
    saving.value = false }
}

async function remove(item) {
  if (!confirm(`确定删除项目「${item.short_name || item.contract_name}」？`)) return
  try {
    await ar.deleteProject(item.id)
    await load()
  } catch (e) {
    alert(e?.response?.data?.msg || '删除失败')
  }
}

async function downloadTemplate() {
  const res = await ar.projectTemplate()
  const url = URL.createObjectURL(res)
  const a = document.createElement('a'); a.href = url; a.download = '项目信息导入模板.xlsx'; a.click()
  URL.revokeObjectURL(url)
}

async function handleImport(e) {
  const f = e.target.files?.[0]
  if (!f) return
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importProjects(fd)
    const d = res.data
    alert(`导入完成：创建 ${d.created} 条${d.errors?.length ? `，错误 ${d.errors.length} 条` : ''}`)
    if (d.errors?.length) console.warn('Import errors:', d.errors)
    await load()
  } catch (e) {
    alert(e?.response?.data?.msg || '导入失败')
  } finally {
    importing.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportProjects(filters)
    const url = URL.createObjectURL(res)
    const a = document.createElement('a'); a.href = url; a.download = '项目信息.xlsx'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert(e?.response?.data?.msg || '导出失败')
  } finally {
    exporting.value = false }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar">
      <h1>项目台账</h1>
      <div class="ctrl-row">
        <input v-model="filters.q" placeholder="搜索编号/合同名/负责人" class="search-input" @input="load(true)" />
        <select v-model="filters.dept" class="sel-bu" @change="load(true)">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="filters.is_shared" class="sel-mo" @change="load(true)">
          <option value="">全部</option>
          <option value="true">共享业务</option>
          <option value="false">非共享</option>
        </select>
        <div class="ctrl-sep"></div>
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate">下载模板</button>
        <label class="btn btn-ghost btn-sm" style="cursor:pointer">
          {{ importing ? '导入中…' : '导入Excel' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" :disabled="importing" />
        </label>
        <button class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportData">{{ exporting ? '导出中…' : '导出Excel' }}</button>
        <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增项目</button>
      </div>
    </div>

    <div class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>项目编号</th>
              <th>合同名称</th>
              <th>项目简称</th>
              <th>交付部门</th>
              <th>项目负责人</th>
              <th>销售对接人</th>
              <th>总账期</th>
              <th>开票模式</th>
              <th class="amt">应收笔数</th>
              <th class="amt">未回款合计</th>
              <th style="width:100px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length">
              <td colspan="11" style="text-align:center;padding:40px;color:var(--muted)">加载中…</td>
            </tr>
            <tr v-else-if="!items.length">
              <td colspan="11" style="text-align:center;padding:40px;color:var(--muted)">暂无项目数据</td>
            </tr>
            <tr v-for="item in items" :key="item.id" :class="{ 'data-reloading': loading }">
              <td><span class="project-no">{{ item.project_no }}</span></td>
              <td>{{ item.contract_name }}</td>
              <td>{{ item.short_name }}</td>
              <td>{{ item.delivery_dept }}</td>
              <td>{{ item.project_manager }}</td>
              <td>
                {{ item.sales_contact }}
                <span v-if="item.is_shared" class="badge badge-shared">共享</span>
              </td>
              <td>{{ item.total_days }}天</td>
              <td>{{ item.invoice_mode }}</td>
              <td class="amt">{{ item.record_count }}</td>
              <td class="amt" :class="parseFloat(item.total_outstanding) > 0 ? 'text-warning' : ''">
                {{ fmtAmt(item.total_outstanding) }}
              </td>
              <td>
                <button class="btn-link" @click="openEdit(item)">编辑</button>
                <span v-if="auth.canDelete"> · </span>
                <button v-if="auth.canDelete" class="btn-link btn-link-danger" @click="remove(item)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <!-- Pagination -->
      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" @click="page--; load()">上一页</button>
        <span>第 {{ page }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" @click="page++; load()">下一页</button>
      </div>
    </div>

    <!-- Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
        <div class="modal-box" style="max-width:680px">
          <div class="modal-header">
            <h3>{{ editItem ? '编辑项目' : '新增项目' }}</h3>
            <button class="modal-close" @click="showModal = false">✕</button>
          </div>
          <div class="modal-body">
            <!-- Derived fields -->
            <div v-if="editItem" class="form-derived">
              <span>编号：<b>{{ editItem.project_no }}</b></span>
              <span>总账期：<b>{{ totalDays }}</b> 天</span>
              <span v-if="isShared" class="badge badge-shared">共享业务</span>
            </div>
            <div v-else class="form-derived">
              <span>总账期：<b>{{ totalDays }}</b> 天</span>
              <span v-if="isShared" class="badge badge-shared">共享业务</span>
            </div>

            <!-- Primary fields -->
            <div class="form-grid">
              <label class="form-field span2">
                <span>合同名称 <em>*</em></span>
                <input v-model="form.contract_name" placeholder="必填" />
              </label>
              <label class="form-field">
                <span>项目简称</span>
                <input v-model="form.short_name" placeholder="可选" />
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
                <span>税率（如 0.06）</span>
                <input v-model="form.tax_rate" placeholder="0.06" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="form.notes" />
              </label>
            </div>

            <!-- Extra fields (collapsible) -->
            <div class="extra-toggle" @click="showExtra = !showExtra">
              {{ showExtra ? '▾ 收起次要信息' : '▸ 展开次要信息（部门/业务/等级/合同）' }}
            </div>
            <div v-show="showExtra" class="form-grid" style="margin-top:8px">
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
                <select v-model="form.has_contract">
                  <option>有</option><option>无</option>
                </select>
              </label>
              <label class="form-field">
                <span>签订日期</span>
                <input v-model="form.contract_date" type="date" />
              </label>
              <label class="form-field">
                <span>专票/普票</span>
                <select v-model="form.invoice_type">
                  <option value="">不限</option>
                  <option>专票</option><option>普票</option>
                </select>
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save">
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.search-input { padding: 6px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; min-width: 200px; background: rgba(255,252,250,.7); }
.project-no { font-family: monospace; font-size: 12px; color: var(--muted); }
.badge-shared { background: rgba(106,27,154,.1); color: #6a1b9a; border: 1px solid rgba(106,27,154,.2); font-size:10px; padding: 1px 6px; border-radius:8px; margin-left:4px; }
.text-warning { color: #e65100; font-weight: 600; }
.btn-link { background: none; border: none; color: var(--primary); cursor: pointer; font-size: 13px; padding: 2px 4px; }
.btn-link-danger { color: var(--danger); }
.btn-link:hover { text-decoration: underline; }
.form-derived { display: flex; align-items: center; gap: 16px; padding: 8px 12px; background: rgba(255,253,250,.6); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 14px; font-size: 13px; flex-wrap: wrap; }
.extra-toggle { font-size: 12px; color: var(--primary); cursor: pointer; margin: 10px 0 4px; user-select: none; }
.extra-toggle:hover { text-decoration: underline; }
.pagination { display:flex; align-items:center; justify-content:center; gap:12px; padding:12px 0 4px; font-size:13px; color:var(--muted); }
.pagination button { padding:4px 12px; border:1px solid var(--border); border-radius:6px; background:rgba(255,252,250,.7); cursor:pointer; font-size:13px; }
.pagination button:disabled { opacity:.4; cursor:default; }
</style>
