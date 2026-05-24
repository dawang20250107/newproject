<script setup>
import { ref } from 'vue'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  level: { type: Number, default: 1 },
  total: { type: Number, default: 0 },
})

const collapsed = ref(new Set())

function toggle(id) {
  if (collapsed.value.has(id)) collapsed.value.delete(id)
  else collapsed.value.add(id)
}

function fmt(n) {
  const v = parseFloat(n || 0)
  if (Math.abs(v) >= 100000000) return (v / 100000000).toFixed(2) + ' 亿'
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(2) + ' 万'
  return v.toFixed(2)
}
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th v-if="level >= 2" style="width:28px"></th>
          <th>一级科目</th>
          <th v-if="level >= 2">二级项目部</th>
          <th v-if="level >= 3">三级科目明细</th>
          <th class="amt">金额</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="row.l1_id">
          <!-- L1 row -->
          <tr :class="['l1-row', level >= 2 ? 'clickable' : '']" @click="level >= 2 && toggle(row.l1_id)">
            <td v-if="level >= 2" class="toggle-cell">
              <span class="toggle-icon">{{ collapsed.has(row.l1_id) ? '›' : '⌄' }}</span>
            </td>
            <td class="l1-name" :colspan="level >= 3 ? 2 : 1">{{ row.l1_name }}</td>
            <td v-if="level >= 2 && level < 3"></td>
            <td class="amt l1-amt" :class="row.amount < 0 ? 'amt-red' : ''">{{ fmt(row.amount) }}</td>
          </tr>

          <!-- L2 rows -->
          <template v-if="level >= 2 && !collapsed.has(row.l1_id)">
            <template v-for="l2 in (row.children || [])" :key="l2.l2_id">
              <tr class="l2-row">
                <td></td>
                <td></td>
                <td class="l2-name">{{ l2.l2_name }}</td>
                <td v-if="level >= 3"></td>
                <td class="amt" :class="l2.amount < 0 ? 'amt-red' : ''">{{ fmt(l2.amount) }}</td>
              </tr>

              <!-- L3 rows -->
              <template v-if="level >= 3">
                <tr v-for="l3 in (l2.children || [])" :key="l3.l3_id" class="l3-row">
                  <td></td>
                  <td></td>
                  <td></td>
                  <td class="l3-name">{{ l3.l3_name }}</td>
                  <td class="amt" :class="l3.amount < 0 ? 'amt-red' : ''">{{ fmt(l3.amount) }}</td>
                </tr>
              </template>
            </template>
          </template>
        </template>

        <!-- Total row -->
        <tr class="total-row">
          <td v-if="level >= 2"></td>
          <td :colspan="level >= 3 ? 3 : (level >= 2 ? 2 : 1)" style="font-weight:700">合计</td>
          <td class="amt total-amt" :class="total < 0 ? 'amt-red' : ''">{{ fmt(total) }}</td>
        </tr>
      </tbody>
    </table>

    <div v-if="!rows.length" class="empty">
      <div class="icon">📭</div>本期暂无数据
    </div>
  </div>
</template>

<style scoped>
.clickable { cursor: pointer; }
.clickable:hover td { background: rgba(201,99,66,.04); }
.toggle-cell { width: 32px; color: var(--muted); font-size: 14px; text-align: center; }
.toggle-icon { display: inline-block; transition: transform .15s; }

.l1-row td { font-weight: 600; background: rgba(201,99,66,.03); }
.l1-name { font-weight: 700; }
.l1-amt { font-weight: 700; font-size: 14px; }
.l2-row td { background: transparent; }
.l2-name { color: var(--text); padding-left: 24px !important; }
.l3-row td { background: rgba(200,185,170,.05); }
.l3-name { color: var(--muted); padding-left: 44px !important; font-size: 12px; }

.total-row td {
  font-weight: 800; border-top: 2px solid var(--border);
  background: rgba(201,99,66,.06); font-size: 14px;
}
.total-amt { font-size: 16px; color: var(--primary); }
</style>
