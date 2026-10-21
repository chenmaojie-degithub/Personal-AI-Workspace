<script setup lang="ts">
import { computed, ref } from 'vue'
import { Upload } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  accept?: string
  disabled?: boolean
}>(), {
  accept: '.txt,.md,.markdown,.pdf,.docx,.csv,.xlsx',
  disabled: false,
})

const emit = defineEmits<{
  files: [files: File[]]
  invalid: [message: string]
}>()

const dragDepth = ref(0)
const active = computed(() => dragDepth.value > 0 && !props.disabled)
const extensions = computed(() => new Set(props.accept.split(',').map(item => item.trim().toLowerCase())))

function hasFiles(event: DragEvent) {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

function enter(event: DragEvent) {
  if (!props.disabled && hasFiles(event)) dragDepth.value += 1
}

function leave(event: DragEvent) {
  if (hasFiles(event)) dragDepth.value = Math.max(0, dragDepth.value - 1)
}

function drop(event: DragEvent) {
  dragDepth.value = 0
  if (props.disabled) return
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (!files.length) return
  const invalid = files.find(file => !extensions.value.has(`.${file.name.split('.').pop()?.toLowerCase()}`))
  if (invalid) {
    emit('invalid', `Unsupported file type: ${invalid.name}`)
    return
  }
  emit('files', files)
}
</script>

<template>
  <div class="relative" @dragenter.prevent="enter" @dragover.prevent @dragleave.prevent="leave" @drop.prevent="drop">
    <slot />
    <div v-if="active" class="pointer-events-none absolute inset-2 z-40 flex items-center justify-center rounded-2xl border-2 border-dashed border-sky-300/70 bg-sky-400/10 backdrop-blur-sm">
      <div class="flex items-center gap-2 rounded-xl bg-[#11151b]/90 px-4 py-3 text-sm text-sky-100 shadow-xl">
        <Upload class="size-4" /> Drop files to upload
      </div>
    </div>
  </div>
</template>
