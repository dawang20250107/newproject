<script setup>
defineProps({
  invoiceStatus: { type: String, default: '' },
  isOverdue: { type: Boolean, default: false },
  overdueDays: { type: Number, default: 0 },
  isCurrent: { type: Boolean, default: false },
  isNotDue: { type: Boolean, default: false },
  reconciliationStatus: { type: String, default: '' },
})
</script>

<template>
  <span v-if="isOverdue" class="badge badge-overdue">逾期{{ overdueDays }}天</span>
  <span v-else-if="isCurrent" class="badge badge-current">当期</span>
  <span v-else-if="isNotDue" class="badge badge-notdue">未到期</span>
  <span v-if="invoiceStatus === '已结清'" class="badge badge-settled">已结清</span>
  <span v-else-if="invoiceStatus === '部分回款'" class="badge badge-partial">部分回款</span>
  <span v-else-if="invoiceStatus === '已开票'" class="badge badge-invoiced">已开票</span>
  <span v-else-if="invoiceStatus === '未开票'" class="badge badge-uninvoiced">未开票</span>
</template>

<style scoped>
.badge {
  display: inline-block; font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: 10px; margin: 0 2px;
}
.badge-overdue   { background: rgba(198,40,40,.12); color: #c62828; border: 1px solid rgba(198,40,40,.25); }
.badge-current   { background: rgba(21,101,192,.1); color: #1565c0; border: 1px solid rgba(21,101,192,.22); }
.badge-notdue    { background: rgba(46,125,50,.1); color: #2e7d32; border: 1px solid rgba(46,125,50,.22); }
.badge-settled   { background: rgba(120,100,85,.1); color: #786455; border: 1px solid rgba(120,100,85,.2); }
.badge-partial   { background: rgba(245,127,23,.12); color: #e65100; border: 1px solid rgba(245,127,23,.25); }
.badge-invoiced  { background: rgba(21,101,192,.1); color: #1565c0; border: 1px solid rgba(21,101,192,.22); }
.badge-uninvoiced{ background: rgba(158,158,158,.12); color: #757575; border: 1px solid rgba(158,158,158,.22); }
</style>
