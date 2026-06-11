<script setup>
import { ref, reactive, onMounted } from 'vue'
import api from '../api/index.js'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = 50
const loading = ref(false)
const pruning = ref(false)
const expanded = ref({})
const filters = reactive({ q: '', module: '', method: '', result: '', date_start: '', date_end: '' })
let qTimer = null

const MODULES = [
  { key: '', label: '全部模块' },
  { key: 'paikuan', label: '排款/用户/权限' },
  { key: 'ar', label: '应收' },
  { key: 'caiwu', label: '财务分析' },
]
const METHODS = ['', 'POST', 'PUT', 'PATCH', 'DELETE']

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const res = await api.get('/audit-logs', { params: { ...filters, page: page.value, size } })
    items.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }
}
function onSearch() {
  clearTimeout(qTimer)
  qTimer = setTimeout(() => load(true), 300)
}
async function prune() {
  if (!confirm('将删除 180 天前的审计日志，确定？')) return
  pruning.value = true
  try {
    const res = await api.post('/audit-logs/prune', { keep_days: 180 })
    alert(`已清理 ${res.data.deleted} 条历史日志`)
    await load(true)
  } catch (e) { alert(e?.msg || '清理失败') }
  finally { pruning.value = false }
}
function toggleExpand(id) { expanded.value[id] = !expanded.value[id] }
const fmtTime = t => t ? t.replace('T', ' ').slice(0, 19) : '—'
const methodClass = m => ({ POST: 'm-post', PUT: 'm-put', PATCH: 'm-put', DELETE: 'm-del' }[m] || '')
// 把接口路径翻译成人话，便于非技术人员看懂
const PATH_LABELS = [
  [/\/ar\/projects\/import/, '导入项目'], [/\/ar\/projects\/export/, '导出项目'],
  [/\/ar\/projects\/bulk-delete/, '批量删除项目'], [/\/ar\/projects\/\d+/, '编辑/删除项目'],
  [/\/ar\/projects/, '新增项目'],
  [/\/ar\/customers\/sync-from-projects/, '同步客户'], [/\/ar\/customers\/bulk-tag-level/, '批量标客户等级'],
  [/\/ar\/customers\/\d+/, '编辑/删除客户'], [/\/ar\/customers/, '新增客户'],
  [/\/ar\/records\/collection\/dunning/, '生成催款任务'],
  [/\/ar\/records\/import/, '导入应收'], [/\/ar\/records\/bulk-delete/, '批量删除应收'],
  [/\/ar\/records\/batch-assign/, '设置开票批次'], [/\/ar\/records\/recompute/, '重算应收'],
  [/\/ar\/records\/\d+\/payments\/\d+/, '编辑/删除回款'], [/\/ar\/records\/\d+\/payments/, '录入回款'],
  [/\/ar\/records\/\d+/, '编辑/删除应收'], [/\/ar\/records/, '新增应收'],
  [/\/ar\/advances\/\d+\/writeoffs/, '核销预收预付'], [/\/ar\/advances\/import/, '导入预收预付'],
  [/\/ar\/advances\/\d+/, '编辑/删除预收预付'], [/\/ar\/advances/, '新增预收预付'],
  [/\/ar\/actions\/from-signal/, '信号转行动项'], [/\/ar\/actions\/\d+/, '更新行动项'], [/\/ar\/actions/, '新增行动项'],
  [/\/ar\/budget/, '收付款预算'], [/\/ar\/suppliers/, '供应商维护'], [/\/ar\/contracts/, '合同维护'],
  [/\/pk\/payments\/import/, '导入排款'], [/\/pk\/payments\/\d+/, '编辑/删除排款'], [/\/pk\/payments/, '新增排款'],
  [/\/pk\/approvals/, '审批管理'], [/\/pk\/login/, '登录'], [/\/pk\/register/, '注册'],
  [/\/pk\/users\/\d+\/approve/, '审批用户'], [/\/pk\/users\/\d+\/reject/, '驳回用户'],
  [/\/pk\/users\/\d+/, '编辑/删除用户'],
  [/\/pk\/permissions/, '权限配置'], [/\/pk\/audit-logs\/prune/, '清理审计日志'],
  [/\/cw\//, '财务分析操作'],
]
function pathLabel(path) {
  for (const [re, label] of PATH_LABELS) if (re.test(path)) return label
  return ''
}
onMounted(() => load())
</script>

<template>
  <div>
    <div class="topbar">
      <div class="topbar-left"><h1>审计日志</h1>
        <span class="audit-sub">系统自动记录的全部写操作（谁 / 何时 / 做了什么 / 结果），共 {{ total }} 条</span>
      </div>
      <div class="ctrl-row">
        <button class="btn btn-ghost btn-sm" :disabled="pruning" @click="prune">🧹 清理180天前</button>
      </div>
    </div>

    <div class="card">
      <div class="filter-strip">
        <input v-model="filters.q" placeholder="搜操作人 / 接口路径" class="search-input" @input="onSearch" />
        <select v-model="filters.module" class="sel-bu" @change="load(true)">
          <option v-for="m in MODULES" :key="m.key" :value="m.key">{{ m.label }}</option>
        </select>
        <select v-model="filters.method" class="sel-bu" @change="load(true)">
          <option v-for="m in METHODS" :key="m" :value="m">{{ m || '全部方法' }}</option>
        </select>
        <select v-model="filters.result" class="sel-bu" @change="load(true)">
          <option value="">全部结果</option>
          <option value="ok">成功</option>
          <option value="fail">失败/被拒</option>
        </select>
        <input v-model="filters.date_start" type="date" class="sel-mo" @change="load(true)" />
        <span style="color:var(--muted)">~</span>
        <input v-model="filters.date_end" type="date" class="sel-mo" @change="load(true)" />
      </div>

      <div class="table-wrap" style="margin-top:12px">
        <table class="audit-table">
          <thead>
            <tr>
              <th class="ctr">时间</th>
              <th>操作人</th>
              <th class="ctr">操作</th>
              <th>接口</th>
              <th class="ctr">模块</th>
              <th class="ctr">结果</th>
              <th class="ctr">来源IP</th>
              <th class="ctr">参数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length"><td colspan="8" class="empty-cell">⏳ 加载中…</td></tr>
            <tr v-else-if="!items.length"><td colspan="8" class="empty-cell">暂无审计记录</td></tr>
            <template v-for="l in items" :key="l.id">
              <tr class="data-row">
                <td class="ctr time-cell">{{ fmtTime(l.created_at) }}</td>
                <td class="fw">{{ l.user_name || '（未登录）' }}</td>
                <td class="ctr">
                  <span class="method-badge" :class="methodClass(l.method)">{{ l.method }}</span>
                  <span v-if="pathLabel(l.path)" class="op-label">{{ pathLabel(l.path) }}</span>
                </td>
                <td class="path-cell">{{ l.path }}</td>
                <td class="ctr"><span class="mod-chip">{{ l.module || '—' }}</span></td>
                <td class="ctr">
                  <span class="st-badge" :class="l.status_code < 400 ? 'st-ok' : 'st-fail'">{{ l.status_code }}</span>
                </td>
                <td class="ctr ip-cell">{{ l.ip || '—' }}</td>
                <td class="ctr">
                  <button v-if="l.payload && Object.keys(l.payload).length" class="exp-btn" @click="toggleExpand(l.id)">
                    {{ expanded[l.id] ? '收起' : '查看' }}
                  </button>
                  <span v-else class="time-cell">—</span>
                </td>
              </tr>
              <tr v-if="expanded[l.id]" class="payload-row">
                <td colspan="8"><pre class="payload-pre">{{ JSON.stringify(l.payload, null, 2) }}</pre></td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
        <span class="page-info">{{ page }} / {{ Math.ceil(total / size) }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.audit-sub { font-size: 12px; color: var(--muted); margin-left: 12px; }
.filter-strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.search-input { padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; width: 200px; }
.sel-bu, .sel-mo { padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; background: #fff; }
.table-wrap { overflow-x: auto; }
.audit-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.audit-table th { background: var(--th-bg, #f6f3ef); color: var(--muted); padding: 8px 10px; font-weight: 600; text-align: left; white-space: nowrap; }
.audit-table th.ctr, .audit-table td.ctr { text-align: center; }
.audit-table td { padding: 7px 10px; border-bottom: 1px solid var(--border); }
.data-row:hover { background: rgba(0,0,0,0.018); }
.empty-cell { text-align: center; color: var(--muted); padding: 32px 0; }
.fw { font-weight: 600; }
.time-cell, .ip-cell { font-size: 12px; color: var(--muted); white-space: nowrap; }
.path-cell { font-family: ui-monospace, monospace; font-size: 12px; color: var(--text); word-break: break-all; }
.method-badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; }
.m-post { background: rgba(21,101,192,0.1); color: #1565c0; }
.m-put { background: rgba(230,81,0,0.1); color: #e65100; }
.m-del { background: rgba(198,40,40,0.1); color: #c62828; }
.op-label { display: block; font-size: 11px; color: var(--muted); margin-top: 2px; white-space: nowrap; }
.mod-chip { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: rgba(0,0,0,0.05); color: var(--muted); }
.st-badge { font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.st-ok { background: rgba(46,125,50,0.1); color: #2e7d32; }
.st-fail { background: rgba(198,40,40,0.12); color: #c62828; }
.exp-btn { padding: 2px 10px; border: 1px solid var(--border); border-radius: 6px; background: #fff; font-size: 12px; cursor: pointer; color: var(--text); }
.exp-btn:hover { border-color: #1565c0; color: #1565c0; }
.payload-row td { background: rgba(0,0,0,0.02); }
.payload-pre { margin: 0; font-size: 12px; max-height: 280px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
.pagination { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 14px; }
.page-btn { padding: 5px 12px; border: 1px solid var(--border); border-radius: 8px; background: #fff; font-size: 13px; cursor: pointer; }
.page-btn:disabled { opacity: .4; cursor: default; }
.page-info { font-size: 13px; color: var(--muted); }
</style>
