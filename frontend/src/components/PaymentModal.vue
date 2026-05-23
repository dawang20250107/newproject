<script setup>
import { ref, watch, nextTick } from 'vue'
import api from '../api/index.js'

const props = defineProps({
  payment: { type: Object, default: null },
  departments: { type: Array, default: () => [] },
})
const emit = defineEmits(['saved', 'close'])

const loading = ref(false)
const error = ref('')
const saveStatus = ref('')  // '' | 'saving' | 'saved' | 'error'
let saveTimer = null
let isResetting = false

const DEPT_LIST = [
  '集团总部', '劳务事业部', '运输事业部', '自营事业部',
  '阔展事业部', '多式联运事业部', '供应链事业部',
]

const deptOptions = ref([])
const form = ref({})

function resetForm() {
  isResetting = true
  const p = props.payment
  form.value = {
    department: p?.department || '',
    approval_number: p?.approval_number || '',
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
  }
  const extra = props.departments.filter(d => !DEPT_LIST.includes(d))
  deptOptions.value = [...DEPT_LIST, ...extra]
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
    setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = '' }, 2200)
  } catch {
    saveStatus.value = 'error'
  }
}

function buildPayload() {
  const payload = { ...form.value }
  for (const k of ['pay1_date', 'pay2_date', 'pay3_date', 'pay1_amount', 'pay2_amount', 'pay3_amount']) {
    if (payload[k] === '' || payload[k] === null) payload[k] = null
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
    error.value = e?.error || '保存失败，请重试'
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
            <span v-else-if="saveStatus === 'error'" class="save-status save-err">保存失败</span>
          </Transition>
          <button class="modal-close" @click="emit('close')">×</button>
        </div>
      </div>

      <div v-if="error" class="alert alert-err">{{ error }}</div>

      <div class="form-row">
        <div class="form-group">
          <label>部门 *</label>
          <select v-model="form.department">
            <option value="">请选择部门</option>
            <option v-for="d in deptOptions" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>审批单号</label>
          <input v-model="form.approval_number" placeholder="可选" />
        </div>
      </div>

      <div class="form-row full">
        <div class="form-group">
          <label>付款事项描述 *</label>
          <textarea v-model="form.project_desc" rows="2" placeholder="描述付款用途"></textarea>
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label>收款方 *</label>
          <input v-model="form.payee" placeholder="收款单位/个人" />
        </div>
        <div class="form-group">
          <label>计划总金额 (元) *</label>
          <input v-model="form.total_amount" type="number" step="0.01" placeholder="0.00" />
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label>计划付款日期 *</label>
          <input v-model="form.planned_date" type="date" />
        </div>
        <div class="form-group">
          <label>备注</label>
          <input v-model="form.notes" placeholder="可选" />
        </div>
      </div>

      <div class="section-title" style="font-size:13px;margin-top:4px">实际付款记录</div>
      <div class="inst-row">
        <div class="form-group">
          <label>第1次日期</label>
          <input v-model="form.pay1_date" type="date" />
        </div>
        <div class="form-group">
          <label>第1次金额 (元)</label>
          <input v-model="form.pay1_amount" type="number" step="0.01" placeholder="0.00" />
        </div>
      </div>
      <div class="inst-row">
        <div class="form-group">
          <label>第2次日期</label>
          <input v-model="form.pay2_date" type="date" />
        </div>
        <div class="form-group">
          <label>第2次金额 (元)</label>
          <input v-model="form.pay2_amount" type="number" step="0.01" placeholder="0.00" />
        </div>
      </div>
      <div class="inst-row">
        <div class="form-group">
          <label>第3次日期</label>
          <input v-model="form.pay3_date" type="date" />
        </div>
        <div class="form-group">
          <label>第3次金额 (元)</label>
          <input v-model="form.pay3_amount" type="number" step="0.01" placeholder="0.00" />
        </div>
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
</style>
