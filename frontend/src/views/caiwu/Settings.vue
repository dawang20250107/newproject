<script setup>
import { ref, onMounted } from 'vue'
import { BUSINESS_UNITS } from '../../constants.js'
import api from '../../api/caiwu.js'
import EmptyState from '../../components/EmptyState.vue'

const tab = ref('l1')  // 'l1' | 'l2' | 'l3'

// ── L1 categories ───────────────────────────────────────
const l1List = ref([])
const l1Loading = ref(false)
const showL1Form = ref(false)
const l1Form = ref({ id: null, name: '', sort_order: 0, is_profit_driver: false, is_calculated: false, sign: 1 })
const l1Err = ref('')

async function loadL1() {
  l1Loading.value = true
  try { const r = await api.get('/categories/l1'); l1List.value = r.data }
  catch (e) { l1Err.value = e?.error || '加载失败' }
  finally { l1Loading.value = false }
}

async function saveL1() {
  l1Err.value = ''
  if (!l1Form.value.name.trim()) { l1Err.value = '名称不能为空'; return }
  try {
    if (l1Form.value.id) {
      await api.put(`/categories/l1/${l1Form.value.id}`, l1Form.value)
    } else {
      await api.post('/categories/l1', l1Form.value)
    }
    showL1Form.value = false
    await loadL1()
  } catch (e) { l1Err.value = e?.error || '保存失败' }
}

async function deleteL1(id) {
  if (!confirm('确认删除该一级科目？')) return
  try { await api.delete(`/categories/l1/${id}`); await loadL1() }
  catch (e) { alert(e?.error || '删除失败') }
}

function openL1Form(cat = null) {
  l1Form.value = cat
    ? { id: cat.id, name: cat.name, sort_order: cat.sort_order, is_profit_driver: cat.is_profit_driver, is_calculated: cat.is_calculated, sign: cat.sign ?? 1 }
    : { id: null, name: '', sort_order: 0, is_profit_driver: false, is_calculated: false, sign: 1 }
  l1Err.value = ''
  showL1Form.value = true
}

// ── L2 categories ───────────────────────────────────────
const l2Bu = ref(BUSINESS_UNITS[0])
const l2List = ref([])
const showL2Form = ref(false)
const l2Form = ref({ id: null, name: '', sort_order: 0 })
const l2Err = ref('')

async function loadL2() {
  try { const r = await api.get('/categories/l2', { params: { bu: l2Bu.value } }); l2List.value = r.data }
  catch (e) { l2Err.value = e?.error || '加载失败' }
}

async function saveL2() {
  l2Err.value = ''
  if (!l2Form.value.name.trim()) { l2Err.value = '名称不能为空'; return }
  try {
    const body = { ...l2Form.value, business_unit: l2Bu.value }
    if (l2Form.value.id) await api.put(`/categories/l2/${l2Form.value.id}`, body)
    else await api.post('/categories/l2', body)
    showL2Form.value = false; await loadL2()
  } catch (e) { l2Err.value = e?.error || '保存失败' }
}

async function deleteL2(id) {
  if (!confirm('确认删除？')) return
  try { await api.delete(`/categories/l2/${id}`); await loadL2() }
  catch (e) { alert(e?.error || '删除失败') }
}

// ── L3 categories ───────────────────────────────────────
const l3Bu = ref(BUSINESS_UNITS[0])
const l3List = ref([])
const showL3Form = ref(false)
const l3Form = ref({ id: null, name: '', sort_order: 0, l1_category_id: null, kingdee_code: '' })
const l3Err = ref('')

async function loadL3() {
  try { const r = await api.get('/categories/l3', { params: { bu: l3Bu.value } }); l3List.value = r.data }
  catch (e) { l3Err.value = e?.error || '加载失败' }
}

async function saveL3() {
  l3Err.value = ''
  if (!l3Form.value.name.trim()) { l3Err.value = '名称不能为空'; return }
  try {
    const body = { ...l3Form.value, business_unit: l3Bu.value }
    if (l3Form.value.id) await api.put(`/categories/l3/${l3Form.value.id}`, body)
    else await api.post('/categories/l3', body)
    showL3Form.value = false; await loadL3()
  } catch (e) { l3Err.value = e?.error || '保存失败' }
}

async function deleteL3(id) {
  if (!confirm('确认删除？')) return
  try { await api.delete(`/categories/l3/${id}`); await loadL3() }
  catch (e) { alert(e?.error || '删除失败') }
}

function switchTab(t) {
  tab.value = t
  if (t === 'l1') loadL1()
  else if (t === 'l2') loadL2()
  else if (t === 'l3') loadL3()
}

onMounted(() => { loadL1() })
</script>

<template>
  <div>
    <div class="topbar"><h1>系统设置</h1></div>

    <div class="tab-bar">
      <button v-for="[k,l] in [['l1','一级科目'],['l2','二级项目部'],['l3','三级科目明细']]" :key="k"
        :class="['tab-btn', tab === k ? 'active' : '']" @click="switchTab(k)">{{ l }}
      </button>
    </div>

    <!-- ── L1 tab ──────────────────────────────────────── -->
    <div v-if="tab === 'l1'" class="card">
      <div class="card-head">
        <div class="section-title" style="margin:0">一级科目（全局通用）</div>
        <button class="btn btn-primary btn-sm" @click="openL1Form()">新增科目</button>
      </div>
      <div v-if="l1Err" class="error-banner">{{ l1Err }}</div>
      <EmptyState v-if="l1Loading" loading />
      <EmptyState v-else-if="!l1List.length" empty text="暂无一级科目，请先添加" />
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>排序</th><th>科目名称</th><th>类型</th><th>利润方向</th><th>瀑布图驱动</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="c in l1List" :key="c.id">
              <td style="color:var(--muted)">{{ c.sort_order }}</td>
              <td>
                {{ c.name }}
                <span v-if="c.is_calculated" class="badge badge-muted" style="margin-left:4px">计算行</span>
              </td>
              <td style="font-size:12px;color:var(--muted)">{{ c.is_calculated ? '自动推算' : '原始导入' }}</td>
              <td style="font-size:12px">
                <span v-if="c.sign === 1" style="color:var(--success)">+ 收入类</span>
                <span v-else style="color:var(--danger)">− 成本类</span>
              </td>
              <td><span v-if="c.is_profit_driver" class="badge badge-success">✓ 已标记</span></td>
              <td>
                <div style="display:flex;gap:6px">
                  <button class="btn btn-ghost btn-sm" @click="openL1Form(c)">编辑</button>
                  <button class="btn btn-danger btn-sm" @click="deleteL1(c.id)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── L2 tab ──────────────────────────────────────── -->
    <div v-else-if="tab === 'l2'" class="card">
      <div class="card-head">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="section-title" style="margin:0">二级项目部</div>
          <select v-model="l2Bu" class="sel-bu-sm" @change="loadL2">
            <option v-for="bu in BUSINESS_UNITS" :key="bu" :value="bu">{{ bu }}</option>
          </select>
        </div>
        <button class="btn btn-primary btn-sm" @click="showL2Form = true; l2Form = {id:null,name:'',sort_order:0}; l2Err=''">新增</button>
      </div>
      <div v-if="l2Err" class="error-banner">{{ l2Err }}</div>
      <EmptyState v-if="!l2List.length" empty text="暂无项目部" />
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>排序</th><th>项目部名称</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="c in l2List" :key="c.id">
              <td style="color:var(--muted)">{{ c.sort_order }}</td>
              <td>{{ c.name }}</td>
              <td>
                <div style="display:flex;gap:6px">
                  <button class="btn btn-ghost btn-sm" @click="l2Form={id:c.id,name:c.name,sort_order:c.sort_order};l2Err='';showL2Form=true">编辑</button>
                  <button class="btn btn-danger btn-sm" @click="deleteL2(c.id)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── L3 tab ──────────────────────────────────────── -->
    <div v-else-if="tab === 'l3'" class="card">
      <div class="card-head">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="section-title" style="margin:0">三级科目明细</div>
          <select v-model="l3Bu" class="sel-bu-sm" @change="loadL3">
            <option v-for="bu in BUSINESS_UNITS" :key="bu" :value="bu">{{ bu }}</option>
          </select>
        </div>
        <button class="btn btn-primary btn-sm" @click="l3Form={id:null,name:'',sort_order:0,l1_category_id:null};l3Err='';showL3Form=true">新增</button>
      </div>
      <div v-if="l3Err" class="error-banner">{{ l3Err }}</div>
      <EmptyState v-if="!l3List.length" empty text="暂无三级科目明细" />
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>排序</th><th>科目明细</th><th>所属一级</th><th>金蝶编码</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="c in l3List" :key="c.id">
              <td style="color:var(--muted)">{{ c.sort_order }}</td>
              <td>{{ c.name }}</td>
              <td>{{ c.l1_name || '-' }}</td>
              <td style="font-size:12px;color:var(--muted);font-family:monospace">{{ c.kingdee_code || '-' }}</td>
              <td>
                <div style="display:flex;gap:6px">
                  <button class="btn btn-ghost btn-sm" @click="l3Form={id:c.id,name:c.name,sort_order:c.sort_order,l1_category_id:c.l1_category_id,kingdee_code:c.kingdee_code||''};l3Err='';showL3Form=true">编辑</button>
                  <button class="btn btn-danger btn-sm" @click="deleteL3(c.id)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── Modals ─────────────────────────────────────── -->
    <Transition name="fade">
      <div v-if="showL1Form" class="modal-mask" @click.self="showL1Form = false">
        <div class="modal-box" style="max-width:380px">
          <h2>{{ l1Form.id ? '编辑' : '新增' }}一级科目</h2>
          <div v-if="l1Err" class="error-banner">{{ l1Err }}</div>
          <div class="form-row"><label>科目名称</label><input v-model="l1Form.name" placeholder="如：主营业务收入" /></div>
          <div class="form-row"><label>排序（数字越小越靠前）</label><input v-model.number="l1Form.sort_order" type="number" /></div>
          <div class="form-row">
            <label>利润方向</label>
            <select v-model.number="l1Form.sign">
              <option :value="1">+1 收入类（金额越大利润越高）</option>
              <option :value="-1">−1 成本/费用类（金额越大利润越低）</option>
            </select>
          </div>
          <div class="form-row" style="display:flex;align-items:center;gap:8px;margin-top:4px">
            <input id="l1calc" type="checkbox" v-model="l1Form.is_calculated" style="width:auto;margin:0" />
            <label for="l1calc" style="margin:0;cursor:pointer">
              计算行（由系统自动推算，不可导入原始数据）
            </label>
          </div>
          <div class="form-row" style="display:flex;align-items:center;gap:8px;margin-top:4px">
            <input id="l1pd" type="checkbox" v-model="l1Form.is_profit_driver" style="width:auto;margin:0" />
            <label for="l1pd" style="margin:0;cursor:pointer">标记为「利润驱动因素」（瀑布图分析用）</label>
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="showL1Form = false">取消</button>
            <button class="btn btn-primary" @click="saveL1">保存</button>
          </div>
        </div>
      </div>
    </Transition>

    <Transition name="fade">
      <div v-if="showL2Form" class="modal-mask" @click.self="showL2Form = false">
        <div class="modal-box" style="max-width:360px">
          <h2>{{ l2Form.id ? '编辑' : '新增' }}项目部</h2>
          <div v-if="l2Err" class="error-banner">{{ l2Err }}</div>
          <div class="form-row"><label>项目部名称</label><input v-model="l2Form.name" /></div>
          <div class="form-row"><label>排序</label><input v-model.number="l2Form.sort_order" type="number" /></div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="showL2Form = false">取消</button>
            <button class="btn btn-primary" @click="saveL2">保存</button>
          </div>
        </div>
      </div>
    </Transition>

    <Transition name="fade">
      <div v-if="showL3Form" class="modal-mask" @click.self="showL3Form = false">
        <div class="modal-box" style="max-width:380px">
          <h2>{{ l3Form.id ? '编辑' : '新增' }}三级科目</h2>
          <div v-if="l3Err" class="error-banner">{{ l3Err }}</div>
          <div class="form-row"><label>科目明细名称</label><input v-model="l3Form.name" /></div>
          <div class="form-row">
            <label>所属一级科目（可选）</label>
            <select v-model="l3Form.l1_category_id">
              <option :value="null">不指定</option>
              <option v-for="c in l1List" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>金蝶科目编码（可选）</label>
            <input v-model="l3Form.kingdee_code" placeholder="如 6001.03.01" style="font-family:monospace" />
          </div>
          <div class="form-row"><label>排序</label><input v-model.number="l3Form.sort_order" type="number" /></div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="showL3Form = false">取消</button>
            <button class="btn btn-primary" @click="saveL3">保存</button>
          </div>
        </div>
      </div>
    </Transition>

  </div>
</template>

<style scoped>
/* ── 顶部栏 ─────────────────────────────────────────── */
.topbar { margin-bottom: 10px; }

/* ── 标签页（更紧凑）────────────────────────────────── */
.tab-bar { display: flex; gap: 3px; margin-bottom: 12px; background: var(--bg2); border-radius: 10px; padding: 3px; width: fit-content; }
.tab-btn { padding: 6px 14px; border-radius: 8px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; color: var(--muted); background: none; transition: all .16s; }
.tab-btn:hover { color: var(--primary); }
.tab-btn.active { background: var(--card); color: var(--primary); box-shadow: 0 1px 5px rgba(100,60,30,.12); }

/* ── 卡片（收紧内边距）─────────────────────────────── */
.card { padding: 13px 14px; }

/* 卡片头部：标题 + 操作按钮一行对齐 */
.card-head {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 8px; margin-bottom: 10px;
}

/* ── 科目列表表格（收紧行高/单元格内边距）──────────── */
.card :deep(table) { font-size: 13px; }
.card :deep(th),
.card :deep(td) { padding: 7px 12px; }

/* 业务单元选择器（紧凑下拉）*/
.sel-bu-sm { width: auto; min-width: 120px; padding: 5px 10px; font-size: 13px; border-radius: 8px; }

/* 错误提示条（紧凑）*/
.error-banner {
  margin-bottom: 10px; padding: 7px 11px; border-radius: 8px;
  font-size: 13px; color: var(--danger, #c62828);
  background: rgba(198,40,40,0.08); border: 1px solid rgba(198,40,40,0.18);
}

/* ── 弹窗（全局 .modal-box padding:0，此处补上紧凑内边距）── */
.modal-box { padding: 20px 22px; }
.modal-box h2 { font-size: 16px; font-weight: 700; margin-bottom: 12px; }
/* 表单行更紧凑：单列堆叠、收紧间距 */
.modal-box :deep(.form-row) { grid-template-columns: 1fr; gap: 5px; margin-bottom: 10px; }
.modal-box :deep(.form-row label) { font-size: 13px; color: var(--muted); }
.modal-box :deep(.form-row input),
.modal-box :deep(.form-row select) { padding: 7px 11px; font-size: 13px; border-radius: 8px; }
/* 操作按钮行：右对齐、收紧上方间距 */
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
</style>
