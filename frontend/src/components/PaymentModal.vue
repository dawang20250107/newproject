<script setup>
import { ref, watch } from 'vue'
import api from '../api/index.js'

const props = defineProps({
  payment: { type: Object, default: null },
  departments: { type: Array, default: () => [] },
})
const emit = defineEmits(['saved', 'close'])

const loading = ref(false)
const error = ref('')

const form = ref({})

function resetForm() {
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
}

watch(() => props.payment, resetForm, { immediate: true })

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const payload = { ...form.value }
    // clean empty date fields
    for (const k of ['pay1_date', 'pay2_date', 'pay3_date', 'pay1_amount', 'pay2_amount', 'pay3_amount']) {
      if (payload[k] === '') payload[k] = null
    }

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
        <button class="modal-close" @click="emit('close')">×</button>
      </div>

      <div v-if="error" class="alert alert-err">{{ error }}</div>

      <div class="form-row">
        <div class="form-group">
          <label>部门 *</label>
          <input v-if="!departments.length" v-model="form.department" placeholder="输入部门名称" />
          <select v-else v-model="form.department">
            <option value="">选择部门</option>
            <option v-for="d in departments" :key="d" :value="d">{{ d }}</option>
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

      <!-- installments -->
      <div class="section-title" style="font-size:14px;margin-top:8px">实际付款记录</div>
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
          {{ loading ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>
