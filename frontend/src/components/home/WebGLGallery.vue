<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  DoubleSide, Group, MathUtils, Mesh, MeshBasicMaterial, PerspectiveCamera,
  PlaneGeometry, Raycaster, Scene, SRGBColorSpace, TextureLoader, Vector2,
  Vector3, WebGLRenderer,
} from 'three'
import galleryItems from '@/data/gallery.json'

export type GalleryItem = (typeof galleryItems)[number]

defineProps<{ exiting?: boolean }>()
const emit = defineEmits<{ select: [item: GalleryItem] }>()
const mount = ref<HTMLElement | null>(null)
const fallback = ref(false)
const loaded = ref(0)
const hoveredTitle = ref('')
const mobile = typeof window !== 'undefined' && window.innerWidth < 700
const items: GalleryItem[] = mobile
  ? Array.from({ length: Math.min(8, galleryItems.length) }, (_, i) => galleryItems[Math.round(i * (galleryItems.length - 1) / Math.max(1, Math.min(8, galleryItems.length) - 1))]).filter((item): item is GalleryItem => item !== undefined)
  : galleryItems

type Card = { mesh: Mesh<PlaneGeometry, MeshBasicMaterial>; item: GalleryItem; ready: boolean; fade: number }
const cards: Card[] = []
const pointer = new Vector2(9, 9)
const raycaster = new Raycaster()
const worldPosition = new Vector3()
let renderer: WebGLRenderer | null = null
let camera: PerspectiveCamera | null = null
let sphere: Group | null = null
let resizeObserver: ResizeObserver | null = null
let frame = 0
let disposed = false
let reducedMotion = false
let hovered: Card | null = null
let targetX = 0
let targetY = 0
let targetRotationX = -0.12
let targetRotationY = 0.5
let targetZoom = mobile ? 8.2 : 7.6
let lastInteraction = 0
let previousFrame = 0

function onPointerMove(event: PointerEvent) {
  if (!mount.value) return
  const bounds = mount.value.getBoundingClientRect()
  pointer.set(((event.clientX - bounds.left) / bounds.width) * 2 - 1, -((event.clientY - bounds.top) / bounds.height) * 2 + 1)
  targetX = reducedMotion ? 0 : pointer.x * 0.28
  targetY = reducedMotion ? 0 : pointer.y * 0.18
  lastInteraction = performance.now()
}

function onPointerLeave() {
  pointer.set(9, 9)
  targetX = 0
  targetY = 0
  hovered = null
  hoveredTitle.value = ''
}

function onWheel(event: WheelEvent) {
  event.preventDefault()
  const delta = MathUtils.clamp(event.deltaY, -120, 120)
  targetRotationY += delta * 0.004
  targetRotationX = MathUtils.clamp(targetRotationX + delta * 0.001, -0.48, 0.48)
  targetZoom = MathUtils.clamp(targetZoom + delta * 0.002, mobile ? 7.6 : 6.5, mobile ? 9.2 : 8.8)
  lastInteraction = performance.now()
}

function onPointerDown(event: PointerEvent) {
  if (!sphere || !camera) return
  onPointerMove(event)
  raycaster.setFromCamera(pointer, camera)
  const hit = raycaster.intersectObjects(cards.map((card) => card.mesh))
    .find(({ object }) => cards.some((card) => card.mesh === object && card.ready))
  const selectedCard = cards.find((card) => card.mesh === hit?.object)
  if (!selectedCard) return
  const position = selectedCard.mesh.position
  const desired = -Math.atan2(position.x, position.z)
  const shortestTurn = Math.atan2(Math.sin(desired - targetRotationY), Math.cos(desired - targetRotationY))
  targetRotationY += shortestTurn
  targetRotationX = MathUtils.clamp(-position.y * 0.12, -0.48, 0.48)
  targetZoom = mobile ? 7.6 : 6.7
  lastInteraction = performance.now()
  emit('select', selectedCard.item)
}

function resize() {
  if (!mount.value || !renderer || !camera) return
  const width = Math.max(1, mount.value.clientWidth)
  const height = Math.max(1, mount.value.clientHeight)
  camera.aspect = width / height
  camera.updateProjectionMatrix()
  renderer.setSize(width, height, false)
}

onMounted(() => {
  const host = mount.value
  if (!host) return
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  try {
    const probe = document.createElement('canvas')
    if (!probe.getContext('webgl2') && !probe.getContext('webgl')) throw new Error('WebGL unavailable')
    renderer = new WebGLRenderer({ alpha: true, antialias: !mobile, powerPreference: 'high-performance' })
  } catch {
    fallback.value = true
    return
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, mobile ? 1.5 : 2))
  renderer.outputColorSpace = SRGBColorSpace
  renderer.setClearColor(0x08090b, 0)
  renderer.domElement.setAttribute('aria-label', 'Interactive three-dimensional gallery')
  host.appendChild(renderer.domElement)

  const scene = new Scene()
  sphere = new Group()
  sphere.rotation.set(targetRotationX, targetRotationY, 0)
  scene.add(sphere)
  camera = new PerspectiveCamera(mobile ? 46 : 42, 1, 0.1, 100)
  camera.position.z = targetZoom
  const loader = new TextureLoader()
  const goldenAngle = Math.PI * (3 - Math.sqrt(5))
  const radius = 2.45

  items.forEach((item, index) => {
    const y = 1 - (index / Math.max(1, items.length - 1)) * 2
    const ring = Math.sqrt(Math.max(0, 1 - y * y))
    const theta = goldenAngle * index
    const width = mobile ? 1.85 : 1.68
    const geometry = new PlaneGeometry(width, width * item.height / item.width)
    const material = new MeshBasicMaterial({ color: 0xd5d9e5, side: DoubleSide, transparent: true, opacity: 0, depthWrite: false })
    const mesh = new Mesh(geometry, material)
    mesh.position.set(Math.cos(theta) * ring * radius, y * radius, Math.sin(theta) * ring * radius)
    sphere?.add(mesh)
    const card: Card = { mesh, item, ready: false, fade: 0 }
    cards.push(card)
    const texture = loader.load(item.image, () => {
      if (disposed) { texture.dispose(); return }
      texture.colorSpace = SRGBColorSpace
      texture.anisotropy = 2
      material.map = texture
      material.needsUpdate = true
      card.ready = true
      loaded.value++
    }, undefined, () => { if (!disposed) loaded.value++ })
  })

  const animate = (now: number) => {
    if (!renderer || !camera || !sphere) return
    const elapsed = Math.min(now - (previousFrame || now), 50)
    previousFrame = now
    if (!reducedMotion && now - lastInteraction > 1800) targetRotationY += elapsed * 0.000035
    sphere.rotation.x = MathUtils.lerp(sphere.rotation.x, targetRotationX, reducedMotion ? 0.12 : 0.045)
    sphere.rotation.y = MathUtils.lerp(sphere.rotation.y, targetRotationY, reducedMotion ? 0.12 : 0.045)
    camera.position.x = MathUtils.lerp(camera.position.x, targetX, 0.045)
    camera.position.y = MathUtils.lerp(camera.position.y, targetY, 0.045)
    camera.position.z = MathUtils.lerp(camera.position.z, targetZoom, 0.045)
    camera.lookAt(0, 0, 0)
    sphere.updateMatrixWorld(true)

    raycaster.setFromCamera(pointer, camera)
    const intersections = raycaster.intersectObjects(cards.map((card) => card.mesh))
    const hit = intersections.find(({ object }) => cards.some((card) => card.mesh === object && card.ready))
    hovered = cards.find((card) => card.mesh === hit?.object) ?? null
    const nextTitle = hovered?.item.title ?? ''
    if (hoveredTitle.value !== nextTitle) hoveredTitle.value = nextTitle
    renderer.domElement.style.cursor = hovered ? 'pointer' : 'grab'

    cards.forEach((card) => {
      card.mesh.quaternion.copy(sphere!.quaternion).invert().multiply(camera!.quaternion)
      card.mesh.getWorldPosition(worldPosition)
      const depth = MathUtils.clamp((worldPosition.z + radius) / (2 * radius), 0, 1)
      card.fade = Math.min(1, card.fade + (card.ready ? elapsed * 0.003 : 0))
      const emphasis = hovered && hovered !== card ? 0.52 : 1
      card.mesh.material.opacity = card.fade * (0.26 + 0.72 * depth) * emphasis
      card.mesh.material.color.setScalar(0.7 + 0.3 * depth)
      const scale = 0.92 + depth * 0.11 + (hovered === card ? 0.08 : 0)
      card.mesh.scale.setScalar(MathUtils.lerp(card.mesh.scale.x, scale, 0.12))
    })
    renderer.render(scene, camera)
    frame = requestAnimationFrame(animate)
  }

  host.addEventListener('pointermove', onPointerMove)
  host.addEventListener('pointerleave', onPointerLeave)
  host.addEventListener('pointerdown', onPointerDown)
  host.addEventListener('wheel', onWheel, { passive: false })
  resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(host)
  resize()
  frame = requestAnimationFrame(animate)
})

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(frame)
  resizeObserver?.disconnect()
  const host = mount.value
  host?.removeEventListener('pointermove', onPointerMove)
  host?.removeEventListener('pointerleave', onPointerLeave)
  host?.removeEventListener('pointerdown', onPointerDown)
  host?.removeEventListener('wheel', onWheel)
  cards.forEach(({ mesh }) => {
    mesh.geometry.dispose()
    mesh.material.map?.dispose()
    mesh.material.dispose()
  })
  renderer?.dispose()
  renderer?.domElement.remove()
})
</script>

<template>
  <div class="gallery-root" :class="{ 'gallery-exiting': exiting }">
    <div ref="mount" class="gallery-stage" />
    <div v-if="fallback" class="gallery-fallback" aria-label="Image gallery">
      <img v-for="item in items" :key="item.id" :src="item.image" :alt="item.title" loading="lazy"
        @click="emit('select', item)" />
    </div>
    <p v-else-if="loaded < items.length" class="gallery-loading">Loading gallery · {{ loaded }}/{{ items.length }}</p>
    <p v-if="hoveredTitle && !fallback" class="gallery-hover">{{ hoveredTitle }}</p>
    <div class="gallery-hint" aria-hidden="true">SCROLL TO ORBIT <span>↗</span> DRAG YOUR GAZE</div>
  </div>
</template>

<style scoped>
.gallery-root { position: relative; width: 100%; height: 100%; min-height: 430px; transition: opacity .75s ease, filter .75s ease, transform .75s ease; }
.gallery-exiting { opacity: 0; filter: blur(14px); transform: scale(1.17); }
.gallery-stage { position: absolute; inset: 0; touch-action: pan-y; }
.gallery-stage :deep(canvas) { display: block; width: 100%; height: 100%; }
.gallery-loading, .gallery-hover, .gallery-hint { position: absolute; z-index: 2; color: #c6c9d2; pointer-events: none; }
.gallery-loading { top: 49%; left: 50%; transform: translate(-50%, -50%); font-size: 11px; letter-spacing: .2em; text-transform: uppercase; }
.gallery-hover { left: 50%; bottom: 13%; transform: translateX(-50%); max-width: 80%; padding: 9px 16px; border: 1px solid #ffffff26; border-radius: 999px; background: #101317c9; backdrop-filter: blur(14px); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gallery-hint { bottom: 4%; right: 7%; font-size: 10px; letter-spacing: .19em; color: #858b99; }
.gallery-hint span { padding: 0 8px; color: #d5d9e5; }
.gallery-fallback { position: absolute; inset: 7%; display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; align-content: center; overflow: hidden; }
.gallery-fallback img { width: 100%; aspect-ratio: 1.75; object-fit: cover; border: 1px solid #ffffff20; border-radius: 12px; cursor: pointer; opacity: .82; }
@media (max-width: 700px) { .gallery-root { min-height: 340px; } .gallery-hint { display: none; } .gallery-fallback { grid-template-columns: repeat(2, 1fr); } }
</style>
