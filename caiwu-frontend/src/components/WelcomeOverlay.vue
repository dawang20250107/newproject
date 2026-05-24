<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { JOB_LABELS, hourCST } from '../constants.js'

const props = defineProps({ user: { type: Object, default: null } })
const emit = defineEmits(['done'])

const visible = ref(true)
const progress = ref(0)
const canvasEl = ref(null)
let animId = null

const hour = hourCST()
const greeting = hour < 6 ? '夜深了' : hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'
const greetIcon = hour < 6 ? '🌙' : hour < 12 ? '🌅' : hour < 18 ? '☀️' : '🌆'

const today = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
})

const mottos = [
  '数据是决策的基石，洞察是管理的利器。',
  '每一张报表，都是对经营的深度理解。',
  '精准财务分析，驱动智慧决策。',
  '数字背后，是企业经营的真实脉动。',
]
const motto = mottos[new Date().getDay() % mottos.length]

function dismiss() {
  visible.value = false
  setTimeout(() => emit('done'), 400)
}

// ── canvas particle emitter ───────────────────────────────────────────────────
function launchParticles(canvas) {
  const dpr = window.devicePixelRatio || 1
  const w = canvas.offsetWidth
  const h = canvas.offsetHeight
  canvas.width  = w * dpr
  canvas.height = h * dpr
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)

  // burst origin ≈ center of the welcome card (card is vertically centered)
  const ox = w / 2
  const oy = h * 0.42

  const COLORS = [
    '#c96342', '#e8855a', '#e8a84a', '#d4946a',
    '#f0b07a', '#c96342cc', '#e8855acc', '#ffd699',
  ]

  const particles = Array.from({ length: 90 }, () => {
    const angle = Math.random() * Math.PI * 2
    const speed = Math.random() * 7 + 2
    const isCircle = Math.random() > 0.55
    return {
      x: ox, y: oy,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed - (Math.random() * 5 + 3), // upward bias
      r: Math.random() * 5 + 2.5,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      alpha: 1,
      decay: Math.random() * 0.013 + 0.008,
      rot: Math.random() * Math.PI * 2,
      rotSpd: (Math.random() - 0.5) * 0.22,
      isCircle,
    }
  })

  function frame() {
    ctx.clearRect(0, 0, w, h)
    let any = false
    for (const p of particles) {
      if (p.alpha <= 0) continue
      any = true
      p.x  += p.vx
      p.y  += p.vy
      p.vy += 0.18          // gravity
      p.vx *= 0.985         // air drag
      p.alpha -= p.decay
      p.rot += p.rotSpd
      ctx.save()
      ctx.globalAlpha = Math.max(0, p.alpha)
      ctx.fillStyle = p.color
      ctx.translate(p.x, p.y)
      ctx.rotate(p.rot)
      if (p.isCircle) {
        ctx.beginPath()
        ctx.arc(0, 0, p.r, 0, Math.PI * 2)
        ctx.fill()
      } else {
        ctx.fillRect(-p.r * 0.5, -p.r, p.r, p.r * 2.2)
      }
      ctx.restore()
    }
    if (any) animId = requestAnimationFrame(frame)
  }

  animId = requestAnimationFrame(frame)
}

onMounted(() => {
  // progress bar
  const duration = 4000
  const interval = 40
  const steps = duration / interval
  let step = 0
  const timer = setInterval(() => {
    step++
    progress.value = Math.min(100, (step / steps) * 100)
    if (step >= steps) { clearInterval(timer); dismiss() }
  }, interval)

  // fire particle emitter after card animation settles (≈ 300 ms)
  setTimeout(() => {
    if (canvasEl.value) launchParticles(canvasEl.value)
  }, 320)
})

onUnmounted(() => {
  if (animId) cancelAnimationFrame(animId)
})
</script>

<template>
  <Transition name="welcome-fade">
    <div v-if="visible" class="welcome-overlay" @click="dismiss">
      <!-- full-screen canvas particle emitter -->
      <canvas ref="canvasEl" class="particle-canvas" aria-hidden="true"></canvas>

      <div class="welcome-card" @click.stop>
        <div class="particle p1"></div><div class="particle p2"></div>
        <div class="particle p3"></div><div class="particle p4"></div>
        <div class="wc-confetti"><i v-for="n in 18" :key="n" :style="`--i:${n}`"></i></div>

        <div class="welcome-icon">{{ greetIcon }}</div>
        <div class="welcome-greeting">{{ greeting }}</div>
        <div class="welcome-name">{{ user?.name || '欢迎' }}</div>

        <div class="welcome-role">
          <span v-if="user?.role === 'super_admin'" class="role-badge">超级管理员</span>
          <span v-else-if="user?.job_title && JOB_LABELS[user.job_title]" class="job-badge">
            {{ JOB_LABELS[user.job_title] }}
          </span>
        </div>

        <div class="welcome-date">{{ today }}</div>
        <div class="welcome-motto">{{ motto }}</div>

        <div class="progress-bar">
          <div class="progress-fill" :style="`width:${progress}%`"></div>
        </div>
        <div class="welcome-hint">点击任意处进入系统</div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.welcome-overlay {
  position: fixed; inset: 0; z-index: 1000;
  display: flex; align-items: center; justify-content: center;
  background: rgba(20,10,5,.55); backdrop-filter: blur(12px);
}

/* canvas covers the whole overlay, particles fly freely over it */
.particle-canvas {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  pointer-events: none;
  z-index: 1;
}

.welcome-card {
  position: relative; z-index: 2;
  width: 420px; max-width: 92vw;
  background: rgba(255,252,248,.78); backdrop-filter: blur(32px) saturate(200%);
  border: 1px solid rgba(255,255,255,.65); border-radius: 28px;
  padding: 48px 40px 36px; text-align: center;
  box-shadow: 0 32px 80px rgba(100,60,30,.28), 0 1px 0 rgba(255,255,255,.9) inset;
  animation: cardIn .55s cubic-bezier(.34,1.6,.64,1) both; overflow: hidden;
}

.particle { position: absolute; border-radius: 50%; opacity: .18; pointer-events: none; }
.p1 { width:120px; height:120px; background:radial-gradient(circle,#c96342,transparent); top:-30px; left:-30px; animation:pfloat 6s ease-in-out infinite; }
.p2 { width:80px; height:80px; background:radial-gradient(circle,#e8a84a,transparent); bottom:-20px; right:-20px; animation:pfloat 8s ease-in-out infinite reverse; }
.p3 { width:60px; height:60px; background:radial-gradient(circle,#c96342,transparent); bottom:60px; left:20px; animation:pfloat 7s ease-in-out infinite; opacity:.12; }
.p4 { width:50px; height:50px; background:radial-gradient(circle,#d4946a,transparent); top:60px; right:20px; animation:pfloat 5s ease-in-out infinite reverse; opacity:.14; }
@keyframes pfloat { 0%,100% { transform:translate(0,0) scale(1); } 50% { transform:translate(10px,-15px) scale(1.1); } }

.wc-confetti { position:absolute; top:0; left:0; right:0; height:0; pointer-events:none; }
.wc-confetti i {
  position:absolute; top:40px; left:50%; width:9px; height:15px; border-radius:2px;
  background:hsl(calc(var(--i)*40),85%,62%); opacity:0;
  animation:wcConfetti 1.8s calc(var(--i)*.05s) cubic-bezier(.2,.7,.3,1) both;
}
@keyframes wcConfetti {
  0% { opacity:0; transform:translate(0,0) rotate(0deg) scale(.5); } 12% { opacity:1; }
  100% { opacity:0; transform:translate(calc((var(--i)-9)*24px),calc(180px+var(--i)*5px)) rotate(calc(var(--i)*110deg)) scale(1); }
}

.welcome-icon { font-size:62px; margin-bottom:16px; animation:spinIn .6s cubic-bezier(.34,1.56,.64,1) .1s both, iconFloat 3s ease-in-out .8s infinite; display:block; filter:drop-shadow(0 6px 16px rgba(201,99,66,.35)); }
@keyframes iconFloat { 0%,100% { transform:translateY(0); } 50% { transform:translateY(-7px); } }
.welcome-greeting { font-size:16px; color:#9b8070; font-weight:500; margin-bottom:4px; letter-spacing:.06em; animation:slideUp .45s .2s both; }
.welcome-name { font-size:36px; font-weight:800; background:linear-gradient(135deg,#c96342,#1a1208 60%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; margin-bottom:16px; animation:slideUp .45s .25s both; }
.welcome-role { display:flex; gap:8px; justify-content:center; margin-bottom:20px; animation:slideUp .45s .3s both; }
.role-badge,.job-badge { display:inline-block; padding:4px 14px; border-radius:20px; font-size:12px; font-weight:600; }
.role-badge { background:rgba(201,99,66,.12); color:#c96342; }
.job-badge  { background:rgba(21,101,192,.1); color:#1565c0; }
.welcome-date { font-size:13px; color:#9b8070; margin-bottom:10px; animation:slideUp .45s .35s both; }
.welcome-motto { font-size:13px; color:#b09080; font-style:italic; margin-bottom:28px; animation:slideUp .45s .4s both; }
.progress-bar { width:100%; height:3px; background:rgba(180,140,110,.18); border-radius:2px; overflow:hidden; margin-bottom:12px; }
.progress-fill { height:100%; background:linear-gradient(90deg,#c96342,#e8855a); border-radius:2px; transition:width .04s linear; box-shadow:0 0 8px rgba(201,99,66,.4); }
.welcome-hint { font-size:11px; color:rgba(155,128,112,.6); letter-spacing:.04em; }
.welcome-fade-enter-active { animation:fadeIn .25s ease; }
.welcome-fade-leave-active { animation:fadeOut .35s ease forwards; }
@keyframes fadeIn  { from{opacity:0} to{opacity:1} }
@keyframes fadeOut { from{opacity:1} to{opacity:0} }
@keyframes cardIn { from{opacity:0;transform:scale(.88) translateY(24px)} to{opacity:1;transform:scale(1) translateY(0)} }
@keyframes slideUp { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }
@keyframes spinIn  { from{transform:rotate(-180deg) scale(.3);opacity:0} to{transform:rotate(0) scale(1);opacity:1} }
</style>
