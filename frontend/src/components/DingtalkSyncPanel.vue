<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import api from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import { confirmDlg, promptDlg } from '../composables/confirm.js'
import { resultDlg } from '../composables/bulkResult.js'
import { todayCST } from '../constants.js'

const emit = defineEmits(['synced'])
const toast = useToast()

// ── 连接自检（凭证/模板配置核对）────────────────────────────────────────────
const testing = ref(false)
const diag = ref(null)
async function testConnection() {
  testing.value = true
  try { diag.value = (await api.get('/dingtalk/test')).data }
  catch (e) { diag.value = { connected: false, error: e?.msg || e?.error || '请求失败' } }
  finally { testing.value = false }
}

// ── 查询条件 ──────────────────────────────────────────────────────────────
const personMode = ref('mobile')          // 'mobile' | 'name'
const personInput = ref('')
const resolving = ref(false)
const candidates = ref([])                 // 姓名命中的多个候选
const picked = ref(null)                   // { userid, name }
const status = ref('todo')                 // todo | done | originated
const STATUS = [
  { v: 'todo', l: '待处理' }, { v: 'done', l: '已处理' }, { v: 'originated', l: '该员工发起' },
]
function monthStart() { const d = todayCST(); return d.slice(0, 8) + '01' }
const range = reactive({ start: monthStart(), end: todayCST() })
const QUICK = [
  { k: 'month', l: '本月' }, { k: 'lastmonth', l: '上月' }, { k: 'q', l: '本季度' },
  { k: 'lastq', l: '上季度' }, { k: 'halfy', l: '近半年' }, { k: 'year', l: '本年' },
  { k: 'd7', l: '近7天' }, { k: 'd30', l: '近30天' }, { k: 'd90', l: '近90天' },
]
function ymd(d) { return d.toISOString().slice(0, 10) }
function setQuick(k) {
  const t = todayCST(); const [y, m] = t.split('-').map(Number)
  const back = (days) => { const d = new Date(t); d.setDate(d.getDate() - days); return ymd(d) }
  if (k === 'month') { range.start = `${t.slice(0, 8)}01`; range.end = t }
  else if (k === 'lastmonth') {
    const d = new Date(y, m - 2, 1); range.start = ymd(new Date(d.getTime() - d.getTimezoneOffset() * 60000))
    const e = new Date(y, m - 1, 0); range.end = ymd(new Date(e.getTime() - e.getTimezoneOffset() * 60000))
  }
  else if (k === 'q') { const qm = Math.floor((m - 1) / 3) * 3 + 1; range.start = `${y}-${String(qm).padStart(2, '0')}-01`; range.end = t }
  else if (k === 'lastq') {
    let qm = Math.floor((m - 1) / 3) * 3 + 1 - 3, yy = y
    if (qm <= 0) { qm += 12; yy -= 1 }
    range.start = `${yy}-${String(qm).padStart(2, '0')}-01`
    const e = new Date(yy, qm + 2, 0); range.end = ymd(new Date(e.getTime() - e.getTimezoneOffset() * 60000))
  }
  else if (k === 'halfy') { range.start = back(182); range.end = t }
  else if (k === 'year') { range.start = `${y}-01-01`; range.end = t }
  else if (k === 'd7') { range.start = back(7); range.end = t }
  else if (k === 'd30') { range.start = back(30); range.end = t }
  else if (k === 'd90') { range.start = back(90); range.end = t }
}

// ── 子页签：查询 / 模板 ─────────────────────────────────────────────────────
const subview = ref('query')   // 'query' | 'templates'

// ── 审批模板（企业全部表单，勾选后再查）─────────────────────────────────────────
// 走 /dingtalk/templates（userId 省略 → 钉钉返回企业下全部表单，覆盖报销等审批人
// 不可发起的模板）。开面板即加载，与选人解耦。财务相关模板默认预选。
const templates = ref([])          // [{process_code, name, dir_name}]
const tplSel = ref(new Set())      // 勾选的 process_code
const tplLoading = ref(false)
const tplErr = ref('')
const tplFilter = ref('')
const FINANCE_KW = /报销|付款|费用|请款|借款|备用金|采购|货款|结算|差旅|招待|电汇|打款/
const DEFAULT_TPL = '其他行政费用报销单'   // 默认只勾这一个
let _hasRestoredSel = false                // 有本地持久化选择时不套用默认
const tplShown = computed(() => {
  const q = tplFilter.value.trim()
  return q ? templates.value.filter(t => (t.name || t.process_code).includes(q)) : templates.value
})
// 按钉钉分组(dir_name)聚合展示
const tplGroups = computed(() => {
  const g = new Map()
  for (const t of tplShown.value) {
    const k = t.dir_name || '未分组'
    if (!g.has(k)) g.set(k, [])
    g.get(k).push(t)
  }
  return [...g.entries()].map(([dir, items]) => ({ dir, items }))
})
const tplSelCount = computed(() => tplSel.value.size)
async function loadTemplates() {
  if (templates.value.length || tplLoading.value) return
  tplLoading.value = true; tplErr.value = ''
  try {
    const r = await api.post('/dingtalk/templates', {}, { timeout: 60000 })
    templates.value = r.data?.templates || []
    if (!_hasRestoredSel) defaultSelect()   // 无持久化选择时才套默认
  } catch (e) { tplErr.value = e?.msg || e?.error || '获取模板失败' }
  finally { tplLoading.value = false }
}
// 默认只勾"其他行政费用报销单"；找不到则退而求其次勾第一个含"报销"的
function defaultSelect() {
  const t = templates.value.find(x => (x.name || '') === DEFAULT_TPL)
    || templates.value.find(x => (x.name || '').includes(DEFAULT_TPL))
    || templates.value.find(x => (x.name || '').includes('报销'))
  tplSel.value = new Set(t ? [t.process_code] : [])
}
function toggleTpl(code) {
  const s = new Set(tplSel.value)
  s.has(code) ? s.delete(code) : s.add(code)
  tplSel.value = s
}
function tplSelectAll(on) {
  tplSel.value = on ? new Set(tplShown.value.map(t => t.process_code)) : new Set()
}
function selectFinance() {
  tplSel.value = new Set(templates.value.filter(t => FINANCE_KW.test(t.name || '')).map(t => t.process_code))
}

// ── 结果 ──────────────────────────────────────────────────────────────────
const loading = ref(false)
const loadErr = ref('')
const items = ref([])
const capped = ref(false)
const scanned = ref([])        // 本次查询实际扫描的模板名（用于确认报销等是否已覆盖）
const tplStats = ref([])       // 逐模板命中诊断 [{name, found, matched}]
const queried = ref(false)     // 是否已发起过一次查询
const sel = ref(new Set())
const selCount = computed(() => sel.value.size)
const DING = {
  approved: ['ok', '已通过'], rejected: ['bad', '已拒绝'],
  pending: ['run', '审批中'], canceled: ['cancel', '已撤销'],
}
const stats = computed(() => {
  const s = displayItems.value
  return { total: s.length, unsynced: s.filter(i => !i.synced).length, synced: s.filter(i => i.synced).length }
})

async function resolvePerson() {
  const val = personInput.value.trim()
  if (!val) { toast.error('请输入手机号或姓名'); return null }
  resolving.value = true; candidates.value = []
  try {
    const body = personMode.value === 'mobile' ? { mobile: val } : { name: val }
    const r = await api.post('/dingtalk/resolve-user', body)
    const users = r.data?.users || []
    if (!users.length) { toast.error('钉钉通讯录未找到该人员'); return null }
    if (users.length === 1) { picked.value = users[0]; return users[0] }
    candidates.value = users; return null   // 多个同名 → 交用户选
  } catch (e) { toast.error(e?.msg || e?.error || '查询人员失败'); return null }
  finally { resolving.value = false }
}
function pickCandidate(u) { picked.value = u; candidates.value = []; runQuery() }
function copyUid() {
  if (!picked.value) return
  navigator.clipboard?.writeText(picked.value.userid).then(() => toast.success('已复制 userid')).catch(() => {})
}

async function runQuery() {
  let user = picked.value
  if (!user) { user = await resolvePerson(); if (!user) return }
  if (!tplSel.value.size) { toast.error('请先勾选要查询的审批模板（如：报销）'); return }
  loading.value = true; loadErr.value = ''; sel.value = new Set()
  try {
    // 只查勾选的模板（连名称一起传，后端无需重拉全量模板目录），单独放宽超时到 90s
    const picks = templates.value.filter(t => tplSel.value.has(t.process_code))
      .map(t => ({ process_code: t.process_code, name: t.name || t.process_code }))
    // 一次查回三口径（待处理/已处理/发起），前端按页签本地筛选，切页签不再重查
    const r = await api.post('/dingtalk/query', {
      userid: user.userid, start: range.start, end: range.end, status: 'all',
      templates: picks,
    }, { timeout: 90000 })
    items.value = r.data?.items || []
    capped.value = !!r.data?.capped
    scanned.value = r.data?.templates_scanned || []
    tplStats.value = r.data?.template_stats || []
    queried.value = true
  } catch (e) { loadErr.value = e?.msg || e?.error || '查询失败'; items.value = [] }
  finally { loading.value = false }
}
// 当前页签下的结果（本地筛选，不重查）
const displayItems = computed(() => items.value.filter(i => i.task === status.value))
const roleCount = computed(() => {
  const c = { todo: 0, done: 0, originated: 0 }
  items.value.forEach(i => { if (c[i.task] != null) c[i.task]++ })
  return c
})
function onStatusTab(v) { status.value = v }   // 只切页签，不查询

// ── 勾选 ──────────────────────────────────────────────────────────────────
function toggle(id) { const s = new Set(sel.value); s.has(id) ? s.delete(id) : s.add(id); sel.value = s }
const pageAllSel = computed(() => displayItems.value.length > 0 && displayItems.value.every(i => sel.value.has(i.instance_id)))
function toggleAll() {
  const s = new Set(sel.value)
  if (pageAllSel.value) displayItems.value.forEach(i => s.delete(i.instance_id))
  else displayItems.value.forEach(i => s.add(i.instance_id))
  sel.value = s
}
function selQuick(kind) {
  const s = new Set()
  displayItems.value.forEach(i => {
    if (kind === 'unsync' && !i.synced) s.add(i.instance_id)
    else if (kind === 'stale' && i.sync_stale) s.add(i.instance_id)
    else if (kind === 'today' && (i.create_time || '').slice(0, 10) === todayCST()) s.add(i.instance_id)
  })
  sel.value = s
}
function clearSel() { sel.value = new Set() }

// ── 同步 / 刷新 ────────────────────────────────────────────────────────────
const selectedItems = computed(() => items.value.filter(i => sel.value.has(i.instance_id)))
const previewOpen = ref(false)
const syncing = ref(false)
const newCount = computed(() => selectedItems.value.filter(i => !i.synced).length)
const updCount = computed(() => selectedItems.value.filter(i => i.synced).length)
const approvedCount = computed(() => selectedItems.value.filter(i => i.ding_status === 'approved').length)

function openPreview() { if (selCount.value) previewOpen.value = true }
async function doSync() {
  syncing.value = true
  try {
    const r = await api.post('/dingtalk/sync', { instance_ids: [...sel.value] }, { timeout: 90000 })
    const d = r.data || {}
    previewOpen.value = false
    if (d.skipped?.length) resultDlg({ title: '同步结果', okLine: d.message, skipped: d.skipped })
    else toast.success(d.message || '已同步')
    emit('synced')
    await runQuery()          // 刷新同步标记
  } catch (e) { toast.error(e?.msg || e?.error || '同步失败') }
  finally { syncing.value = false }
}
async function refreshStatus() {
  if (!selCount.value) return
  if (!(await confirmDlg(`对所选 ${selCount.value} 条已同步记录，从钉钉重新拉取最新状态并回写？未同步的会自动跳过。`))) return
  syncing.value = true
  try {
    const r = await api.post('/dingtalk/refresh', { instance_ids: [...sel.value] }, { timeout: 90000 })
    const d = r.data || {}
    if (d.skipped?.length) resultDlg({ title: '刷新结果', okLine: d.message, skipped: d.skipped })
    else toast.success(d.message || '已刷新')
    emit('synced')
    await runQuery()
  } catch (e) { toast.error(e?.msg || e?.error || '刷新失败') }
  finally { syncing.value = false }
}

// ── 查询方案（按账号保存：模板选择 + 口径）——复用通用 list-schemes 基座 ──────────
const SCHEME_MODULE = 'dingtalk_query'
const schemes = ref([])
const curSchemeId = ref(null)
async function loadSchemes() {
  try { schemes.value = (await api.get('/list-schemes', { params: { module: SCHEME_MODULE } })).data?.items || [] }
  catch { schemes.value = [] }
}
async function saveScheme() {
  if (!tplSel.value.size) { toast.error('请先勾选要保存的模板'); return }
  const name = ((await promptDlg({ title: '保存为方案', inputLabel: '方案名称',
    placeholder: '如：报销+付款', confirmText: '保存' })) || '').trim()
  if (!name) return
  const picks = templates.value.filter(t => tplSel.value.has(t.process_code))
    .map(t => ({ process_code: t.process_code, name: t.name || t.process_code }))
  try {
    await api.post('/list-schemes', {
      module: SCHEME_MODULE, name, scope: 'private',
      payload: { templates: picks, status: status.value },
    })
    toast.success('方案已保存'); await loadSchemes()
  } catch (e) { toast.error(e?.msg || e?.error || '保存失败') }
}
function applyScheme(s) {
  if (!s) { curSchemeId.value = null; return }
  curSchemeId.value = s.id
  const p = s.payload || {}
  const have = new Set(templates.value.map(t => t.process_code))
  for (const t of (p.templates || [])) {
    if (!have.has(t.process_code)) templates.value.push({ ...t, dir_name: t.dir_name || '方案' })
  }
  tplSel.value = new Set((p.templates || []).map(t => t.process_code))
  if (p.status) status.value = p.status
  toast.success(`已载入方案「${s.name}」`)
  if (picked.value) runQuery()
}
async function deleteScheme(s) {
  if (!(await confirmDlg(`删除方案「${s.name}」？`))) return
  try {
    await api.delete(`/list-schemes/${s.id}`)
    if (curSchemeId.value === s.id) curSchemeId.value = null
    toast.success('已删除'); await loadSchemes()
  } catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
}

// ── 单据详情（钉钉样式弹窗）──────────────────────────────────────────────────
const detailOpen = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const showRaw = ref(false)
const DFLOW = {   // 操作类型 → 中文 + 色
  START_PROCESS_INSTANCE: ['发起', 'st'], EXECUTE_TASK_NORMAL: ['审批', 'ap'],
  EXECUTE_TASK_AGENT: ['代审批', 'ap'], FINISH_PROCESS_INSTANCE: ['结束', 'fi'],
  TERMINATE_PROCESS_INSTANCE: ['撤销', 'te'], REDIRECT_PROCESS: ['退回', 'te'],
  PROCESS_CC: ['抄送', 'cc'], ADD_REMARK: ['评论', 'cc'],
  APPEND_TASK_BEFORE: ['前加签', 'ap'], APPEND_TASK_AFTER: ['后加签', 'ap'],
  REDIRECT_TASK: ['转交', 'cc'],
}
function flowLabel(t) { return (DFLOW[t] || [t || '处理', 'ap'])[0] }
function flowCls(t) { return 'fl-' + (DFLOW[t] || ['', 'ap'])[1] }
function flowResult(r) {
  return { AGREE: '同意', REFUSE: '拒绝', NONE: '' }[(r || '').toUpperCase()] || ''
}
async function openDetail(item) {
  detailOpen.value = true; detail.value = null; detailLoading.value = true
  try {
    detail.value = (await api.post('/dingtalk/instance',
      { instance_id: item.instance_id }, { timeout: 60000 })).data
  } catch (e) { toast.error(e?.msg || e?.error || '获取详情失败'); detailOpen.value = false }
  finally { detailLoading.value = false }
}
function money(v) { return '¥' + Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }

// ── 单据字段格式化（把钉钉各控件值渲染成人看得懂的样子）──────────────────────
function tryJSON(v) { try { return JSON.parse(v) } catch { return null } }
// 钉钉明细行两种形态：{列:值} 或 {rowValue:[{label,value,key}]} → 统一展平成 {列:值}
function flattenRow(r) {
  if (r && Array.isArray(r.rowValue)) {
    const o = {}
    for (const c of r.rowValue) if (c && c.label != null) o[String(c.label)] = c.value
    return o
  }
  return r || {}
}
// 明细表(TableField)：value 是 JSON 数组字符串 → 解析成 {cols, rows} 的表
function parseTable(fld) {
  let rows = Array.isArray(fld.value) ? fld.value : tryJSON(fld.value)
  if (!Array.isArray(rows) || !rows.length) return null
  rows = rows.map(flattenRow)
  const cols = []
  rows.forEach(r => Object.keys(r).forEach(k => { if (!cols.includes(k)) cols.push(k) }))
  return { cols, rows }
}
const MONEY_COL = /金额|价税|合计|费用|款|单价|总额/
function fmtCell(col, val) {
  if (val == null || val === '') return '—'
  if (MONEY_COL.test(col) && !isNaN(Number(String(val).replace(/,/g, ''))))
    return money(String(val).replace(/,/g, ''))
  return String(val)
}
// 普通字段的显示值（图片/附件/多选/人员等做友好处理）
function fldDisplay(fld) {
  const t = fld.type || ''
  const v = fld.value
  if (v == null || v === '') return '—'
  if (t === 'MoneyField') return money(v)
  if (t === 'DDPhotoField') { const a = tryJSON(v); return Array.isArray(a) ? `🖼 ${a.length} 张图片` : String(v) }
  if (t === 'DDAttachment') { const a = tryJSON(v); return Array.isArray(a) ? `📎 ${a.length} 个附件` : String(v) }
  if (t === 'DDMultiSelectField' || t === 'InnerContactField') {
    const a = tryJSON(v); return Array.isArray(a) ? a.join('、') : String(v)
  }
  if (t === 'AddressField') { const o = tryJSON(v); if (o && typeof o === 'object') return [o.province, o.city, o.district, o.detail].filter(Boolean).join('') || String(v) }
  return String(v)
}
const fldIsTable = (fld) => (fld.type === 'TableField') || (typeof fld.value === 'string' && /^\s*\[\s*{/.test(fld.value))
const fldIsWide = (fld) => fldIsTable(fld) || String(fldDisplay(fld)).length > 24

// ── 状态持久化：勾选模板/人员/时间/口径/方案 存本地，重进界面自动恢复并复现上次查询 ──
const STATE_KEY = 'dt_query_state_v1'
function saveState() {
  try {
    const picks = templates.value.filter(t => tplSel.value.has(t.process_code))
      .map(t => ({ process_code: t.process_code, name: t.name || t.process_code }))
    const have = new Set(picks.map(p => p.process_code))
    for (const c of tplSel.value) if (!have.has(c)) picks.push({ process_code: c, name: c })
    localStorage.setItem(STATE_KEY, JSON.stringify({
      personMode: personMode.value, personInput: personInput.value, picked: picked.value,
      range: { start: range.start, end: range.end }, status: status.value,
      curSchemeId: curSchemeId.value, tpls: picks,
      // 结果也存下：刷新/重进界面直接显示上次记录，无需再打钉钉（点「查询」才刷新）
      items: items.value.slice(0, 500), queried: queried.value,
    }))
  } catch { /* ignore */ }
}
const _saved = (() => { try { return JSON.parse(localStorage.getItem(STATE_KEY) || 'null') } catch { return null } })()
if (_saved) {   // 先同步恢复标量输入（在 watch 注册前）
  personMode.value = _saved.personMode || 'mobile'
  personInput.value = _saved.personInput || ''
  picked.value = _saved.picked || null
  if (_saved.range) { range.start = _saved.range.start || range.start; range.end = _saved.range.end || range.end }
  status.value = _saved.status || 'todo'
  curSchemeId.value = _saved.curSchemeId ?? null
  if (_saved.tpls?.length) _hasRestoredSel = true
}
// 先恢复上次结果（在 watch 注册前，避免被空 items 覆盖）
if (_saved?.items?.length) { items.value = _saved.items; queried.value = !!_saved.queried }
watch([
  () => [...tplSel.value].join(','), () => personMode.value, () => personInput.value,
  () => picked.value && picked.value.userid, () => range.start, () => range.end,
  () => status.value, () => curSchemeId.value, () => items.value.length,
], saveState)

onMounted(async () => {
  await loadTemplates()
  if (_saved?.tpls?.length) {   // 恢复勾选（含方案带入、当前企业列表里没有的也并进来）
    const have = new Set(templates.value.map(t => t.process_code))
    for (const t of _saved.tpls) if (!have.has(t.process_code)) templates.value.push({ ...t, dir_name: t.dir_name || '已选' })
    tplSel.value = new Set(_saved.tpls.map(t => t.process_code))
  }
  loadSchemes()
  // 不自动查询——上次结果已从本地恢复；要拉钉钉最新数据点「查询」即可
})
</script>

<template>
  <div class="dt card fh-fill">
    <!-- 连接自检 -->
    <div v-if="diag" class="diag" :class="{ bad: !diag.connected }">
      <div class="diag-line">
        <b>{{ diag.connected ? '✓ 钉钉已连通' : '✗ 连接失败' }}</b>
        <span v-if="diag.error" class="diag-err">{{ diag.error }}</span>
        <button class="diag-x" @click="diag = null">✕</button>
      </div>
      <div v-if="diag.config" class="diag-cfg">
        服务器读到：AppKey=<code>{{ diag.config.app_key }}</code> ·
        Secret 长度 <code>{{ diag.config.secret_len }}</code>（<code>{{ diag.config.secret_masked }}</code>） ·
        管理员 userid <code>{{ diag.config.admin_userid_set ? '已配' : '未配' }}</code> ·
        模板清单 <code>{{ diag.config.process_codes_set ? '已配' : '未配' }}</code>
      </div>
      <div v-if="diag.hint" class="diag-hint">💡 {{ diag.hint }}</div>
      <div v-if="diag.connected" class="diag-tpl">
        可同步模板：<template v-if="diag.templates && diag.templates.length"><code v-for="t in diag.templates" :key="t.process_code">{{ t.name || t.process_code }}</code></template>
        <span v-else class="diag-err">未列出 —— 请在 DINGTALK_PROCESS_CODES 配置模板 process_code<span v-if="diag.template_error">（{{ diag.template_error }}）</span></span>
      </div>
    </div>

    <!-- 子页签：查询 / 模板 -->
    <div class="dt-subtabs">
      <button :class="['sub', { on: subview === 'query' }]" @click="subview = 'query'">查询同步</button>
      <button :class="['sub', { on: subview === 'templates' }]" @click="subview = 'templates'">
        模板配置<span v-if="tplSelCount" class="sub-n">{{ tplSelCount }}</span>
      </button>
      <span class="grow"></span>
      <button class="quick test" :disabled="testing" @click="testConnection">{{ testing ? '检测中…' : '测试连接' }}</button>
    </div>

    <!-- ══ 查询条（人员 / 时间 / 方案 同一行，尽量给结果留空间）══ -->
    <div v-show="subview === 'query'" class="dt-bar">
      <div class="seg">
        <button :class="{ on: personMode === 'mobile' }" @click="personMode = 'mobile'; picked = null">手机号</button>
        <button :class="{ on: personMode === 'name' }" @click="personMode = 'name'; picked = null">姓名</button>
      </div>
      <input v-model="personInput" class="inp person-inp" :placeholder="personMode === 'mobile' ? '钉钉手机号' : '姓名'"
             @keyup.enter="runQuery()" @input="picked = null" />
      <span v-if="picked" class="picked" :title="'userid: ' + picked.userid">✓ {{ picked.name }}</span>

      <span class="bar-sep"></span>
      <input v-model="range.start" type="date" class="inp inp-date" />
      <span class="sep">→</span>
      <input v-model="range.end" type="date" class="inp inp-date" />
      <select class="inp preset-sel" @change="setQuick($event.target.value); $event.target.selectedIndex = 0">
        <option value="">快捷…</option>
        <option v-for="q in QUICK" :key="q.k" :value="q.k">{{ q.l }}</option>
      </select>

      <span class="bar-sep"></span>
      <span class="sc-lbl">方案</span>
      <button v-for="s in schemes" :key="s.id" class="sc-chip" :class="{ on: curSchemeId === s.id }" @click="applyScheme(s)">
        {{ s.name }}<span class="sc-x" title="删除" @click.stop="deleteScheme(s)">✕</span>
      </button>
      <button class="sc-save" title="把当前勾选的模板+口径存为方案" @click="saveScheme">＋存方案</button>
      <span class="tpl-hint" @click="subview = 'templates'">模板 <b>{{ tplSelCount }}</b> →</span>

      <span class="grow"></span>
      <button class="go" :disabled="loading || resolving" @click="runQuery()">
        {{ loading || resolving ? '查询中…' : '查询' }}
      </button>
    </div>
    <!-- 同名候选 -->
    <div v-show="subview === 'query' && candidates.length" class="dt-cands">
      <span class="cands-lbl">多个同名，请选择：</span>
      <button v-for="u in candidates" :key="u.userid" class="cand" @click="pickCandidate(u)">{{ u.name }}</button>
    </div>

    <!-- ══ 审批模板配置（企业全部表单，勾选后再查）══ -->
    <div v-show="subview === 'templates'" class="dt-tpls">
      <div class="tpls-head">
        <span class="tpls-lbl">审批模板</span>
        <span v-if="tplLoading" class="tpls-info">加载企业全部模板中…</span>
        <span v-else class="tpls-info">共 <b>{{ templates.length }}</b> 个 · 已选 <b>{{ tplSelCount }}</b></span>
        <button class="tpls-op" :disabled="tplLoading" @click="selectFinance">只选财务类</button>
        <button class="tpls-op" :disabled="tplLoading" @click="tplSelectAll(true)">{{ tplFilter ? '选中筛选项' : '全选' }}</button>
        <button class="tpls-op" :disabled="tplLoading" @click="tplSelectAll(false)">全不选</button>
        <input v-model="tplFilter" class="tpls-filter" placeholder="筛选模板名，如 报销" />
        <span class="grow"></span>
        <button class="tpls-op refresh" :disabled="tplLoading" @click="templates = []; loadTemplates()">↻ 刷新</button>
      </div>
      <div v-if="tplLoading" class="tpls-empty">⏳ 正在加载企业全部审批模板…</div>
      <div v-else-if="tplErr" class="tpls-err">⚠️ {{ tplErr }} <button class="tpls-op" @click="templates = []; loadTemplates()">重试</button></div>
      <div v-else class="tpls-scroll">
        <div v-for="g in tplGroups" :key="g.dir" class="tpls-group">
          <div class="grp-h">{{ g.dir }}<span class="grp-n">{{ g.items.length }}</span></div>
          <div class="tpls-grid">
            <label v-for="t in g.items" :key="t.process_code" class="tplitem" :class="{ on: tplSel.has(t.process_code) }">
              <input type="checkbox" class="cbx" :checked="tplSel.has(t.process_code)" @change="toggleTpl(t.process_code)" />
              <span class="tplname">{{ t.name || t.process_code }}</span>
            </label>
          </div>
        </div>
        <div v-if="!tplShown.length" class="tpls-empty">
          {{ tplFilter ? '无匹配模板，换个关键词' : '未获取到审批模板，点右上「刷新」重试，或确认应用已开通「工作流模板读」权限、可用范围为全部员工' }}
        </div>
      </div>
    </div>

    <!-- 状态页签（一次查回三口径，切页签只本地筛选、不再重查）-->
    <div v-show="subview === 'query'" class="dt-tabs">
      <button v-for="s in STATUS" :key="s.v" :class="['dt-tab', { on: status === s.v }]" @click="onStatusTab(s.v)">
        {{ s.l }}<span v-if="queried" class="tab-n">{{ roleCount[s.v] }}</span>
      </button>
    </div>

    <!-- 汇总条 + 快捷选 -->
    <div v-if="displayItems.length && subview === 'query'" class="dt-summary">
      <span class="s">共 <b>{{ stats.total }}</b> 条</span>
      <span class="s acc">未同步 <b>{{ stats.unsynced }}</b></span>
      <span class="s ok">已同步 <b>{{ stats.synced }}</b></span>
      <span v-if="capped" class="s warn">结果较多已截断，请缩小时间范围</span>
      <span class="grow"></span>
      <span class="sellbl">快捷选：</span>
      <button class="selq" @click="selQuick('unsync')">全部未同步</button>
      <button class="selq" @click="selQuick('stale')">状态待刷新</button>
      <button class="selq" @click="selQuick('today')">今天</button>
    </div>

    <!-- 结果表 -->
    <div v-show="subview === 'query'" class="dt-body">
      <div v-if="loadErr" class="empty err">⚠️ {{ loadErr }}</div>
      <div v-else-if="loading" class="empty">⏳ 正在从钉钉拉取…</div>
      <div v-else-if="!queried" class="empty hint">
        <div class="hint-i">🔗</div>
        <div class="hint-t">按人查询钉钉审批</div>
        <div class="hint-s">输入手机号或姓名、选时间范围、勾选模板，点「查询」——一次查回该员工的待处理 / 已处理 / 发起，切页签即时看，勾选后可转为审批记录供排款。</div>
      </div>
      <div v-else-if="!displayItems.length" class="empty">
        <div>该员工在此范围内无「{{ STATUS.find(s => s.v === status).l }}」的审批<span v-if="items.length">（其他口径共 {{ items.length }} 条，切页签查看）</span></div>
        <!-- 逐模板诊断：拉到多少实例、其中符合当前口径多少 → 一眼看穿卡在哪 -->
        <div v-if="tplStats.length" class="diag">
          <div class="diag-h">本次查询逐模板情况</div>
          <table class="diag-t">
            <thead><tr><th>模板</th><th>时间段内实例</th><th>符合「{{ STATUS.find(s => s.v === status).l }}」</th></tr></thead>
            <tbody>
              <tr v-for="t in tplStats" :key="t.process_code" :class="{ hot: t.found > 0 }">
                <td>{{ t.name }}</td><td class="c">{{ t.found }}</td><td class="c">{{ t.matched }}</td>
              </tr>
            </tbody>
          </table>
          <div class="scanned-tip">
            · 某模板「实例=0」：该模板在此时间段无单据，或应用无权读取其实例 → 换时间段，或确认应用「审批」读权限。<br>
            · 「实例&gt;0 但符合=0」：单据存在，只是不属于当前口径 → 换标签页（发起用查提报人、待处理/已处理用查审批人）。
          </div>
        </div>
      </div>
      <div v-else class="tablewrap">
        <table>
          <thead>
            <tr>
              <th class="cbcol"><input type="checkbox" class="cbx" :checked="pageAllSel" @change="toggleAll" /></th>
              <th>审批标题 / 编号</th><th>摘要</th><th>发起人</th><th class="r">金额</th><th>收款方</th>
              <th>钉钉状态</th><th>发起时间</th><th>同步状态</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in displayItems" :key="i.instance_id" :class="{ sel: sel.has(i.instance_id) }"
                @dblclick="openDetail(i)" title="双击查看单据详情">
              <td><input type="checkbox" class="cbx" :checked="sel.has(i.instance_id)" @change="toggle(i.instance_id)" /></td>
              <td class="ttlcell">
                <div class="ttl">{{ i.title }}</div>
                <div class="sub"><span class="tpl">{{ i.template }}</span> · {{ i.approval_number || '—' }}</div>
              </td>
              <td class="sumcell">{{ i.summary || '—' }}</td>
              <td>{{ i.applicant }}<div class="sub">{{ i.department }}</div></td>
              <td class="r amt">¥{{ Number(i.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</td>
              <td class="payee">{{ i.payee }}</td>
              <td>
                <span class="pill" :class="'p-' + (DING[i.ding_status] || ['run'])[0]"><i></i>{{ (DING[i.ding_status] || ['', i.ding_status || '未知'])[1] }}</span>
                <span v-if="i.stale" class="stale-b" title="本次刷新失败，展示的是上次存档，数据可能已变化">旧</span>
              </td>
              <td class="when">{{ (i.create_time || '').replace('T', ' ').slice(0, 16) }}</td>
              <td>
                <span v-if="!i.synced" class="sync no">● 未同步</span>
                <span v-else-if="i.sync_stale" class="sync upd">◑ 待刷新 <span class="rec">{{ i.sync_rec_no }}</span></span>
                <span v-else class="sync yes">✓ 已同步 <span class="rec">{{ i.sync_rec_no }}</span></span>
              </td>
              <td><button class="rowdetail" @click.stop="openDetail(i)">详情</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 批量条 -->
    <Transition name="bb">
      <div v-if="selCount" class="batchbar">
        <span class="n">已选 <b>{{ selCount }}</b> 条</span>
        <button class="bb primary" :disabled="syncing" @click="openPreview">转为审批记录（供排款）</button>
        <button class="bb ghost" :disabled="syncing" @click="refreshStatus">刷新选中状态</button>
        <button class="bb x" @click="clearSel">✕</button>
      </div>
    </Transition>

    <!-- 转为审批记录预览弹窗 -->
    <Teleport to="body">
      <div v-if="previewOpen" class="scrim" @click.self="previewOpen = false">
        <div class="modal">
          <div class="m-head">
            <h3>转为审批记录 · 预览</h3>
            <p>把所选钉钉审批转成「审批管理」记录供排款。按实例去重：已存在的更新，其余新建。</p>
          </div>
          <div class="m-body">
            <div class="conflict">
              <span>ℹ</span>
              <span>共 <b>{{ selCount }}</b> 条：<b>{{ newCount }}</b> 新建、<b>{{ updCount }}</b> 更新。
                其中 <b>{{ approvedCount }}</b> 条钉钉「已通过」→ 转入即为<b>审批通过</b>、可直接排款；
                其余（审批中/拒绝）转入对应状态，通过后再排款。
                字段：申请人/部门/金额/收款方/摘要自动映射，原始表单整单留存。</span>
            </div>
            <table class="mtable">
              <thead><tr><th>钉钉审批</th><th class="r">金额</th><th>钉钉状态</th><th>处理</th></tr></thead>
              <tbody>
                <tr v-for="i in selectedItems" :key="i.instance_id">
                  <td><div class="ttl">{{ i.title }}</div><div class="sub">{{ i.applicant }} · {{ i.department }} · {{ i.payee }}</div></td>
                  <td class="r amt">¥{{ Number(i.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</td>
                  <td><span class="pill sm" :class="'p-' + (DING[i.ding_status] || ['run'])[0]">{{ (DING[i.ding_status] || ['', i.ding_status || '未知'])[1] }}</span></td>
                  <td><span class="tag" :class="i.synced ? 'upd' : 'new'">{{ i.synced ? '更新' : '新建' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="m-foot">
            <button class="btn" @click="previewOpen = false">取消</button>
            <button class="btn primary" :disabled="syncing" @click="doSync">{{ syncing ? '转入中…' : `确认转入 ${selCount} 条` }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 单据详情弹窗（钉钉样式）-->
    <Teleport to="body">
      <div v-if="detailOpen" class="scrim" @click.self="detailOpen = false">
        <div class="ding-modal">
          <div v-if="detailLoading" class="ding-loading">⏳ 加载单据详情…</div>
          <template v-else-if="detail">
            <div class="ding-head">
              <div class="ding-title">
                <span class="ding-tpl">{{ detail.template }}</span>
                <span class="ding-st" :class="'p-' + (DING[detail.sys_status] || ['run'])[0]">{{ (DING[detail.sys_status] || ['', detail.ding_status])[1] }}</span>
              </div>
              <h3>{{ detail.title }}</h3>
              <button class="diag-x" @click="detailOpen = false">✕</button>
            </div>
            <div class="ding-body">
              <div class="ding-meta">
                <div><label>申请人</label><span>{{ detail.applicant }}</span></div>
                <div><label>部门</label><span>{{ detail.department }}</span></div>
                <div><label>审批编号</label><span>{{ detail.approval_number || '—' }}</span></div>
                <div><label>发起时间</label><span>{{ (detail.create_time || '').replace('T', ' ').slice(0, 16) || '—' }}</span></div>
                <div class="amt-big"><label>金额</label><span>{{ money(detail.amount) }}</span></div>
                <div><label>收款方</label><span>{{ detail.payee || '—' }}</span></div>
              </div>

              <div class="ding-sec">表单内容</div>
              <div class="ding-form">
                <div v-for="(fld, idx) in detail.form" :key="idx" class="ding-fld" :class="{ wide: fldIsWide(fld) }">
                  <label>{{ fld.name }}</label>
                  <!-- 明细表：渲染成子表格 -->
                  <div v-if="fldIsTable(fld) && parseTable(fld)" class="ding-subtable-wrap">
                    <table class="ding-subtable">
                      <thead><tr><th v-for="c in parseTable(fld).cols" :key="c">{{ c }}</th></tr></thead>
                      <tbody>
                        <tr v-for="(row, ri) in parseTable(fld).rows" :key="ri">
                          <td v-for="c in parseTable(fld).cols" :key="c" :class="{ r: MONEY_COL.test(c) }">{{ fmtCell(c, row[c]) }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <span v-else-if="fld.type === 'MoneyField'" class="fv-money">{{ money(fld.value) }}</span>
                  <span v-else class="fv">{{ fldDisplay(fld) }}</span>
                </div>
                <div v-if="!detail.form.length" class="ding-empty">无表单字段</div>
              </div>

              <div class="ding-sec">审批流水</div>
              <ol class="ding-flow">
                <li v-for="(op, idx) in detail.flow" :key="idx">
                  <span class="fl-dot" :class="flowCls(op.type)"></span>
                  <span class="fl-act" :class="flowCls(op.type)">{{ flowLabel(op.type) }}</span>
                  <span class="fl-user">{{ op.userid }}</span>
                  <span v-if="flowResult(op.result)" class="fl-res" :class="op.result === 'AGREE' ? 'ok' : 'no'">{{ flowResult(op.result) }}</span>
                  <span class="fl-date">{{ (op.date || '').replace('T', ' ').slice(0, 16) }}</span>
                </li>
                <li v-if="!detail.flow.length" class="ding-empty">无审批流水</li>
              </ol>

              <!-- 调试：钉钉原始字段（名/类型/值）——金额或摘要不对时，把这块发我可精确定位 -->
              <div class="ding-sec dbg-h">
                字段调试 <button class="dbg-t" @click="showRaw = !showRaw">{{ showRaw ? '收起' : '展开' }}</button>
              </div>
              <div v-if="showRaw" class="dbg-wrap">
                <table class="dbg-t2">
                  <thead><tr><th>字段名</th><th>类型</th><th>原始值</th></tr></thead>
                  <tbody>
                    <tr v-for="(fld, idx) in detail.form" :key="idx">
                      <td>{{ fld.name }}</td><td class="mono">{{ fld.type || '—' }}</td>
                      <td class="mono">{{ String(fld.value).slice(0, 120) || '(空)' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dt { display: flex; flex-direction: column; min-height: 0; padding: 0; }
/* 子页签 */
.dt-subtabs { display: flex; align-items: center; gap: 4px; padding: 8px 14px 0; border-bottom: 1px solid var(--border, #eadfd2); }
.dt-subtabs .sub { border: none; background: none; padding: 9px 16px; font-size: 14px; font-weight: 700; color: var(--muted, #9b8070); cursor: pointer; font-family: inherit; border-bottom: 2.5px solid transparent; margin-bottom: -1px; display: flex; align-items: center; gap: 6px; }
.dt-subtabs .sub.on { color: var(--primary, #1565c0); border-bottom-color: var(--primary, #1565c0); }
.dt-subtabs .sub-n { background: var(--primary, #1565c0); color: #fff; font-size: 11px; border-radius: 9px; padding: 0 6px; font-weight: 700; }
.dt-subtabs .grow { flex: 1; }
/* 方案条 */
.dt-schemes { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; padding: 10px 18px; border-bottom: 1px solid var(--border, #eadfd2); background: var(--panel-2, #faf6f0); }
.sc-lbl { font-size: 12px; font-weight: 700; color: var(--muted, #9b8070); }
.sc-chip { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--text, #4a3322); font-size: 12.5px; padding: 4px 9px; border-radius: 14px; cursor: pointer; font-family: inherit; }
.sc-chip.on { border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); background: var(--primary-weak, #e8f1fb); }
.sc-chip .sc-x { color: var(--muted, #9b8070); font-size: 11px; }
.sc-chip .sc-x:hover { color: var(--danger, #d64545); }
.sc-empty { font-size: 12px; color: var(--muted, #9b8070); }
.sc-save { border: 1px dashed var(--primary, #1565c0); background: none; color: var(--primary, #1565c0); font-size: 12.5px; padding: 4px 11px; border-radius: 14px; cursor: pointer; font-family: inherit; }
.sc-sel { font-size: 12px; color: var(--muted, #9b8070); }
.sc-sel b { color: var(--primary, #1565c0); }
.sc-goto { border: none; background: none; color: var(--primary, #1565c0); font-size: 12px; cursor: pointer; font-family: inherit; margin-left: 4px; }
.sumcell { max-width: 220px; font-size: 12.5px; color: var(--muted, #7a6550); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stale-b { margin-left: 5px; font-size: 10.5px; color: var(--warn, #c47d0a); background: color-mix(in srgb, var(--warn, #c47d0a) 14%, transparent); padding: 0 5px; border-radius: 8px; }
.rowdetail { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--primary, #1565c0); font-size: 12px; padding: 3px 10px; border-radius: 6px; cursor: pointer; font-family: inherit; }
.rowdetail:hover { border-color: var(--primary, #1565c0); }
/* 单据详情弹窗 */
.ding-modal { background: var(--card-bg, #fff); border-radius: 14px; width: min(680px, 94vw); max-height: 88vh; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,.3); }
.ding-loading { padding: 60px; text-align: center; color: var(--muted, #9b8070); }
.ding-head { position: relative; padding: 18px 20px 14px; border-bottom: 1px solid var(--border, #eadfd2); background: linear-gradient(180deg, var(--primary-weak, #e8f1fb), transparent); }
.ding-title { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.ding-tpl { font-size: 12px; font-weight: 700; color: var(--primary, #1565c0); background: var(--card-bg, #fff); padding: 2px 9px; border-radius: 10px; }
.ding-st { font-size: 11.5px; font-weight: 700; padding: 2px 8px; border-radius: 10px; }
.ding-head h3 { margin: 0; font-size: 17px; color: var(--text, #4a3322); padding-right: 30px; }
.ding-body { padding: 16px 20px 22px; overflow-y: auto; }
.ding-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 20px; margin-bottom: 6px; }
.ding-meta > div { display: flex; flex-direction: column; gap: 2px; }
.ding-meta label { font-size: 11px; color: var(--muted, #9b8070); }
.ding-meta span { font-size: 13.5px; color: var(--text, #4a3322); font-weight: 600; }
.ding-meta .amt-big span { font-size: 18px; font-weight: 800; color: var(--primary, #1565c0); }
.ding-sec { font-size: 12px; font-weight: 800; color: var(--muted, #9b8070); margin: 18px 0 8px; padding-bottom: 5px; border-bottom: 1px dashed var(--border, #eadfd2); }
.dbg-h { display: flex; align-items: center; gap: 8px; }
.dbg-t { border: 1px solid var(--border, #eadfd2); background: none; color: var(--muted, #9b8070); border-radius: 5px; padding: 1px 8px; font-size: 11px; cursor: pointer; font-family: inherit; }
.dbg-wrap { overflow-x: auto; }
.dbg-t2 { border-collapse: collapse; font-size: 11.5px; width: 100%; }
.dbg-t2 th, .dbg-t2 td { border: 1px solid var(--border, #eadfd2); padding: 3px 7px; text-align: left; vertical-align: top; }
.dbg-t2 th { background: var(--panel-2, #faf6f0); color: var(--muted, #9b8070); }
.dbg-t2 .mono { font-family: ui-monospace, Menlo, Consolas, monospace; word-break: break-all; }
.ding-form { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 20px; }
@media (max-width: 620px) { .ding-form { grid-template-columns: 1fr; } }
.ding-fld { display: flex; flex-direction: column; gap: 2px; }
.ding-fld.wide { grid-column: 1 / -1; }
.ding-fld label { font-size: 11px; color: var(--muted, #9b8070); }
.ding-fld .fv { font-size: 13px; color: var(--text, #4a3322); white-space: pre-wrap; word-break: break-word; }
.ding-fld .fv-money { font-size: 14px; font-weight: 700; color: var(--primary, #1565c0); }
.ding-empty { color: var(--muted, #9b8070); font-size: 12.5px; grid-column: 1 / -1; }
.ding-subtable-wrap { overflow-x: auto; margin-top: 3px; }
.ding-subtable { border-collapse: collapse; font-size: 12px; width: 100%; }
.ding-subtable th, .ding-subtable td { border: 1px solid var(--border, #eadfd2); padding: 3px 8px; white-space: nowrap; }
.ding-subtable th { background: var(--panel-2, #faf6f0); color: var(--muted, #9b8070); font-weight: 600; }
.ding-subtable td.r { text-align: right; font-variant-numeric: tabular-nums; }
.ding-flow { list-style: none; margin: 0; padding: 0; }
.ding-flow li { display: flex; align-items: center; gap: 9px; padding: 7px 0; font-size: 12.5px; border-bottom: 1px dashed var(--border, #f0e6d8); }
.fl-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; background: var(--muted, #9b8070); }
.fl-dot.fl-ap { background: var(--primary, #1565c0); } .fl-dot.fl-st { background: #6b7280; } .fl-dot.fl-fi { background: var(--success, #2e9e5b); } .fl-dot.fl-te { background: var(--danger, #d64545); } .fl-dot.fl-cc { background: #b08968; }
.fl-act { font-weight: 700; color: var(--text, #4a3322); min-width: 44px; }
.fl-user { color: var(--muted, #7a6550); flex: 1; }
.fl-res { font-weight: 700; } .fl-res.ok { color: var(--success, #2e9e5b); } .fl-res.no { color: var(--danger, #d64545); }
.fl-date { color: var(--muted, #9b8070); font-size: 11.5px; }
.ding-st.p-ok, .ding-st.p-bad, .ding-st.p-run, .ding-st.p-cancel { border-radius: 10px; }
/* 紧凑单行查询条 */
.dt-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 16px; border-bottom: 1px solid var(--border, #eadfd2); }
.dt-bar .inp { padding: 6px 9px; font-size: 13px; }
.dt-bar .person-inp { width: 150px; }
.dt-bar .inp-date { width: 132px; }
.dt-bar .preset-sel { width: 78px; cursor: pointer; }
.dt-bar .bar-sep { width: 1px; align-self: stretch; background: var(--border, #eadfd2); margin: 2px 4px; }
.dt-bar .picked { font-size: 12.5px; font-weight: 700; color: var(--success, #2e9e5b); white-space: nowrap; }
.dt-bar .sc-lbl { font-size: 12px; font-weight: 700; color: var(--muted, #9b8070); }
.dt-bar .tpl-hint { font-size: 12px; color: var(--primary, #1565c0); cursor: pointer; white-space: nowrap; }
.dt-bar .tpl-hint b { font-size: 13px; }
.dt-bar .go { margin-left: 0; padding: 7px 20px; }
.dt-cands { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; padding: 8px 16px; border-bottom: 1px solid var(--border, #eadfd2); background: var(--panel-2, #faf6f0); }
.dt-query { display: flex; gap: 18px; align-items: flex-end; flex-wrap: wrap; padding: 16px 18px; border-bottom: 1px solid var(--border, #eadfd2); }
.qf { display: flex; flex-direction: column; gap: 7px; }
.qf > label { font-size: 11.5px; font-weight: 700; letter-spacing: .04em; color: var(--muted, #9b8070); text-transform: uppercase; }
.person { display: flex; align-items: center; gap: 9px; }
.seg { display: inline-flex; background: var(--surface-2, rgba(160,120,80,.08)); border-radius: 8px; padding: 3px; }
.seg button { border: none; background: none; padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; color: var(--muted, #9b8070); cursor: pointer; font-family: inherit; }
.seg button.on { background: var(--card-bg, #fff); color: var(--primary, #1565c0); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.inp { border: 1.5px solid var(--border, #d8c9b8); border-radius: 8px; padding: 8px 11px; font-size: 14px; color: var(--text, #4a3322); background: var(--card-bg, #fff); font-family: inherit; outline: none; transition: .14s; }
.inp:focus { border-color: var(--primary, #1565c0); box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary, #1565c0) 15%, transparent); }
.inp-date { width: 140px; }
.person .inp { width: 210px; }
.picked { font-size: 12.5px; font-weight: 700; color: var(--success, #2e9e5b); }
.picked .uid { font-weight: 500; background: var(--surface-2, rgba(160,120,80,.1)); color: var(--muted, #9b8070); padding: 1px 6px; border-radius: 5px; cursor: pointer; font-size: 11.5px; }
.picked .uid:hover { color: var(--primary, #1565c0); }
.cands { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 2px; }
.cands-lbl { font-size: 12px; color: var(--muted, #9b8070); }
.cand { border: 1px solid var(--primary, #1565c0); background: color-mix(in srgb, var(--primary, #1565c0) 8%, transparent); color: var(--primary, #1565c0); font-size: 12.5px; padding: 5px 11px; border-radius: 7px; cursor: pointer; font-family: inherit; }
.daterow { display: flex; align-items: center; gap: 8px; }
.sep { color: var(--muted, #9b8070); }
.quick { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--muted, #9b8070); font-size: 12px; padding: 6px 10px; border-radius: 7px; cursor: pointer; font-family: inherit; }
.quick:hover { border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); }
.go { margin-left: auto; background: var(--primary, #1565c0); color: #fff; border: none; padding: 9px 24px; border-radius: 9px; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; }
.go:disabled { opacity: .6; cursor: default; }

.quick.test { border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); }
.diag { margin: 12px 16px 0; padding: 11px 14px; border-radius: 10px; font-size: 12.5px; line-height: 1.7;
  background: color-mix(in srgb, var(--success, #2e9e5b) 8%, transparent); border: 1px solid color-mix(in srgb, var(--success, #2e9e5b) 25%, transparent); }
.diag.bad { background: color-mix(in srgb, var(--danger, #d64545) 8%, transparent); border-color: color-mix(in srgb, var(--danger, #d64545) 28%, transparent); }
.diag-line { display: flex; align-items: center; gap: 10px; } .diag-line b { font-size: 13.5px; }
.diag-err { color: var(--danger, #d64545); }
.diag-x { margin-left: auto; border: none; background: none; color: var(--muted, #9b8070); cursor: pointer; font-size: 15px; }
.diag code { background: var(--surface-2, rgba(160,120,80,.1)); padding: 1px 6px; border-radius: 5px; font-size: 12px; margin: 0 2px; }
.diag-hint { margin-top: 4px; color: var(--text-2, #6b5a49); }
.diag-tpl { margin-top: 4px; }
/* 模板勾选区 */
.dt-tpls { padding: 12px 18px; border-bottom: 1px solid var(--border, #eadfd2); background: var(--panel-2, #faf6f0); flex: 1; min-height: 0; display: flex; flex-direction: column; }
.tpls-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.tpls-lbl { font-size: 13px; font-weight: 700; color: var(--text, #4a3322); }
.tpls-info { font-size: 12.5px; color: var(--muted, #9b8070); }
.tpls-info b { color: var(--primary, #1565c0); }
.tpls-op { border: 1px solid var(--border, #eadfd2); background: var(--panel, #fff); border-radius: 6px; padding: 3px 10px; font-size: 12px; cursor: pointer; color: var(--text, #4a3322); font-family: inherit; }
.tpls-op:hover { border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); }
.tpls-filter { border: 1px solid var(--border, #eadfd2); border-radius: 6px; padding: 3px 9px; font-size: 12.5px; width: 150px; font-family: inherit; background: var(--panel, #fff); color: inherit; }
.tpls-op.refresh { color: var(--muted, #9b8070); }
.tpls-err { font-size: 12.5px; color: var(--danger, #d64545); }
.tpls-scroll { flex: 1; min-height: 120px; overflow-y: auto; }
.tpls-group + .tpls-group { margin-top: 8px; }
.grp-h { font-size: 11.5px; font-weight: 700; color: var(--muted, #9b8070); margin: 4px 0 4px; display: flex; align-items: center; gap: 6px; }
.grp-n { background: var(--chip-bg, #f0e9e0); color: var(--text, #6a5641); border-radius: 8px; padding: 0 6px; font-size: 10.5px; font-weight: 600; }
.tpls-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 4px 12px; }
.tplitem { display: flex; align-items: center; gap: 7px; padding: 4px 8px; border-radius: 6px; cursor: pointer; font-size: 12.5px; color: var(--text, #4a3322); border: 1px solid transparent; }
.tplitem:hover { background: var(--panel, #fff); }
.tplitem.on { background: var(--primary-weak, #e8f1fb); border-color: var(--primary-border, #c3ddf5); }
.tplname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tpls-empty { font-size: 12.5px; color: var(--muted, #9b8070); padding: 10px 2px; line-height: 1.6; }

.dt-tabs { display: flex; gap: 4px; padding: 2px 14px 0; border-bottom: 1px solid var(--border, #eadfd2); }
.dt-tab { border: none; background: none; padding: 11px 16px; font-size: 14px; font-weight: 650; color: var(--muted, #9b8070); cursor: pointer; font-family: inherit; border-bottom: 2.5px solid transparent; margin-bottom: -1px; }
.dt-tab.on { color: var(--primary, #1565c0); border-bottom-color: var(--primary, #1565c0); }
.pill.sm { font-size: 11px; padding: 2px 7px; }
.tab-n { margin-left: 5px; font-size: 11px; background: var(--surface-2, rgba(160,120,80,.12)); color: inherit; border-radius: 9px; padding: 0 6px; }
.dt-tab.on .tab-n { background: var(--primary, #1565c0); color: #fff; }

.dt-summary { display: flex; align-items: center; gap: 15px; padding: 10px 16px; border-bottom: 1px solid var(--border, #eadfd2); flex-wrap: wrap; }
.dt-summary .s { font-size: 13px; color: var(--text, #4a3322); }
.dt-summary .s b { font-weight: 750; } .dt-summary .acc b { color: var(--primary, #1565c0); } .dt-summary .ok b { color: var(--success, #2e9e5b); }
.dt-summary .warn { color: var(--warn, #c47d0a); font-size: 12px; }
.grow { flex: 1; } .sellbl { font-size: 12px; color: var(--muted, #9b8070); }
.selq { border: 1px dashed var(--border, #d8c9b8); background: none; color: var(--primary, #1565c0); font-size: 12px; padding: 5px 10px; border-radius: 7px; cursor: pointer; font-family: inherit; }
.selq:hover { border-color: var(--primary, #1565c0); background: color-mix(in srgb, var(--primary, #1565c0) 7%, transparent); }

.dt-body { flex: 1; min-height: 0; overflow: auto; }
.empty { padding: 46px 20px; text-align: center; color: var(--muted, #9b8070); font-size: 13.5px; }
.empty.err { color: var(--danger, #d64545); }
.empty.hint .hint-i { font-size: 40px; margin-bottom: 10px; }
.empty.hint .hint-t { font-size: 16px; font-weight: 700; color: var(--text, #4a3322); }
.empty.hint .hint-s { max-width: 460px; margin: 8px auto 0; line-height: 1.6; }
.scanned { margin-top: 14px; max-width: 620px; margin-left: auto; margin-right: auto; font-size: 12px; }
.scanned .tplchip { display: inline-block; margin: 3px 4px 0 0; padding: 1px 7px; border-radius: 10px;
  background: var(--chip-bg, #f0e9e0); color: var(--text, #6a5641); }
.scanned .scanned-tip { margin-top: 10px; line-height: 1.6; color: var(--muted, #9b8070); }
.diag { margin: 16px auto 0; max-width: 560px; text-align: left; }
.diag-h { font-size: 12.5px; font-weight: 700; color: var(--text, #4a3322); margin-bottom: 6px; }
.diag-t { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.diag-t th, .diag-t td { border: 1px solid var(--border, #eadfd2); padding: 4px 8px; }
.diag-t th { background: var(--panel-2, #faf6f0); font-weight: 650; color: var(--muted, #9b8070); }
.diag-t td.c { text-align: center; }
.diag-t tr.hot td { background: var(--primary-weak, #e8f1fb); }
.diag .scanned-tip { margin-top: 10px; line-height: 1.7; color: var(--muted, #9b8070); font-size: 11.5px; }
.tablewrap { overflow-x: auto; padding-bottom: 76px; }   /* 给悬浮批量条留出空间，避免遮住末行 */
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
thead th { text-align: left; padding: 10px 12px; font-size: 11.5px; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; color: var(--muted, #9b8070); background: var(--surface-2, rgba(160,120,80,.06)); white-space: nowrap; position: sticky; top: 0; z-index: 1; }
thead th.r, td.r { text-align: right; } .cbcol { width: 38px; }
tbody td { padding: 10px 12px; border-top: 1px solid var(--border, #eadfd2); white-space: nowrap; vertical-align: middle; }
tbody tr:nth-child(even) { background: color-mix(in srgb, var(--muted, #9b8070) 4%, transparent); }
tbody tr:hover { background: var(--surface-2, rgba(160,120,80,.08)); cursor: default; }
tbody tr.sel { background: color-mix(in srgb, var(--primary, #1565c0) 9%, transparent) !important; }
td.amt { font-variant-numeric: tabular-nums; font-weight: 700; color: var(--text, #4a3322); }
.ttlcell { white-space: normal; min-width: 220px; } .ttl { font-weight: 650; color: var(--text, #4a3322); }
.sub { font-size: 12px; color: var(--muted, #9b8070); margin-top: 1px; }
.tpl { color: var(--primary, #1565c0); font-weight: 600; }
.amt { font-weight: 700; font-variant-numeric: tabular-nums; color: var(--text, #4a3322); }
.payee { color: var(--text-2, #6b5a49); } .when { color: var(--muted, #9b8070); font-variant-numeric: tabular-nums; font-size: 12.5px; }
.cbx { width: 17px; height: 17px; accent-color: var(--primary, #1565c0); cursor: pointer; }
.pill { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 20px; }
.pill i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.p-run { color: var(--warn, #c47d0a); background: color-mix(in srgb, var(--warn, #c47d0a) 12%, transparent); }
.p-ok { color: var(--success, #2e9e5b); background: color-mix(in srgb, var(--success, #2e9e5b) 12%, transparent); }
.p-bad { color: var(--danger, #d64545); background: color-mix(in srgb, var(--danger, #d64545) 12%, transparent); }
.p-cancel { color: #8a7a68; background: rgba(138,122,104,.12); }
.sync { font-size: 12.5px; font-weight: 650; } .sync.no { color: var(--primary, #1565c0); } .sync.yes { color: var(--muted, #9b8070); } .sync.upd { color: var(--warn, #c47d0a); }
.sync .rec { font-size: 11px; color: var(--muted, #9b8070); font-variant-numeric: tabular-nums; }

.batchbar { position: fixed; left: 50%; transform: translateX(-50%); bottom: 22px; z-index: 40; display: flex; align-items: center; gap: 12px; background: #2c241d; color: #f4efe8; padding: 10px 12px 10px 20px; border-radius: 13px; box-shadow: 0 16px 40px -12px rgba(0,0,0,.5); }
.batchbar .n { font-size: 14px; } .batchbar .n b { font-size: 16px; font-weight: 800; color: #fff; }
.bb { border: none; padding: 9px 16px; border-radius: 9px; font-size: 13.5px; font-weight: 700; cursor: pointer; font-family: inherit; }
.bb.primary { background: var(--primary, #1565c0); color: #fff; } .bb.ghost { background: rgba(255,255,255,.15); color: #fff; }
.bb.x { background: none; color: rgba(255,255,255,.6); font-size: 17px; padding: 0 4px; }
.bb-enter-active, .bb-leave-active { transition: transform .26s, opacity .26s; }
.bb-enter-from, .bb-leave-to { transform: translateX(-50%) translateY(140%); opacity: 0; }

.scrim { position: fixed; inset: 0; background: rgba(30,22,14,.5); z-index: 60; display: flex; align-items: center; justify-content: center; padding: 20px; }
.modal { background: var(--card-bg, #fff); border-radius: 15px; width: min(660px, 100%); max-height: 86vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 50px -14px rgba(0,0,0,.4); }
.m-head { padding: 18px 22px 13px; border-bottom: 1px solid var(--border, #eadfd2); }
.m-head h3 { margin: 0; font-size: 17px; font-weight: 750; color: var(--text, #4a3322); } .m-head p { margin: 5px 0 0; font-size: 13px; color: var(--muted, #9b8070); }
.m-body { padding: 6px 22px; overflow: auto; }
.conflict { display: flex; gap: 9px; background: color-mix(in srgb, var(--primary, #1565c0) 8%, transparent); border-radius: 9px; padding: 10px 13px; font-size: 12.5px; color: var(--text, #4a3322); line-height: 1.55; margin: 12px 0; }
.mtable { width: 100%; border-collapse: collapse; font-size: 13px; }
.mtable th { text-align: left; padding: 8px 10px; font-size: 11px; text-transform: uppercase; color: var(--muted, #9b8070); border-bottom: 1px solid var(--border, #eadfd2); }
.mtable td { padding: 9px 10px; border-bottom: 1px solid var(--border, #eadfd2); }
.tag { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.tag.new { background: color-mix(in srgb, var(--primary, #1565c0) 14%, transparent); color: var(--primary, #1565c0); }
.tag.upd { background: color-mix(in srgb, var(--warn, #c47d0a) 16%, transparent); color: var(--warn, #c47d0a); }
.m-foot { padding: 14px 22px; border-top: 1px solid var(--border, #eadfd2); display: flex; gap: 10px; justify-content: flex-end; }
.btn { padding: 9px 18px; border-radius: 9px; font-size: 13.5px; font-weight: 700; cursor: pointer; font-family: inherit; border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--text-2, #6b5a49); }
.btn.primary { background: var(--primary, #1565c0); color: #fff; border-color: var(--primary, #1565c0); }
.btn:disabled { opacity: .6; cursor: default; }
</style>
