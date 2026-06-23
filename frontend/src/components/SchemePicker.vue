<script setup>
// 通用「筛选方案」下拉（表格方案基座 UI）：配合 useTableSchemes 使用，任意列表页可复用。
// 私有/公共分组展示、设默认（★）、保存当前列头筛选+排序为命名方案。
const props = defineProps({
  ctl: { type: Object, required: true },        // useTableSchemes(...) 的返回
  canPublic: { type: Boolean, default: false }, // 是否允许创建公共方案（写权限）
  isSuperAdmin: { type: Boolean, default: false },
})
const c = props.ctl
</script>

<template>
  <div class="sp-wrap">
    <button class="sp-btn" :class="{ on: c.showDrop.value }" title="保存/加载筛选方案（私有/公共）"
            @click="c.showDrop.value = !c.showDrop.value">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
      方案<span v-if="c.schemes.value.length" class="sp-badge">{{ c.schemes.value.length }}</span>
    </button>
    <div v-if="c.showDrop.value" class="sp-drop">
      <div class="sp-save-row">
        <input v-model="c.newName.value" class="sp-name-input" placeholder="方案名称…" maxlength="40"
               @keyup.enter="c.saveCurrent()" />
        <button class="sp-save-btn" :disabled="!c.newName.value.trim() || !c.hasState()" @click="c.saveCurrent()">保存</button>
      </div>
      <div class="sp-scope-row">
        <span class="sp-scope-lbl">范围</span>
        <button class="sp-scope-seg" :class="{ on: c.newScope.value === 'private' }" @click="c.newScope.value = 'private'">私有</button>
        <button class="sp-scope-seg" :class="{ on: c.newScope.value === 'public' }"
                :disabled="!canPublic" :title="canPublic ? '团队共享' : '需写入权限'"
                @click="c.newScope.value = 'public'">公共（团队共享）</button>
      </div>

      <div v-if="!c.loaded.value" class="sp-empty">加载中…</div>
      <template v-else>
        <div v-if="c.mySchemes.value.length" class="sp-grp">我的方案</div>
        <div v-for="s in c.mySchemes.value" :key="s.id" class="sp-item" @click="c.applyScheme(s)">
          <button class="sp-star" :class="{ on: c.isDefault(s) }"
                  :title="c.isDefault(s) ? '默认方案（进入页面自动套用）· 点击取消' : '设为默认方案'"
                  @click.stop="c.toggleDefault(s)">{{ c.isDefault(s) ? '★' : '☆' }}</button>
          <span class="sp-name">{{ s.name }}</span>
          <button class="sp-del" @click.stop="c.remove(s)">✕</button>
        </div>

        <div v-if="c.publicSchemes.value.length" class="sp-grp">公共方案 <i>团队共享</i></div>
        <div v-for="s in c.publicSchemes.value" :key="s.id" class="sp-item" @click="c.applyScheme(s)">
          <button class="sp-star" :class="{ on: c.isDefault(s) }"
                  :title="c.isDefault(s) ? '默认方案 · 点击取消' : '设为默认方案'"
                  @click.stop="c.toggleDefault(s)">{{ c.isDefault(s) ? '★' : '☆' }}</button>
          <span class="sp-name">{{ s.name }}<span class="sp-pub">公</span></span>
          <span class="sp-owner" :title="`创建人：${s.owner_name || '—'}`">{{ s.owner_name || '—' }}</span>
          <button v-if="c.isMine(s) || isSuperAdmin" class="sp-del" @click.stop="c.remove(s)">✕</button>
        </div>

        <div v-if="!c.schemes.value.length" class="sp-empty">暂无方案，设好筛选后点「保存」</div>
      </template>
    </div>
    <div v-if="c.showDrop.value" class="sp-backdrop" @click="c.showDrop.value = false"></div>
  </div>
</template>

<style scoped>
.sp-wrap { position: relative; }
.sp-btn {
  display: flex; align-items: center; gap: 5px; padding: 4px 9px; font-size: 12px; font-weight: 500;
  border: 1.5px solid var(--border); border-radius: 6px; background: #fff; color: var(--text); cursor: pointer; white-space: nowrap;
}
.sp-btn:hover, .sp-btn.on { border-color: var(--primary); color: var(--primary); }
.sp-badge { background: var(--primary); color: #fff; border-radius: 8px; padding: 0 5px; font-size: 10px; font-weight: 700; }
.sp-drop {
  position: absolute; top: calc(100% + 6px); right: 0; z-index: 200;
  background: #fff; border: 1.5px solid var(--border); border-radius: 10px;
  box-shadow: 0 6px 20px rgba(0,0,0,0.12); min-width: 250px; padding: 8px 0;
}
.sp-backdrop { position: fixed; inset: 0; z-index: 199; }
.sp-save-row { display: flex; gap: 6px; padding: 6px 10px 8px; border-bottom: 1px solid var(--border); }
.sp-name-input { flex: 1; padding: 5px 8px; font-size: 12px; border: 1px solid var(--border); border-radius: 6px; outline: none; }
.sp-name-input:focus { border-color: var(--primary); }
.sp-save-btn { padding: 5px 10px; font-size: 12px; white-space: nowrap; border: none; border-radius: 6px; background: var(--primary); color: #fff; cursor: pointer; }
.sp-save-btn:disabled { opacity: .45; cursor: default; }
.sp-scope-row { display: flex; align-items: center; gap: 5px; padding: 7px 10px; border-bottom: 1px solid var(--border); }
.sp-scope-lbl { font-size: 11px; color: var(--muted); }
.sp-scope-seg { flex: 1; padding: 4px 6px; font-size: 11px; border: 1px solid var(--border); border-radius: 6px; background: #fff; color: var(--muted); cursor: pointer; white-space: nowrap; }
.sp-scope-seg.on { border-color: var(--primary); background: rgba(201,99,66,0.08); color: var(--primary); font-weight: 600; }
.sp-scope-seg:disabled { opacity: .4; cursor: not-allowed; }
.sp-grp { font-size: 11px; color: var(--muted); font-weight: 700; padding: 8px 12px 3px; }
.sp-grp i { font-weight: 400; font-style: normal; color: #c9963f; }
.sp-pub { font-size: 9px; background: #c9963f; color: #fff; border-radius: 3px; padding: 0 3px; margin-left: 4px; vertical-align: middle; }
.sp-empty { padding: 10px 12px; font-size: 12px; color: var(--muted); }
.sp-item { display: flex; align-items: center; gap: 6px; padding: 7px 12px; cursor: pointer; font-size: 13px; }
.sp-item:hover { background: rgba(201,99,66,0.05); }
.sp-star { border: none; background: none; cursor: pointer; color: var(--muted); font-size: 14px; padding: 0 2px; line-height: 1; }
.sp-star.on, .sp-star:hover { color: #f5a623; }
.sp-name { flex: 1; font-weight: 500; }
.sp-owner { font-size: 11px; color: var(--muted); }
.sp-del { border: none; background: none; color: var(--muted); cursor: pointer; padding: 0 2px; font-size: 12px; }
.sp-del:hover { color: var(--danger); }
</style>
