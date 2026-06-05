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
const saveStatus = ref('')
const autoSaveErr = ref('')
let saveTimer = null
let isResetting = false

const DEPT_LIST = DEPT_CONST

const deptOptions = ref([])
const form = ref({})

// installments: array of {seq, pay_date, pay_amount, notes, id?}
const installments = ref([])

const FIELD_COLS = {
  department: ['department'],
  applicant: ['applicant'],
  approval_number: ['approval_number'],
  project_desc: ['project_desc', 'project_no'],
  payee: ['payee'],
  total_amount: ['total_amount'],
  planned_date: ['planned_date'],
  installments: ['installments'],
  notes: ['notes'],
  plan_adjustment: ['plan_adjustment'],
}

function _autoDefaultDept() {
  return ''
}

function resetForm() {
  isResetting = true
  const p = props.payment
  const isNew = !p?.id
  form.value = {
    department: p?.department || (isNew ? _autoDefaultDept() : ''),
    applicant: p?.applicant || '',
    approval_number: p?.approval_number || '',
    project_no: p?.project_no || '',
    project_desc: p?.project_desc || '',
    payee: p?.payee || '',
    total_amount: p?.total_amount || '',
    planned_date: p?.planned_date || '',
    notes: p?.notes || '',
    plan_adjustment: p?.plan_adjustment != null ? p.plan_adjustment : '',
  }
  // Restore installments from payment
  installments.value = (p?.installments || []).map((inst, i) => ({
    id: inst.id,
    seq: inst.seq || (i + 1),
    pay_date: inst.pay_date || '',
    pay_amount: inst.pay_amount && inst.pay_amount !== '0' ? inst.pay_amount : '',
    notes: inst.notes || '',
  }))

  const myDepts = auth.isAdmin ? null : (auth.user?.departments || [])
  const extra = props.departments.filter(d => !DEPT_LIST.includes(d))
  const allDepts = [...DEPT_LIST, ...extra]
  let opts = myDepts ? allDepts.filter(d => myDepts.includes(d)) : allDepts
  if (!isNew && p?.department && !opts.includes(p.department)) opts = [p.department, ...opts]
  deptOptions.value = opts
  nextTick(() => { isResetting = false })
}

watch(() => props.payment, resetForm, { immediate: true })

watch([form, installments], async () => {
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
  installments.value.reduce((s, i) => s + (parseFloat(i.pay_amount) || 0), 0)
)
const plannedTotal = computed(() => parseFloat(form.value.total_amount) || 0)
const adjustedTarget = computed(() => {
  const adj = parseFloat(form.value.plan_adjustment)
  return (!isNaN(adj) && adj > 0) ? adj : plannedTotal.value
})
const overpaid = computed(() => plannedTotal.value > 0 && paidSoFar.value > plannedTotal.value)
const remaining = computed(() => Math.max(0, adjustedTarget.value - paidSoFar.value))

// Installment helpers
function addInstallment() {
  const nextSeq = installments.value.length > 0
    ? Math.max(...installments.value.map(i => i.seq)) + 1
    : 1
  installments.value.push({ seq: nextSeq, pay_date: '', pay_amount: '', notes: '' })
}
function removeInstallment(idx) {
  installments.value.splice(idx, 1)
  // Re-assign seq
  installments.value.forEach((inst, i) => { inst.seq = i + 1 })
}

// 排款联动1：按项目编号查该项目的「预付」未核销余额（只读提示）
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

// 排款联动2：按收款方名称模糊匹配供应商池，弹出预付余额并可直接核销
const matchedSupplier = ref(null)
const supplierWoAdv = ref(null)
const supplierWoAmt = ref('')
const supplierWoDate = ref('')
const supplierWoNotes = ref('')
const supplierWoSaving = ref(false)
const supplierWoResult = ref('')
let supplierTimer = null

watch(() => form.value.payee, (payee) => {
  clearTimeout(supplierTimer)
  matchedSupplier.value = null
  supplierWoAdv.value = null
  const q = (payee || '').trim()
  if (q.length < 2) return
  supplierTimer = setTimeout(async () => {
    try {
      const res = await api.get('/ar/suppliers/search', {
        params: { q, dept: form.value.department || undefined }
      })
      const items = res.data?.items || []
      if (items.length > 0) matchedSupplier.value = items[0]
    } catch (_) { /* 静默 */ }
  }, 450)
})

function selectSupplierAdv(adv) {
  supplierWoAdv.value = adv
  supplierWoAmt.value = adv.balance_amount
  if (!supplierWoDate.value) supplierWoDate.value = new Date().toISOString().slice(0, 10)
}
function cancelSupplierWo() {
  supplierWoAdv.value = null; supplierWoAmt.value = ''; supplierWoNotes.value = ''
}
async function doSupplierWriteoff() {
  if (!(parseFloat(supplierWoAmt.value) > 0)) { alert('核销金额必须大于0'); return }
  if (!supplierWoDate.value) { alert('请填写核销日期'); return }
  supplierWoSaving.value = true
  try {
    await api.post(`/ar/advances/${supplierWoAdv.value.id}/writeoffs`, {
      amount: supplierWoAmt.value,
      writeoff_date: supplierWoDate.value,
      notes: supplierWoNotes.value || '',
      payment_id: props.payment?.id,
    })
    supplierWoResult.value = `已用预付 ¥${parseFloat(supplierWoAmt.value).toFixed(2)} 核销，预付余额已更新`
    cancelSupplierWo()
    const res = await api.get('/ar/suppliers/search', {
      params: { q: form.value.payee, dept: form.value.department || undefined }
    })
    const items = res.data?.items || []
    matchedSupplier.value = items.length > 0 ? items[0] : null
    setTimeout(() => { supplierWoResult.value = '' }, 4000)
  } catch (e) { alert(e?.msg || '核销失败') }
  finally { supplierWoSaving.value = false }
}

function buildPayload() {
  const payload = {}
  const includeAll = !props.payment?.id
  for (const [field, cols] of Object.entries(FIELD_COLS)) {
    if (field === 'installments') continue  // handled separately below
    if (includeAll || editable(field)) {
      for (const col of cols) payload[col] = form.value[col]
    }
  }
  if ('plan_adjustment' in payload) {
    payload.plan_adjustment = (payload.plan_adjustment === '' || payload.plan_adjustment === null)
      ? null : payload.plan_adjustment
  }
  // Include installments if user can edit them or if creating new
  if (includeAll || editable('installments')) {
    payload.installments = installments.value
      .filter(i => i.pay_date && parseFloat(i.pay_amount) > 0)
      .map((i, idx) => ({
        id: i.id || undefined,
        seq: idx + 1,
        pay_date: i.pay_date,
        pay_amount: i.pay_amount,
        notes: i.notes || '',
      }))
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
        <div v-if="vis('applicant')" class="form-group">
          <label>申请人 <span class="hint-text">选填</span></label>
          <input v-model="form.applicant" placeholder="如：张三" maxlength="100"
            :disabled="!editable('applicant')" />
        </div>
      </div>

      <div class="form-row">
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
          <!-- 供应商匹配 -->
          <div v-if="matchedSupplier" class="supplier-match">
            <div class="supplier-match-header">
              <span class="supplier-tag">{{ matchedSupplier.supplier_type === 'private' ? '私有' : '公共' }}供应商</span>
              <b>{{ matchedSupplier.name }}</b>
              <span class="supplier-dept">{{ matchedSupplier.delivery_dept }}</span>
              <span v-if="parseFloat(matchedSupplier.prepaid_balance) > 0" class="prepaid-bal">
                预付余额 ¥{{ parseFloat(matchedSupplier.prepaid_balance).toLocaleString('zh-CN', {minimumFractionDigits: 2}) }}
              </span>
              <span v-else class="no-bal">暂无未核销预付</span>
            </div>
            <div v-if="supplierWoResult" class="wo-success">{{ supplierWoResult }}</div>
            <div v-if="matchedSupplier.prepaid_advances?.length">
              <div class="adv-list-label">可冲抵预付明细：</div>
              <div v-for="adv in matchedSupplier.prepaid_advances" :key="adv.id" class="adv-row">
                <span class="adv-date">{{ adv.occur_date || '—' }}</span>
                <span class="adv-bal">¥{{ parseFloat(adv.balance_amount).toLocaleString('zh-CN', {minimumFractionDigits: 2}) }}</span>
                <span class="adv-notes">{{ adv.notes || '' }}</span>
                <button v-if="payment?.id && supplierWoAdv?.id !== adv.id"
                        class="btn-xs btn-offset" @click="selectSupplierAdv(adv)">用此预付核销</button>
                <span v-else-if="!payment?.id" class="adv-hint">（保存排款后可核销）</span>
              </div>
              <div v-if="supplierWoAdv" class="wo-inline">
                <span class="wo-inline-label">核销金额（元）</span>
                <input v-model="supplierWoAmt" type="number" step="0.01" class="wo-inp" />
                <span class="wo-inline-label">核销日期</span>
                <input v-model="supplierWoDate" type="date" class="wo-inp" />
                <input v-model="supplierWoNotes" class="wo-inp-wide" placeholder="备注（选填）" />
                <button class="btn-xs btn-primary-xs" :disabled="supplierWoSaving" @click="doSupplierWriteoff">
                  {{ supplierWoSaving ? '核销中…' : '确认核销' }}
                </button>
                <button class="btn-xs" @click="cancelSupplierWo">取消</button>
              </div>
            </div>
          </div>
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

      <!-- Installments section -->
      <div v-if="vis('installments')" class="section-title" style="font-size:13px;margin-top:4px">
        实际付款记录
        <span class="inst-count" v-if="installments.length > 0">（已录入 {{ installments.length }} 次）</span>
      </div>

      <div v-if="vis('installments')" class="inst-list">
        <div v-for="(inst, idx) in installments" :key="idx" class="inst-row">
          <span class="inst-seq">第{{ idx + 1 }}次</span>
          <div class="form-group inst-date-grp">
            <label>付款日期</label>
            <input v-model="inst.pay_date" type="date" :disabled="!editable('installments')" />
          </div>
          <div class="form-group inst-amt-grp">
            <label>付款金额 (元)</label>
            <input v-model="inst.pay_amount" type="number" min="0" step="0.01" placeholder="0.00"
                   :disabled="!editable('installments')" />
          </div>
          <div class="form-group inst-notes-grp">
            <label>备注</label>
            <input v-model="inst.notes" placeholder="选填" maxlength="200"
                   :disabled="!editable('installments')" />
          </div>
          <button v-if="editable('installments')" class="btn-xs btn-danger-xs inst-del"
                  @click="removeInstallment(idx)" title="删除此次付款">×</button>
        </div>

        <div v-if="installments.length === 0" class="inst-empty">暂无付款记录</div>

        <button v-if="editable('installments')" class="btn btn-ghost btn-sm inst-add-btn"
                @click="addInstallment">+ 添加付款</button>
      </div>

      <!-- Real-time paid-so-far summary -->
      <div v-if="vis('installments') && vis('total_amount') && plannedTotal > 0"
           class="pay-summary" :class="{ 'pay-over': overpaid }">
        <span>已录入：<strong>{{ paidSoFar.toFixed(2) }}</strong> 元</span>
        <span class="pay-sep">／</span>
        <span>计划：<strong>{{ plannedTotal.toFixed(2) }}</strong> 元</span>
        <span v-if="overpaid" class="pay-warn">⚠️ 超出计划总额</span>
        <span v-else-if="paidSoFar > 0" class="pay-ok">剩余 {{ remaining.toFixed(2) }} 元</span>
      </div>

      <div v-if="payment?.prepaid_offset_amount && parseFloat(payment.prepaid_offset_amount) > 0"
           class="prepaid-offset-tip">
        <span class="offset-icon">⚖️</span>
        已关联预付核销 <strong>¥{{ parseFloat(payment.prepaid_offset_amount).toLocaleString('zh-CN', {minimumFractionDigits: 2}) }}</strong>，现金流已扣除此金额防双重计
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

.prepaid-offset-tip {
  margin: 6px 0 2px;
  padding: 6px 10px;
  background: rgba(245,124,0,0.08);
  border-left: 3px solid #f57c00;
  border-radius: 4px;
  font-size: 12px;
  color: #e65100;
}
.offset-icon { margin-right: 4px; }

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

/* Installment section */
.inst-count { font-size: 12px; color: var(--muted); font-weight: 400; margin-left: 4px; }
.inst-list { margin-bottom: 10px; }
.inst-row {
  display: flex; align-items: flex-end; gap: 8px; flex-wrap: wrap;
  padding: 8px 10px; border-radius: 8px; margin-bottom: 6px;
  background: rgba(21,101,192,0.03); border: 1px solid rgba(21,101,192,0.1);
}
.inst-seq {
  font-size: 12px; font-weight: 700; color: var(--primary);
  min-width: 36px; padding-bottom: 6px; white-space: nowrap;
}
.inst-date-grp { flex: 0 0 140px; }
.inst-amt-grp  { flex: 0 0 140px; }
.inst-notes-grp { flex: 1; min-width: 100px; }
.inst-del {
  padding: 4px 10px; margin-bottom: 0; align-self: flex-end;
  border-color: rgba(198,40,40,0.4); color: #c62828;
  background: rgba(198,40,40,0.04);
}
.inst-del:hover { background: rgba(198,40,40,0.1); }
.inst-empty { font-size: 12px; color: var(--muted); padding: 8px 0; }
.inst-add-btn { margin-top: 4px; font-size: 12px; }

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

/* supplier match section */
.supplier-match { margin-top: 8px; padding: 10px 12px; border: 1px solid rgba(21,101,192,0.25);
  background: rgba(21,101,192,0.04); border-radius: 10px; font-size: 12px; }
.supplier-match-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.supplier-tag { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 11px; font-weight: 700;
  background: rgba(21,101,192,0.12); color: #1565c0; }
.supplier-dept { color: var(--muted); font-size: 11px; }
.prepaid-bal { color: #1565c0; font-weight: 700; }
.no-bal { color: var(--muted); font-size: 11px; }
.adv-list-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
.adv-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 5px 0;
  border-top: 1px dashed rgba(21,101,192,0.12); font-size: 12px; }
.adv-date { color: var(--muted); min-width: 80px; }
.adv-bal { font-weight: 700; color: #1565c0; }
.adv-notes { color: var(--muted); flex: 1; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px; }
.adv-hint { color: var(--muted); font-size: 11px; }
.wo-success { padding: 5px 8px; border-radius: 7px; background: rgba(46,125,50,0.1); color: #2e7d32;
  font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.wo-inline { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 8px;
  padding: 8px 10px; background: rgba(21,101,192,0.06); border-radius: 8px; }
.wo-inline-label { font-size: 11px; color: var(--muted); white-space: nowrap; }
.wo-inp { width: 110px; padding: 4px 7px; border: 1px solid var(--border); border-radius: 6px;
  font-size: 12px; background: var(--card); color: var(--text); }
.wo-inp-wide { flex: 1; min-width: 100px; padding: 4px 7px; border: 1px solid var(--border);
  border-radius: 6px; font-size: 12px; background: var(--card); color: var(--text); }
.btn-xs { padding: 3px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer;
  border: 1px solid var(--border); background: var(--card); color: var(--text); }
.btn-xs:hover { background: rgba(120,120,120,0.1); }
.btn-offset { border-color: #1565c0; color: #1565c0; background: rgba(21,101,192,0.06); }
.btn-offset:hover { background: rgba(21,101,192,0.12); }
.btn-primary-xs { border-color: var(--primary); background: var(--primary); color: #fff; }
.btn-primary-xs:hover { opacity: 0.88; }
.btn-primary-xs:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-danger-xs { }
</style>
