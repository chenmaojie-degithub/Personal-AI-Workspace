<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="flex flex-col gap-4">
    <div>
      <h1 class="text-lg font-semibold">Not Found</h1>
      <p class="text-sm text-muted-foreground">The page you requested does not exist.</p>
    </div>
    <div>
      <Button type="button" variant="secondary" @click="router.push('/chat')">Go to Chat</Button>
    </div>
  </div>
</template>
