<template>
  <canvas ref="canvas" class="click-canvas" :class="{ active: enabled }"></canvas>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const canvas = ref(null)
const enabled = ref(false)
let ctx = null
let particles = []
let animId = null
let isMobile = false

function onMouseMove(e) {
  if (isMobile) return
  addParticle(e.clientX, e.clientY, 'move')
}

function onMouseClick(e) {
  if (isMobile) return
  for (let i = 0; i < 6; i++) {
    addParticle(e.clientX, e.clientY, 'click')
  }
}

function addParticle(x, y, type) {
  const count = type === 'click' ? 12 : 1
  for (let i = 0; i < count; i++) {
    const angle = type === 'click' ? (Math.PI * 2 * i) / count + Math.random() * 0.5 : Math.random() * Math.PI * 2
    const speed = type === 'click' ? 2 + Math.random() * 3 : 0.5 + Math.random() * 0.5
    particles.push({
      x, y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      alpha: 1,
      size: type === 'click' ? 3 + Math.random() * 3 : 1.5 + Math.random() * 1,
      color: type === 'click'
        ? `hsla(${210 + Math.random() * 20}, 95%, ${55 + Math.random() * 15}%, `
        : `hsla(210, 90%, 65%, `,
      life: type === 'click' ? 1 : 0.4,
      decay: type === 'click' ? 0.03 + Math.random() * 0.02 : 0.05 + Math.random() * 0.03
    })
  }
  if (!animId) animate()
}

function animate() {
  if (!canvas.value) return
  ctx.clearRect(0, 0, canvas.value.width, canvas.value.height)

  particles = particles.filter(p => {
    p.x += p.vx
    p.y += p.vy
    p.vy += 0.08 // gravity
    p.vx *= 0.97
    p.alpha -= p.decay

    if (p.alpha <= 0) return false

    ctx.beginPath()
    ctx.arc(p.x, p.y, p.size * p.alpha, 0, Math.PI * 2)
    ctx.fillStyle = p.color + p.alpha + ')'
    ctx.fill()

    return true
  })

  if (particles.length > 0) {
    animId = requestAnimationFrame(animate)
  } else {
    animId = null
  }
}

function resize() {
  if (!canvas.value) return
  canvas.value.width = window.innerWidth
  canvas.value.height = window.innerHeight
}

function init() {
  isMobile = 'ontouchstart' in window
  if (!canvas.value) return
  ctx = canvas.value.getContext('2d')
  resize()

  if (!isMobile) {
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('click', onMouseClick, true)
  }
  window.addEventListener('resize', resize)
  enabled.value = true
}

onMounted(init)
onUnmounted(() => {
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('click', onMouseClick, true)
  window.removeEventListener('resize', resize)
  if (animId) cancelAnimationFrame(animId)
})
</script>

<style scoped>
.click-canvas {
  position: fixed;
  top: 0; left: 0;
  width: 100vw; height: 100vh;
  pointer-events: none;
  z-index: 9999;
  opacity: 0;
  transition: opacity 0.4s ease;
}
.click-canvas.active { opacity: 1; }
</style>
