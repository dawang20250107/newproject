<script setup>
import { ref, reactive, computed } from 'vue'
import api from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import { confirmDlg } from '../composables/confirm.js'
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
  { k: 'month', l: '本月' }, { k: 'q', l: '本季度' }, { k: 'd30', l: '近30天' },
]
function setQuick(k) {
  const t = todayCST(); const [y, m] = t.split('-').map(Number)
  if (k === 'month') { range.start = `${t.slice(0, 8)}01`; range.end = t }
  else if (k === 'd30') { const d = new Date(t); d.setDate(d.getDate() - 30); range.start = d.toISOString().slice(0, 10); range.end = t }
  else if (k === 'q') { const qm = Math.floor((m - 1) / 3) * 3 + 1; range.start = `${y}-${String(qm).padStart(2, '0')}-01`; range.end = t }
}

// ── 可见模板（勾选后再查，避免全表扫描超时；也用于确认"报销"是否在可见范围）──────
const templates = ref([])          // [{process_code, name}]
const tplSel = ref(new Set())      // 勾选的 process_code
const tplLoading = ref(false)
const tplErr = ref('')
const tplFilter = ref('')
const tplShown = computed(() => {
  const q = tplFilter.value.trim()
  return q ? templates.value.filter(t => (t.name || t.process_code).includes(q)) : templates.value
})
const tplSelCount = computed(() => tplSel.value.size)
// 手动添加的模板（processCode 从钉钉后台"编辑模板"URL 获取）。持久化到本地，长期生效——
// 用于覆盖官方接口取不到的模板（如仅"可审批/管理"而非"可发起"的费用报销单）。
const MANUAL_KEY = 'dt_manual_tpls'
function loadManual() {
  try { return JSON.parse(localStorage.getItem(MANUAL_KEY) || '[]') } catch { return [] }
}
const manualTpls = ref(loadManual())
const manualCodes = computed(() => new Set(manualTpls.value.map(t => t.process_code)))
function saveManual() { localStorage.setItem(MANUAL_KEY, JSON.stringify(manualTpls.value)) }
function removeManual(code) {
  manualTpls.value = manualTpls.value.filter(t => t.process_code !== code); saveManual()
  templates.value = templates.value.filter(t => t.process_code !== code)
  const s = new Set(tplSel.value); s.delete(code); tplSel.value = s
}
function mergeManual(list) {
  const have = new Set(list.map(t => t.process_code))
  const extra = manualTpls.value.filter(t => !have.has(t.process_code))
                               .map(t => ({ ...t, manual: true }))
  return [...list, ...extra]
}
async function loadTemplates(userid) {
  tplLoading.value = true; tplErr.value = ''; templates.value = []
  try {
    const r = await api.post('/dingtalk/templates', { userid }, { timeout: 60000 })
    templates.value = mergeManual(r.data?.templates || [])
    tplSel.value = new Set(templates.value.map(t => t.process_code))   // 默认全选
  } catch (e) {
    tplErr.value = e?.msg || e?.error || '获取模板失败'
    // 接口失败也保留手动模板，至少能查这些
    templates.value = mergeManual([])
    tplSel.value = new Set(templates.value.map(t => t.process_code))
  } finally { tplLoading.value = false }
}
function toggleTpl(code) {
  const s = new Set(tplSel.value)
  s.has(code) ? s.delete(code) : s.add(code)
  tplSel.value = s
}
function tplSelectAll(on) {
  tplSel.value = on ? new Set(templates.value.map(t => t.process_code)) : new Set()
}

// ── 从员工导入模板：报销单等"仅可审批/管理"的模板，本人可发起清单里没有，
//    但发起它的员工清单里有。解析一个会发起该审批的员工 → 列出其可发起模板 →
//    勾选加入本地模板库（长期生效）。全程无需 processCode，纯 App 可用。────────────
const importOpen = ref(false)
const importMode = ref('name')
const importInput = ref('')
const importResolving = ref(false)
const importCands = ref([])
const importUser = ref(null)
const importTpls = ref([])
const importLoading = ref(false)
const importFilter = ref('')
const importShown = computed(() => {
  const q = importFilter.value.trim()
  return q ? importTpls.value.filter(t => (t.name || t.process_code).includes(q)) : importTpls.value
})
async function importFetchTpls(userid) {
  importLoading.value = true; importTpls.value = []
  try {
    const r = await api.post('/dingtalk/templates', { userid }, { timeout: 60000 })
    importTpls.value = r.data?.templates || []
  } catch (e) { toast.error(e?.msg || e?.error || '获取该员工模板失败') }
  finally { importLoading.value = false }
}
async function importResolve() {
  const val = importInput.value.trim()
  if (!val) { toast.error('请输入该员工的手机号或姓名'); return }
  importResolving.value = true; importCands.value = []; importUser.value = null; importTpls.value = []
  try {
    const body = importMode.value === 'mobile' ? { mobile: val } : { name: val }
    const r = await api.post('/dingtalk/resolve-user', body)
    const users = r.data?.users || []
    if (!users.length) { toast.error('钉钉通讯录未找到该人员'); return }
    if (users.length === 1) { importUser.value = users[0]; await importFetchTpls(users[0].userid) }
    else importCands.value = users
  } catch (e) { toast.error(e?.msg || e?.error || '查询人员失败') }
  finally { importResolving.value = false }
}
async function importPickCand(u) { importUser.value = u; importCands.value = []; await importFetchTpls(u.userid) }
function isInCatalog(code) { return templates.value.some(t => t.process_code === code) }
function addImported(t) {
  if (isInCatalog(t.process_code)) { toast.error('该模板已在列表中'); return }
  if (!manualCodes.value.has(t.process_code)) {
    manualTpls.value = [...manualTpls.value, { process_code: t.process_code, name: t.name || t.process_code }]
    saveManual()
  }
  templates.value = [...templates.value, { ...t, manual: true }]
  tplSel.value = new Set([...tplSel.value, t.process_code])
  toast.success(`已加入「${t.name || t.process_code}」`)
}

// ── 结果 ──────────────────────────────────────────────────────────────────
const loading = ref(false)
const loadErr = ref('')
const items = ref([])
const capped = ref(false)
const scanned = ref([])        // 本次查询实际扫描的模板名（用于确认报销等是否已覆盖）
const queried = ref(false)     // 是否已发起过一次查询
const sel = ref(new Set())
const selCount = computed(() => sel.value.size)
const DING = {
  approved: ['ok', '已通过'], rejected: ['bad', '已拒绝'],
  pending: ['run', '审批中'], canceled: ['cancel', '已撤销'],
}
const stats = computed(() => {
  const s = items.value
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
    if (users.length === 1) { picked.value = users[0]; await loadTemplates(users[0].userid); return users[0] }
    candidates.value = users; return null   // 多个同名 → 交用户选
  } catch (e) { toast.error(e?.msg || e?.error || '查询人员失败'); return null }
  finally { resolving.value = false }
}
async function pickCandidate(u) { picked.value = u; candidates.value = []; await loadTemplates(u.userid); runQuery() }
function copyUid() {
  if (!picked.value) return
  navigator.clipboard?.writeText(picked.value.userid).then(() => toast.success('已复制 userid')).catch(() => {})
}

async function runQuery() {
  let user = picked.value
  if (!user) { user = await resolvePerson(); if (!user) return }
  if (templates.value.length && !tplSel.value.size) { toast.error('请至少勾选一个审批模板'); return }
  loading.value = true; loadErr.value = ''; sel.value = new Set()
  try {
    // 只查勾选的模板并逐条拉详情，耗时较长，单独放宽超时到 90s
    const r = await api.post('/dingtalk/query', {
      userid: user.userid, start: range.start, end: range.end, status: status.value,
      process_codes: [...tplSel.value],
    }, { timeout: 90000 })
    items.value = r.data?.items || []
    capped.value = !!r.data?.capped
    scanned.value = r.data?.templates_scanned || []
    queried.value = true
  } catch (e) { loadErr.value = e?.msg || e?.error || '查询失败'; items.value = [] }
  finally { loading.value = false }
}
function onStatusTab(v) { status.value = v; if (picked.value) runQuery() }

// ── 勾选 ──────────────────────────────────────────────────────────────────
function toggle(id) { const s = new Set(sel.value); s.has(id) ? s.delete(id) : s.add(id); sel.value = s }
const pageAllSel = computed(() => items.value.length > 0 && items.value.every(i => sel.value.has(i.instance_id)))
function toggleAll() {
  const s = new Set()
  if (!pageAllSel.value) items.value.forEach(i => s.add(i.instance_id))
  sel.value = s
}
function selQuick(kind) {
  const s = new Set()
  items.value.forEach(i => {
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

    <!-- 查询条 -->
    <div class="dt-query">
      <div class="qf">
        <label>查询人员</label>
        <div class="person">
          <div class="seg">
            <button :class="{ on: personMode === 'mobile' }" @click="personMode = 'mobile'; picked = null">手机号</button>
            <button :class="{ on: personMode === 'name' }" @click="personMode = 'name'; picked = null">姓名</button>
          </div>
          <input v-model="personInput" class="inp" :placeholder="personMode === 'mobile' ? '钉钉手机号' : '姓名（可能多个同名）'"
                 @keyup.enter="runQuery()" @input="picked = null" />
          <span v-if="picked" class="picked" :title="'userid: ' + picked.userid">✓ {{ picked.name }} <code class="uid" @click="copyUid">{{ picked.userid }}</code></span>
        </div>
        <!-- 同名候选 -->
        <div v-if="candidates.length" class="cands">
          <span class="cands-lbl">多个同名，请选择：</span>
          <button v-for="u in candidates" :key="u.userid" class="cand" @click="pickCandidate(u)">{{ u.name }}</button>
        </div>
      </div>
      <div class="qf">
        <label>时间范围</label>
        <div class="daterow">
          <input v-model="range.start" type="date" class="inp inp-date" />
          <span class="sep">→</span>
          <input v-model="range.end" type="date" class="inp inp-date" />
          <button v-for="q in QUICK" :key="q.k" class="quick" @click="setQuick(q.k)">{{ q.l }}</button>
        </div>
      </div>
      <button class="go" :disabled="loading || resolving" @click="runQuery()">
        {{ loading || resolving ? '查询中…' : '查询' }}
      </button>
      <button class="quick test" :disabled="testing" @click="testConnection">{{ testing ? '检测中…' : '测试连接' }}</button>
    </div>

    <!-- 可见模板勾选（勾选后再查，避免全表扫描超时；也用于确认"报销"是否可见）-->
    <div v-if="picked" class="dt-tpls">
      <div class="tpls-head">
        <span class="tpls-lbl">审批模板</span>
        <span v-if="tplLoading" class="tpls-info">加载模板中…</span>
        <template v-else>
          <span class="tpls-info">可见 <b>{{ templates.length }}</b> 个 · 已选 <b>{{ tplSelCount }}</b></span>
          <button class="tpls-op" @click="tplSelectAll(true)">全选</button>
          <button class="tpls-op" @click="tplSelectAll(false)">全不选</button>
          <input v-model="tplFilter" class="tpls-filter" placeholder="筛选模板名，如 报销" />
          <span class="grow"></span>
          <span class="tpls-tip">勾选越少查得越快；缩小时间范围也能提速</span>
        </template>
      </div>
      <div v-if="tplErr" class="tpls-err">⚠️ {{ tplErr }}</div>
      <div v-else-if="!tplLoading" class="tpls-grid">
        <label v-for="t in tplShown" :key="t.process_code" class="tplitem" :class="{ on: tplSel.has(t.process_code) }">
          <input type="checkbox" class="cbx" :checked="tplSel.has(t.process_code)" @change="toggleTpl(t.process_code)" />
          <span class="tplname">{{ t.name || t.process_code }}</span>
          <span v-if="t.manual" class="tplmanual" title="手动添加，点击移除" @click.prevent="removeManual(t.process_code)">手动 ✕</span>
        </label>
        <div v-if="!tplShown.length" class="tpls-empty">
          无匹配模板{{ tplFilter ? '（换个关键词）' : '' }}。官方接口只返回「可发起」模板，
          仅「可审批/管理」的费用报销单需在下方手动添加。
        </div>
      </div>
      <!-- 补充模板：官方接口只返回"可发起"模板，报销单等"仅可审批/管理"的需在此补入 -->
      <div v-if="!tplLoading" class="tpls-add">
        <span class="add-lbl">缺模板（如报销）？</span>
        <button class="add-btn ghost" :class="{ on: importOpen }" @click="importOpen = !importOpen">
          从员工导入 ▾
        </button>
        <span class="add-hint">选一个会「发起」该审批的员工，从他的模板里勾选加入（无需 processCode）</span>
      </div>

      <!-- 从员工导入模板 -->
      <div v-if="importOpen && !tplLoading" class="tpls-import">
        <div class="imp-row">
          <div class="seg sm">
            <button :class="{ on: importMode === 'name' }" @click="importMode = 'name'">姓名</button>
            <button :class="{ on: importMode === 'mobile' }" @click="importMode = 'mobile'">手机号</button>
          </div>
          <input v-model="importInput" class="add-inp code" :placeholder="importMode === 'mobile' ? '会发起报销的员工手机号' : '会发起报销的员工姓名'" @keyup.enter="importResolve" />
          <button class="add-btn" :disabled="importResolving" @click="importResolve">{{ importResolving ? '查找中…' : '查找' }}</button>
          <span v-if="importUser" class="imp-user">✓ {{ importUser.name }}</span>
        </div>
        <div v-if="importCands.length" class="cands">
          <span class="cands-lbl">多个同名，请选择：</span>
          <button v-for="u in importCands" :key="u.userid" class="cand" @click="importPickCand(u)">{{ u.name }}</button>
        </div>
        <div v-if="importLoading" class="imp-tip">加载该员工可发起模板中…</div>
        <template v-else-if="importUser">
          <div class="imp-bar">
            <span class="imp-tip">该员工可发起 {{ importTpls.length }} 个模板，点「＋」加入：</span>
            <input v-model="importFilter" class="tpls-filter" placeholder="筛选，如 报销" />
          </div>
          <div class="imp-grid">
            <div v-for="t in importShown" :key="t.process_code" class="impitem" :class="{ dim: isInCatalog(t.process_code) }">
              <span class="tplname">{{ t.name || t.process_code }}</span>
              <button class="imp-add" :disabled="isInCatalog(t.process_code)" @click="addImported(t)">{{ isInCatalog(t.process_code) ? '已加' : '＋' }}</button>
            </div>
            <div v-if="!importShown.length" class="imp-tip">无匹配模板</div>
          </div>
        </template>
      </div>
    </div>

    <!-- 状态页签 -->
    <div class="dt-tabs">
      <button v-for="s in STATUS" :key="s.v" :class="['dt-tab', { on: status === s.v }]" @click="onStatusTab(s.v)">{{ s.l }}</button>
    </div>

    <!-- 汇总条 + 快捷选 -->
    <div v-if="items.length" class="dt-summary">
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
    <div class="dt-body">
      <div v-if="loadErr" class="empty err">⚠️ {{ loadErr }}</div>
      <div v-else-if="loading" class="empty">⏳ 正在从钉钉拉取…</div>
      <div v-else-if="!picked && !items.length" class="empty hint">
        <div class="hint-i">🔗</div>
        <div class="hint-t">按人查询钉钉审批</div>
        <div class="hint-s">输入手机号或姓名、选时间范围，查出该员工在钉钉里的待处理 / 已处理审批，勾选后同步进「审批管理」。</div>
      </div>
      <div v-else-if="!items.length" class="empty">
        <div>该员工在此范围内无「{{ STATUS.find(s => s.v === status).l }}」的审批</div>
        <div v-if="scanned.length" class="scanned">
          已扫描 {{ scanned.length }} 个模板：<span v-for="(t, i) in scanned" :key="i" class="tplchip">{{ t }}</span>
          <div class="scanned-tip">若这里没有你要的模板（如「报销」），说明该模板对此人不可见 / 应用未授权，请换用发起该审批的本人查询，或联系钉钉管理员在应用可用范围内放开。</div>
        </div>
      </div>
      <div v-else class="tablewrap">
        <table>
          <thead>
            <tr>
              <th class="cbcol"><input type="checkbox" class="cbx" :checked="pageAllSel" @change="toggleAll" /></th>
              <th>审批标题 / 编号</th><th>发起人</th><th class="r">金额</th><th>收款方</th>
              <th>钉钉状态</th><th>发起时间</th><th>同步状态</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in items" :key="i.instance_id" :class="{ sel: sel.has(i.instance_id) }">
              <td><input type="checkbox" class="cbx" :checked="sel.has(i.instance_id)" @change="toggle(i.instance_id)" /></td>
              <td class="ttlcell">
                <div class="ttl">{{ i.title }}</div>
                <div class="sub"><span class="tpl">{{ i.template }}</span> · {{ i.approval_number || '—' }}</div>
              </td>
              <td>{{ i.applicant }}<div class="sub">{{ i.department }}</div></td>
              <td class="r amt">¥{{ Number(i.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</td>
              <td class="payee">{{ i.payee }}</td>
              <td><span class="pill" :class="'p-' + DING[i.ding_status][0]"><i></i>{{ DING[i.ding_status][1] }}</span></td>
              <td class="when">{{ (i.create_time || '').replace('T', ' ').slice(0, 16) }}</td>
              <td>
                <span v-if="!i.synced" class="sync no">● 未同步</span>
                <span v-else-if="i.sync_stale" class="sync upd">◑ 待刷新 <span class="rec">{{ i.sync_rec_no }}</span></span>
                <span v-else class="sync yes">✓ 已同步 <span class="rec">{{ i.sync_rec_no }}</span></span>
              </td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 批量条 -->
    <Transition name="bb">
      <div v-if="selCount" class="batchbar">
        <span class="n">已选 <b>{{ selCount }}</b> 条</span>
        <button class="bb primary" :disabled="syncing" @click="openPreview">同步至审批管理</button>
        <button class="bb ghost" :disabled="syncing" @click="refreshStatus">刷新选中状态</button>
        <button class="bb x" @click="clearSel">✕</button>
      </div>
    </Transition>

    <!-- 同步预览弹窗 -->
    <Teleport to="body">
      <div v-if="previewOpen" class="scrim" @click.self="previewOpen = false">
        <div class="modal">
          <div class="m-head">
            <h3>同步至审批管理 · 预览</h3>
            <p>按钉钉实例 ID 去重：已存在的更新状态/金额，其余新建。</p>
          </div>
          <div class="m-body">
            <div class="conflict">
              <span>ℹ</span>
              <span>共 <b>{{ selCount }}</b> 条：<b>{{ newCount }}</b> 条新建、<b>{{ updCount }}</b> 条更新。字段映射：申请人 / 部门 / 金额 / 收款方 / 摘要按通用规则从钉钉表单提取，原始表单整单留存。</span>
            </div>
            <table class="mtable">
              <thead><tr><th>钉钉审批</th><th class="r">金额</th><th>处理</th></tr></thead>
              <tbody>
                <tr v-for="i in selectedItems" :key="i.instance_id">
                  <td><div class="ttl">{{ i.title }}</div><div class="sub">{{ i.applicant }} · {{ i.department }}</div></td>
                  <td class="r amt">¥{{ Number(i.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</td>
                  <td><span class="tag" :class="i.synced ? 'upd' : 'new'">{{ i.synced ? '更新' : '新建' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="m-foot">
            <button class="btn" @click="previewOpen = false">取消</button>
            <button class="btn primary" :disabled="syncing" @click="doSync">{{ syncing ? '同步中…' : `确认同步 ${selCount} 条` }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dt { display: flex; flex-direction: column; min-height: 0; padding: 0; }
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
.dt-tpls { padding: 12px 18px; border-bottom: 1px solid var(--border, #eadfd2); background: var(--panel-2, #faf6f0); }
.tpls-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.tpls-lbl { font-size: 13px; font-weight: 700; color: var(--text, #4a3322); }
.tpls-info { font-size: 12.5px; color: var(--muted, #9b8070); }
.tpls-info b { color: var(--primary, #1565c0); }
.tpls-op { border: 1px solid var(--border, #eadfd2); background: var(--panel, #fff); border-radius: 6px; padding: 3px 10px; font-size: 12px; cursor: pointer; color: var(--text, #4a3322); font-family: inherit; }
.tpls-op:hover { border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); }
.tpls-filter { border: 1px solid var(--border, #eadfd2); border-radius: 6px; padding: 3px 9px; font-size: 12.5px; width: 150px; font-family: inherit; background: var(--panel, #fff); color: inherit; }
.tpls-tip { font-size: 11.5px; color: var(--muted, #9b8070); }
.tpls-err { font-size: 12.5px; color: var(--danger, #d64545); }
.tpls-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 6px 12px; max-height: 168px; overflow-y: auto; }
.tplitem { display: flex; align-items: center; gap: 7px; padding: 4px 8px; border-radius: 6px; cursor: pointer; font-size: 12.5px; color: var(--text, #4a3322); border: 1px solid transparent; }
.tplitem:hover { background: var(--panel, #fff); }
.tplitem.on { background: var(--primary-weak, #e8f1fb); border-color: var(--primary-border, #c3ddf5); }
.tplname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tplmanual { flex: none; font-size: 10.5px; color: var(--danger, #d64545); background: var(--danger-weak, #fdeaea); padding: 0 5px; border-radius: 8px; cursor: pointer; }
.tpls-empty { grid-column: 1 / -1; font-size: 12.5px; color: var(--muted, #9b8070); padding: 6px 2px; line-height: 1.6; }
.tpls-add { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border, #eadfd2); }
.add-lbl { font-size: 12.5px; font-weight: 650; color: var(--text, #4a3322); }
.add-hint { font-size: 11.5px; color: var(--muted, #9b8070); }
.add-inp { border: 1px solid var(--border, #eadfd2); border-radius: 6px; padding: 4px 9px; font-size: 12.5px; font-family: inherit; background: var(--panel, #fff); color: inherit; }
.add-inp.code { width: 240px; }
.add-btn { border: none; background: var(--primary, #1565c0); color: #fff; border-radius: 6px; padding: 5px 14px; font-size: 12.5px; font-weight: 650; cursor: pointer; font-family: inherit; }
.add-btn:hover { filter: brightness(1.05); }
.add-btn.ghost { background: var(--panel, #fff); color: var(--primary, #1565c0); border: 1px solid var(--primary, #1565c0); }
.add-btn.ghost.on { background: var(--primary-weak, #e8f1fb); }

.tpls-import { margin-top: 10px; padding: 12px; border: 1px dashed var(--primary-border, #c3ddf5); border-radius: 8px; background: var(--panel, #fff); }
.imp-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.seg.sm button { padding: 4px 10px; font-size: 12px; }
.imp-user { font-size: 12.5px; color: var(--ok, #2e9e6b); font-weight: 650; }
.imp-bar { display: flex; align-items: center; gap: 10px; margin: 10px 0 6px; flex-wrap: wrap; }
.imp-tip { font-size: 12px; color: var(--muted, #9b8070); }
.imp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 6px 10px; max-height: 200px; overflow-y: auto; }
.impitem { display: flex; align-items: center; gap: 6px; padding: 5px 8px; border: 1px solid var(--border, #eadfd2); border-radius: 6px; font-size: 12.5px; }
.impitem.dim { opacity: .5; }
.impitem .tplname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.imp-add { flex: none; width: 26px; height: 22px; border: none; border-radius: 5px; background: var(--primary, #1565c0); color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; }
.imp-add:disabled { background: var(--border, #eadfd2); color: var(--muted, #9b8070); cursor: default; }

.dt-tabs { display: flex; gap: 2px; padding: 0 12px; border-bottom: 1px solid var(--border, #eadfd2); }
.dt-tab { border: none; background: none; padding: 11px 16px; font-size: 14px; font-weight: 650; color: var(--muted, #9b8070); cursor: pointer; font-family: inherit; border-bottom: 2.5px solid transparent; margin-bottom: -1px; }
.dt-tab.on { color: var(--primary, #1565c0); border-bottom-color: var(--primary, #1565c0); }

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
.tablewrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
thead th { text-align: left; padding: 10px 12px; font-size: 11.5px; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; color: var(--muted, #9b8070); background: var(--surface-2, rgba(160,120,80,.06)); white-space: nowrap; position: sticky; top: 0; z-index: 1; }
thead th.r, td.r { text-align: right; } .cbcol { width: 38px; }
tbody td { padding: 11px 12px; border-top: 1px solid var(--border, #eadfd2); white-space: nowrap; vertical-align: middle; }
tbody tr:hover { background: var(--surface-2, rgba(160,120,80,.05)); }
tbody tr.sel { background: color-mix(in srgb, var(--primary, #1565c0) 8%, transparent); }
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
