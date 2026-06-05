<script setup>
import { computed, ref, watch, onUnmounted } from 'vue'
import { renderMarkdown } from '../../utils/markdown.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  text: { type: String, default: '' },
  error: { type: String, default: '' },
  title: { type: String, default: 'AI 智能分析' },
  subtitle: { type: String, default: '' },
  // 加载文案与耗时预期：慢分析（驾驶舱推理模型）用来安抚等待，避免误以为卡死。
  loadingHint: { type: String, default: 'DeepSeek 正在分析财务数据…' },
  estimateSeconds: { type: Number, default: 0 },
  // 流式：推理过程（reasoner 模型先吐的思考链），实时填充。
  reasoning: { type: String, default: '' },
})

const emit = defineEmits(['close', 'reanalyze'])

const showReasoning = ref(true)
// 出现正文后，自动折叠推理过程，聚焦结论（用户仍可手动展开）。
watch(() => props.text, (t, old) => {
  if (t && !old) showReasoning.value = false
})
// 是否已经开始流式输出（推理或正文任一有内容）。
const streaming = computed(() => props.loading && (!!props.reasoning || !!props.text))

// ── 已用时计时器：loading 期间每秒自增，给等待者明确的进度感 ──
const elapsed = ref(0)
let timer = null
watch(() => props.loading, (on) => {
  clearInterval(timer)
  if (on) {
    elapsed.value = 0
    timer = setInterval(() => { elapsed.value += 1 }, 1000)
  }
}, { immediate: true })
onUnmounted(() => clearInterval(timer))

// 超过预期耗时后给一句额外安抚，避免焦虑。
const overEstimate = computed(() =>
  props.estimateSeconds > 0 && elapsed.value >= props.estimateSeconds)

const renderedHtml = computed(() => renderMarkdown(props.text))
</script>

<template>
  <Transition name="ai-fade">
    <div v-if="visible" class="ai-mask" @click.self="emit('close')">
      <div class="ai-modal">
        <!-- Animated tech border glow -->
        <div class="ai-glow"></div>

        <div class="ai-head">
          <div class="ai-title-wrap">
            <span class="ai-orb">✨</span>
            <div>
              <div class="ai-title">{{ title }}</div>
              <div v-if="subtitle" class="ai-sub">{{ subtitle }}</div>
            </div>
          </div>
          <button class="ai-x" @click="emit('close')">×</button>
        </div>

        <div class="ai-body">
          <!-- 初始等待：尚未开始流式输出 -->
          <div v-if="loading && !streaming && !error" class="ai-loading">
            <div class="ai-scanner">
              <div class="ai-scan-line"></div>
            </div>
            <div class="ai-loading-text">{{ loadingHint }}</div>
            <div class="ai-timer">
              已用时 <b>{{ elapsed }}</b> 秒<template v-if="estimateSeconds"> · 预计约 {{ estimateSeconds }} 秒</template>
            </div>
            <div v-if="overEstimate" class="ai-timer-note">模型仍在深度推理，请再稍候，马上就好…</div>
            <div class="ai-dots"><span></span><span></span><span></span></div>
          </div>

          <template v-else>
            <!-- 推理过程（reasoner 思考链，可折叠） -->
            <div v-if="reasoning" class="ai-reasoning">
              <button class="ai-reasoning-head" @click="showReasoning = !showReasoning">
                <span class="ai-reasoning-dot" :class="{ live: streaming && !text }"></span>
                <span>AI 推理过程{{ streaming && !text ? '（进行中…）' : '' }}</span>
                <span class="ai-reasoning-toggle">{{ showReasoning ? '收起 ▲' : '展开 ▼' }}</span>
              </button>
              <div v-show="showReasoning" class="ai-reasoning-body">{{ reasoning }}</div>
            </div>

            <!-- 正文（流式逐字渲染，Markdown 美化） -->
            <div v-if="text" class="ai-content">
              <div class="ai-md" v-html="renderedHtml"></div>
              <span v-if="streaming" class="ai-caret"></span>
            </div>

            <!-- 流式状态行 -->
            <div v-if="streaming" class="ai-stream-status">
              ⚡ 正在生成…已用时 {{ elapsed }} 秒
            </div>

            <!-- 错误（可能带部分已生成内容） -->
            <div v-if="error" class="ai-err" :class="{ 'ai-err-inline': reasoning || text }">
              <div style="font-size:22px;margin-bottom:6px">⚠️</div>{{ error }}
            </div>
          </template>
        </div>

        <div class="ai-foot">
          <button class="btn btn-ghost btn-sm" :disabled="loading" @click="emit('reanalyze')">
            <span>↻</span> 重新分析
          </button>
          <button class="btn btn-primary btn-sm" @click="emit('close')">确认</button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.ai-mask {
  position: fixed; inset: 0; z-index: 1000;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
  background: rgba(30, 18, 10, 0.45);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.ai-modal {
  position: relative;
  width: min(580px, 96vw);
  max-height: 86vh;
  display: flex; flex-direction: column;
  border-radius: 20px;
  background: linear-gradient(165deg, rgba(255,252,248,0.97), rgba(252,244,236,0.97));
  box-shadow: 0 30px 90px rgba(80, 40, 20, 0.32);
  overflow: hidden;
}

/* Rotating gradient glow ring behind modal edge */
.ai-glow {
  position: absolute; inset: -2px;
  border-radius: 22px;
  padding: 2px;
  background: linear-gradient(120deg, #c96342, #e8a05a, #7a9fd4, #c96342);
  background-size: 300% 300%;
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  animation: aiGlowShift 6s ease infinite;
  pointer-events: none;
}
@keyframes aiGlowShift {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

.ai-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px 14px;
  border-bottom: 1px solid rgba(201,99,66,0.12);
}
.ai-title-wrap { display: flex; align-items: center; gap: 12px; }
.ai-orb {
  font-size: 22px;
  filter: drop-shadow(0 0 6px rgba(201,99,66,0.5));
  animation: aiOrb 3s ease-in-out infinite;
}
@keyframes aiOrb {
  0%, 100% { transform: scale(1) rotate(0deg); }
  50% { transform: scale(1.15) rotate(8deg); }
}
.ai-title { font-size: 16px; font-weight: 800; color: var(--text); letter-spacing: 0.02em; }
.ai-sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
.ai-x {
  background: none; border: none; font-size: 24px; line-height: 1;
  color: var(--muted); cursor: pointer; padding: 0 4px;
}

.ai-body {
  flex: 1; overflow-y: auto;
  padding: 18px 22px;
  min-height: 160px;
}

/* Loading scanner */
.ai-loading {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 16px; padding: 40px 0;
}
.ai-scanner {
  width: 120px; height: 64px; border-radius: 12px;
  background: linear-gradient(180deg, rgba(201,99,66,0.06), rgba(122,159,212,0.06));
  border: 1px solid rgba(201,99,66,0.15);
  position: relative; overflow: hidden;
}
.ai-scan-line {
  position: absolute; left: 0; right: 0; height: 30%;
  background: linear-gradient(180deg, transparent, rgba(201,99,66,0.35), transparent);
  animation: aiScan 1.4s ease-in-out infinite;
}
@keyframes aiScan {
  0% { top: -30%; }
  100% { top: 100%; }
}
.ai-loading-text { font-size: 13px; color: var(--muted); text-align: center; max-width: 320px; line-height: 1.6; }
.ai-timer { font-size: 12px; color: var(--muted); }
.ai-timer b { color: var(--primary); font-variant-numeric: tabular-nums; font-size: 14px; }
.ai-timer-note { font-size: 12px; color: var(--primary); opacity: .85; animation: aiFadeIn .4s ease; }
@keyframes aiFadeIn { from { opacity: 0; } to { opacity: .85; } }
.ai-dots { display: flex; gap: 6px; }
.ai-dots span {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--primary); opacity: 0.4;
  animation: aiDot 1.2s ease-in-out infinite;
}
.ai-dots span:nth-child(2) { animation-delay: 0.2s; }
.ai-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes aiDot {
  0%, 100% { opacity: 0.3; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-4px); }
}

.ai-err { text-align: center; color: #c62828; font-size: 13px; padding: 30px 10px; }
.ai-err-inline { padding: 14px 10px 4px; text-align: left; opacity: .9; }

.ai-content { font-size: 13.5px; line-height: 1.85; color: var(--text); }
.ai-content :deep(p) { margin: 0 0 10px; }
.ai-content :deep(p:last-child) { margin-bottom: 0; }
.ai-content :deep(strong) { color: var(--primary); font-weight: 700; }
/* Markdown 美化 */
.ai-content :deep(.md-h) { font-weight: 800; color: var(--text); line-height: 1.4; margin: 16px 0 8px; }
.ai-content :deep(.md-h:first-child) { margin-top: 0; }
.ai-content :deep(.md-h1) { font-size: 16.5px; }
.ai-content :deep(.md-h2) {
  font-size: 15px; color: var(--primary);
  padding-left: 9px; border-left: 3px solid var(--primary);
}
.ai-content :deep(.md-h3) { font-size: 14px; color: #8a4b34; }
.ai-content :deep(.md-h4) { font-size: 13.5px; color: var(--muted); }
.ai-content :deep(.md-list) { margin: 6px 0 12px; padding-left: 22px; }
.ai-content :deep(.md-list li) { margin: 4px 0; }
.ai-content :deep(ul.md-list li::marker) { color: var(--primary); }
.ai-content :deep(ol.md-list li::marker) { color: var(--primary); font-weight: 700; }
.ai-content :deep(code) {
  background: rgba(201,99,66,0.1); color: #a8442a;
  padding: 1px 5px; border-radius: 4px; font-size: 12.5px;
  font-family: ui-monospace, Menlo, Consolas, monospace;
}
.ai-content :deep(hr) { border: none; border-top: 1px solid rgba(201,99,66,0.18); margin: 14px 0; }

/* ── streaming reasoning (collapsible) ───────────────────────────────────── */
.ai-reasoning {
  margin-bottom: 12px; border: 1px solid rgba(122,159,212,0.22);
  border-radius: 12px; background: rgba(122,159,212,0.05); overflow: hidden;
}
.ai-reasoning-head {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; background: none; border: none; cursor: pointer;
  font-size: 12px; font-weight: 700; color: #5a6f8c; text-align: left;
}
.ai-reasoning-toggle { margin-left: auto; font-weight: 500; opacity: .8; }
.ai-reasoning-dot {
  width: 8px; height: 8px; border-radius: 50%; background: #7a9fd4; flex: none;
}
.ai-reasoning-dot.live { animation: aiPulse 1.1s ease-in-out infinite; }
@keyframes aiPulse {
  0%, 100% { opacity: .35; transform: scale(.85); }
  50% { opacity: 1; transform: scale(1.15); }
}
.ai-reasoning-body {
  padding: 4px 12px 12px; font-size: 12px; line-height: 1.7; color: #6b7a8c;
  white-space: pre-wrap; max-height: 200px; overflow-y: auto;
}

/* streaming caret + status */
.ai-caret {
  display: inline-block; width: 7px; height: 15px; vertical-align: text-bottom;
  background: var(--primary); margin-left: 2px; border-radius: 1px;
  animation: aiBlink 1s step-end infinite;
}
@keyframes aiBlink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
.ai-stream-status {
  margin-top: 10px; font-size: 12px; color: var(--primary); font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.ai-foot {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 14px 22px;
  border-top: 1px solid rgba(201,99,66,0.12);
}

/* transition */
.ai-fade-enter-active, .ai-fade-leave-active { transition: opacity 0.22s ease; }
.ai-fade-enter-from, .ai-fade-leave-to { opacity: 0; }
.ai-fade-enter-active .ai-modal { transition: transform 0.26s cubic-bezier(0.2,0.8,0.3,1); }
.ai-fade-enter-from .ai-modal { transform: scale(0.92) translateY(12px); }
</style>
