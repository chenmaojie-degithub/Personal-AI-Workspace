<script setup lang="ts">
import type { UiChatMessage } from '@/lib/chat'
import MessageBubble from '@/components/chat/MessageBubble.vue'

defineProps<{
  messages: UiChatMessage[]
  isLoading?: boolean
}>()
</script>

<template>
  <div class="flex flex-col gap-7 pb-8 sm:gap-9">
    <div v-for="(m, idx) in messages" :key="idx" class="scroll-mt-4"
      :data-chat-last="idx === messages.length - 1 ? 'true' : undefined">
      <MessageBubble :message="m" />
    </div>

    <div v-if="isLoading && messages[messages.length - 1]?.content === ''" class="scroll-mt-4" data-chat-last="true">
      <MessageBubble :message="{ role: 'assistant', content: '' }" typing />
    </div>
  </div>
</template>
