<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { DEPARTMENTS as DEPT_CONST } from '../constants.js'
import { fmtMoney } from '../utils/format.js'

const props = defineProps({
  payment: { type: Object, default: null },
  departments: { type: Array, default: () => [] },
})
const emit = defineEmits(['saved', 'close'])

const auth = useAuthStore()
function vis(key) { return auth.canView(key) }
function editable(key) { return auth.canEdit(key) }

const loading = ref(false)
const error = ref('')
const saveStatus = ref('')  // '' | 'saving' | 'saved' | 'error'
const autoSaveErr = ref('')
let saveTimer = null
let isResetting = false

const DEPT_LIST = DEPT_CONST

const deptOptions = ref([])
const form = ref({})

const FIELD_COLS = {
  department: ['department'],
  approval_number: ['approval_number'],
  project_desc: ['project_desc', 'project_no'],
  payee: ['payee'],
  total_amount: ['total_amount'],
  planned_date: ['planned_date'],
  pay1: ['pay1_date', 'pay1_amount'],
  pay2: ['pay2_date', 'pay2_amount'],
  pay3: ['pay3_date', 'pay3_amount'],
  notes: ['notes'],
  plan_adjustment: ['plan_adjustment'],
}

function _autoDefaultDept() {
  // Always empty on new records — user must explicitly choose a department.
  return ''
}

function resetForm() {
  isResetting = true
  const p = props.payment
  const isNew = !p?.id
  form.value = {
    department: p?.department || (isNew ? _autoDefaultDept() : ''),
    approval_number: p?.approval_number || '',
    project_no: p?.project_no || '',
    project_desc: p?.project_desc || '',
    payee: p?.payee || '',
    total_amount: p?.total_amount || '',
    planned_date: p?.planned_date || '',
    pay1_date: p?.pay1_date || '',
    pay1_amount: p?.pay1_amount && p.pay1_amount !== '0' ? p.pay1_amount : '',
    pay2_date: p?.pay2_date || '',
    pay2_amount: p?.pay2_amount && p.pay2_amount !== '0' ? p.pay2_amount : '',
    pay3_date: p?.pay3_date || '',
    pay3_amount: p?.pay3_amount && p.pay3_amount !== '0' ? p.pay3_amount : '',
    notes: p?.notes || '',
    plan_adjustment: p?.plan_adjustment != null ? p.plan_adjustment : '',
  }
  // Non-admin users only see their own departments; admin sees all.
  const myDepts = auth.isAdmin ? null : (auth.user?.departments || [])
  const extra = props.departments.filter(d => !DEPT_LIST.includes(d))
  const allDepts = [...DEPT_LIST, ...extra]
  let opts = myDepts ? allDepts.filter(d => myDepts.includes(d)) : allDepts
  // When editing, never drop the record's existing department from the choices.
  if (!isNew && p?.department && !opts.includes(p.department)) opts = [p.department, ...opts]
  deptOptions.value = opts
  nextTick(() => { isResetting = false })
}

watch(() => props.payment, resetForm, { immediate: true })

// Autosave — only for editing existing records
watch(form, async () => {
  if (!props.payment?.id || isResetting) return
  clearTimeout(saveTimer)
  saveStatus.value = 'saving'
  saveTimer = setTimeout(autosave, 1400)
}, { deep: true })

async function autosave() {
  try {
    await api.put(`/payments/${props.payment.id}`, buildPayload())
    saveStatus.value = 'saved'
    autoSaveErr.value = ''
    setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = '' }, 2200)
  } catch (e) {
    saveStatus.value = 'error'
    autoSaveErr.value = e?.msg || '自动保存失败'
  }
}

// Real-time installment tracker
const paidSoFar = computed(() =>
  (parseFloat(form.value.pay1_amount) || 0) +
  (parseFloat(form.value.pay2_amount) || 0) +
  (parseFloat(form.value.pay3_amount) || 0)
)
const plannedTotal = computed(() => parseFloat(form.value.total_amount) || 0)
const adjustedTarget = computed(() => {
  const adj = parseFloat(form.value.plan_adjustment)
  return (!isNaN(adj) && adj > 0) ? adj : plannedTotal.value
})
const overpaid = computed(() => plannedTotal.value > 0 && paidSoFar.value > plannedTotal.value)
const remaining = computed(() => Math.max(0, adjustedTarget.value - paidSoFar.value))

// 排款联动：按项目编号查该项目的「预付」未核销余额（只读提示）
const prepaid = ref(null)
let prepaidTimer = null
watch(() => form.value.project_no, (no) => {
  clearTimeout(prepaidTimer)
  prepaid.value = null
  const v = (no || '').trim()
  if (!v) return
  prepaidTimer = setTimeout(async () => {
    try {
      const res = await api.get('/payments/prepaid-balance', { params: { project_no: v } })
      if (res.data?.matched && res.data.count > 0) prepaid.value = res.data
    } catch (_) { /* 静默 */ }
  }, 400)
})

function buildPayload() {
  const payload = {}
  const includeAll = !props.payment?.id
  for (const [field, cols] of Object.entries(FIELD_COLS)) {
    if (includeAll || editable(field)) {
      for (const col of cols) payload[col] = form.value[col]
    }
  }
  for (const k of ['pay1_date', 'pay2_date', 'pay3_date', 'pay1_amount', 'pay2_amount', 'pay3_amount']) {
    if (k in payload && (payload[k] === '' || payload[k] === null)) payload[k] = null
  }
  if ('plan_adjustment' in payload) {
    payload.plan_adjustment = (payload.plan_adjustment === '' || payload.plan_adjustment === null)
      ? null : payload.plan_adjustment
  }
  return payload
}

async function submit() {
  error.value = ''
  loading.value = true
  clearTimeout(saveTimer)
  try {
    const payload = buildPayload()
    let res
    if (props.payment?.id) {
      res = await api.put(`/payments/${props.payment.id}`, payload)
    } else {
      res = await api.post('/payments', payload)
    }
    emit('saved', res.data)
  } catch (e) {
    error.value = e?.msg || '保存失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-header">
        <h3>{{ payment ? '编辑排款记录' : '新增排款记录' }}</h3>
        <div style="display:flex;align-items:center;gap:12px">
          <Transition name="status-fade">
            <span v-if="saveStatus === 'saving'" class="save-status saving">
              <span class="save-spin"></span>自动保存中…
            </span>
            <span v-else-if="saveStatus === 'saved'" class="save-status saved">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 6l3 3 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
              已保存
            </span>
            <span v-else-if="saveStatus === 'error'" class="save-status save-err" :title="autoSaveErr">
              ⚠ {{ autoSaveErr || '自动保存失败' }}
            </span>
          </Transition>
          <button class="modal-close" @click="emit('close')">×</button>
        </div>
      </div>

      <div v-if="error" class="alert alert-err">{{ error }}</div>

      <div class="form-row">
        <div v-if="vis('department')" class="form-group">
          <label>部门 *</label>
          <select v-model="form.department" :disabled="!editable('department')">
            <option value="">请选择部门</option>
            <option v-for="d in deptOptions" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <div v-if="vis('approval_number')" class="form-group">
          <label>审批单号 <span class="hint-text">21位数字，可选</span></label>
          <input v-model="form.approval_number" placeholder="填写则需为21位数字" maxlength="21"
            :disabled="!editable('approval_number')"
            :class="{ 'input-warn': form.approval_number && !/^\d{21}$/.test(form.approval_number) }" />
          <span v-if="form.approval_number && !/^\d{21}$/.test(form.approval_number)" class="field-err">
            已输入 {{ form.approval_number.replace(/\D/g, '').length }} 位数字，需满21位
          </span>
        </div>
      </div>

      <div v-if="vis('project_desc')" class="form-row full">
        <div class="form-group">
          <label>项目编号 <span class="lbl-tip">（选填，关联项目台账以弹出预付余额）</span></label>
          <input v-model="form.project_no" placeholder="如 GYL-20260301-0001，可手工填写" :disabled="!editable('project_desc')" maxlength="20" />
          <div v-if="prepaid" class="prepaid-hint">
            <span class="prepaid-tag">预付余额</span>
            该项目「{{ prepaid.short_name }}」尚有 <b>{{ prepaid.count }}</b> 笔预付未核销，余额合计
            <b>{{ fmtMoney(prepaid.total_balance) }}</b>，付款前请确认是否应先以预付核销冲抵。
          </div>
        </div>
      </div>

      <div v-if="vis('project_desc')" class="form-row full">
        <div class="form-group">
          <label>付款事项描述 *</label>
          <textarea v-model="form.project_desc" rows="2" placeholder="描述付款用途" :disabled="!editable('project_desc')"></textarea>
        </div>
      </div>

      <div class="form-row">
        <div v-if="vis('payee')" class="form-group">
          <label>收款方 *</label>
          <input v-model="form.payee" placeholder="收款单位/个人" :disabled="!editable('payee')" />
        </div>
        <div v-if="vis('total_amount')" class="form-group">
          <label>计划总金额 (元) *</label>
          <input v-model="form.total_amount" type="number" min="0" step="0.01" placeholder="0.00" :disabled="!editable('total_amount')" />
        </div>
      </div>

      <div class="form-row">
        <div v-if="vis('planned_date')" class="form-group">
          <label>计划付款日期 *</label>
          <input v-model="form.planned_date" type="date" :disabled="!editable('planned_date')" />
        </div>
        <div v-if="vis('notes')" class="form-group">
          <label>备注</label>
          <input v-model="form.notes" placeholder="可选" :disabled="!editable('notes')" />
        </div>
      </div>

      <div v-if="vis('plan_adjustment')" class="form-row full">
        <div class="form-group">
          <label>计划调整金额 (元)
            <span class="hint-text">
              填写后以此金额为实付目标：已付 ≥ 调整金额则自动结清；留空表示仍以计划总额为目标
            </span>
          </label>
          <input v-model="form.plan_adjustment" type="number" min="0" step="0.01"
                 placeholder="如：20000（实际只需付2万，填写后达到即结清）"
                 :disabled="!editable('plan_adjustment')" />
          <span v-if="form.plan_adjustment && parseFloat(form.plan_adjustment) > 0"
                class="field-hint">
            调整后目标：{{ parseFloat(form.plan_adjustment).toFixed(2) }} 元 ／
            剩余 {{ Math.max(0, parseFloat(form.plan_adjustment) - paidSoFar).toFixed(2) }} 元
          </span>
        </div>
      </div>

      <div v-if="vis('pay1') || vis('pay2') || vis('pay3')" class="section-title" style="font-size:13px;margin-top:4px">实际付款记录</div>
      <div v-if="vis('pay1')" class="inst-row">
        <div class="form-group">
          <label>第1次日期</label>
          <input v-model="form.pay1_date" type="date" :disabled="!editable('pay1')" />
        </div>
        <div class="form-group">
          <label>第1次金额 (元)</label>
          <input v-model="form.pay1_amount" type="number" min="0" step="0.01" placeholder="0.00" :disabled="!editable('pay1')" />
        </div>
      </div>
      <div v-if="vis('pay2')" class="inst-row">
        <div class="form-group">
          <label>第2次日期</label>
          <input v-model="form.pay2_date" type="date" :disabled="!editable('pay2')" />
        </div>
        <div class="form-group">
          <label>第2次金额 (元)</label>
          <input v-model="form.pay2_amount" type="number" min="0" step="0.01" placeholder="0.00" :disabled="!editable('pay2')" />
        </div>
      </div>
      <div v-if="vis('pay3')" class="inst-row">
        <div class="form-group">
          <label>第3次日期</label>
          <input v-model="form.pay3_date" type="date" :disabled="!editable('pay3')" />
        </div>
        <div class="form-group">
          <label>第3次金额 (元)</label>
          <input v-model="form.pay3_amount" type="number" min="0" step="0.01" placeholder="0.00" :disabled="!editable('pay3')" />
        </div>
      </div>

      <!-- Real-time paid-so-far vs total indicator (only when pay fields and total are visible) -->
      <div v-if="(vis('pay1') || vis('pay2') || vis('pay3')) && vis('total_amount') && plannedTotal > 0"
           class="pay-summary" :class="{ 'pay-over': overpaid }">
        <span>已录入：<strong>{{ paidSoFar.toFixed(2) }}</strong> 元</span>
        <span class="pay-sep">／</span>
        <span>计划：<strong>{{ plannedTotal.toFixed(2) }}</strong> 元</span>
        <span v-if="overpaid" class="pay-warn">⚠️ 超出计划总额</span>
        <span v-else-if="paidSoFar > 0" class="pay-ok">剩余 {{ remaining.toFixed(2) }} 元</span>
      </div>

      <div class="modal-footer">
        <button class="btn btn-ghost" @click="emit('close')">取消</button>
        <button class="btn btn-primary" :disabled="loading" @click="submit">
          <span v-if="loading" class="save-spin btn-spin"></span>
          {{ loading ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.save-status {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 12px; border-radius: 6px; padding: 3px 9px;
  white-space: nowrap;
}
.saving  { background: rgba(21,101,192,0.1); color: #1565c0; }
.saved   { background: rgba(46,125,50,0.1); color: #2e7d32; }
.save-err { background: rgba(198,40,40,0.1); color: #c62828; }

.save-spin {
  width: 10px; height: 10px; border-radius: 50%;
  border: 1.5px solid rgba(21,101,192,0.3);
  border-top-color: #1565c0;
  animation: spin 0.7s linear infinite;
  display: inline-block; flex-shrink: 0;
}
.btn-spin { border-color: rgba(255,255,255,0.35) !important; border-top-color: white !important; }

@keyframes spin { to { transform: rotate(360deg); } }

.status-fade-enter-active, .status-fade-leave-active { transition: opacity 0.2s, transform 0.2s; }
.status-fade-enter-from { opacity:0; transform:translateY(-4px); }
.status-fade-leave-to   { opacity:0; transform:translateY(-4px); }

.hint-text { font-size: 11px; color: var(--muted); font-weight: 400; margin-left: 4px; }

.pay-summary {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 14px; border-radius: 8px; margin-bottom: 14px;
  background: rgba(46, 125, 50, 0.07);
  border: 1px solid rgba(46, 125, 50, 0.18);
  font-size: 13px; color: #2e7d32;
  transition: background 0.2s, border-color 0.2s;
}
.pay-summary.pay-over {
  background: rgba(198, 40, 40, 0.07);
  border-color: rgba(198, 40, 40, 0.25);
  color: #c62828;
}
.pay-sep { opacity: 0.45; }
.pay-warn { font-weight: 700; margin-left: 6px; }
.pay-ok { color: #2e7d32; opacity: 0.75; margin-left: 6px; }
.input-warn { border-color: #f57f17 !important; background: rgba(245,127,23,0.04) !important; }
.field-err { font-size: 11px; color: #f57f17; margin-top: 3px; display: block; }
.field-hint { font-size: 11px; color: #1565c0; margin-top: 3px; display: block; }
.lbl-tip { font-size: 11px; color: var(--muted); font-weight: 400; }
.prepaid-hint { margin-top: 7px; padding: 8px 10px; border: 1px solid rgba(201,99,66,0.3);
  background: rgba(201,99,66,0.07); border-radius: 9px; font-size: 12px; color: var(--text); line-height: 1.5; }
.prepaid-hint b { color: var(--primary); }
.prepaid-tag { display: inline-block; padding: 1px 7px; border-radius: 999px; background: var(--primary);
  color: #fff; font-size: 11px; font-weight: 600; margin-right: 6px; }
</style>
