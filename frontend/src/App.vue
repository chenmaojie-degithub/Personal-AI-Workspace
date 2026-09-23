<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { MessageSquare, FileText, Settings, House, MoreHorizontal, Plus } from 'lucide-vue-next'
import WorkspaceSelector from '@/components/workspace/WorkspaceSelector.vue'
import { cn } from '@/lib/utils'
import { useChat, type StoredSession } from '@/lib/chat'

const route = useRoute()
const router = useRouter()
const chat = useChat()
const editingSessionId = ref<string | null>(null)
const titleDraft = ref('')

onMounted(() => { void chat.loadSessions(); void chat.loadModels() })

const historyGroups = computed(() => {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime()
  const lastWeek = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6).getTime()
  const groups: Array<{ label: string; items: StoredSession[] }> = [
    { label: '今天', items: [] },
    { label: '昨天', items: [] },
    { label: '7 天内', items: [] },
    { label: '更早', items: [] },
  ]
  for (const session of chat.sessions.value) {
    const updated = Date.parse(session.updated_at)
    groups[updated >= today ? 0 : updated >= yesterday ? 1 : updated >= lastWeek ? 2 : 3]!.items.push(session)
  }
  return groups.filter((group) => group.items.length)
})

function openSession(sessionId: string) {
  if (chat.isLoading.value) return
  void chat.selectSession(sessionId)
  if (route.path !== '/chat') void router.push('/chat')
}

function onNewChat() {
  if (chat.isLoading.value || chat.isRestoring.value || chat.isUploading.value) return
  chat.reset()
  if (route.path !== '/chat') void router.push('/chat')
}

async function onDeleteSession(sessionId: string) {
  if (!window.confirm('删除这个会话的聊天记录和 Token Usage？已上传文件与向量索引不会删除。')) return
  await chat.deleteSession(sessionId)
}

function startRename(session: StoredSession) {
  editingSessionId.value = session.session_id
  titleDraft.value = session.title
  void nextTick(() => {
    const input = document.querySelector<HTMLInputElement>('[data-session-title-input]')
    input?.focus()
    input?.select()
  })
}

function cancelRename() {
  editingSessionId.value = null
}

async function saveRename(sessionId: string) {
  if (editingSessionId.value !== sessionId) return
  const title = titleDraft.value.trim()
  editingSessionId.value = null
  if (!title || title.length > 100) {
    chat.sessionsError.value = '标题需要包含 1–100 个字符'
    return
  }
  await chat.renameSession(sessionId, title)
}

function linkClass(path: string) {
  const active = route.path === path
  return cn(
    'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
    active
      ? 'bg-sidebar-accent text-sidebar-accent-foreground'
      : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground',
  )
}
</script>

<template>
  <div class="dark app-frame" :class="{ 'app-shell': route.path === '/chat' }">
  <RouterView v-if="route.path === '/'" />
  <SidebarProvider v-else :class="route.path === '/chat' ? 'h-full overflow-hidden' : undefined">
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <WorkspaceSelector />
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton :as-child="true" :is-active="route.path === '/'" tooltip="Home">
                  <RouterLink :class="linkClass('/')" to="/">
                    <House class="size-4" />
                    <span>Home</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton :as-child="true" :is-active="route.path === '/chat'" tooltip="Chat">
                  <RouterLink :class="linkClass('/chat')" to="/chat">
                    <MessageSquare class="size-4" />
                    <span>Chat</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton :as-child="true" :is-active="route.path === '/files'" tooltip="Knowledge Base">
                  <RouterLink :class="linkClass('/files')" to="/files">
                    <FileText class="size-4" />
                    <span>Knowledge Base</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton :as-child="true" :is-active="route.path === '/settings'" tooltip="Settings">
                  <RouterLink :class="linkClass('/settings')" to="/settings">
                    <Settings class="size-4" />
                    <span>Settings</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup class="group-data-[collapsible=icon]:hidden">
          <div class="flex items-center justify-between pr-2">
            <SidebarGroupLabel>历史记录</SidebarGroupLabel>
            <button type="button" class="flex size-7 items-center justify-center rounded-md text-sidebar-foreground/55 transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
              aria-label="新聊天" title="新聊天" :disabled="chat.isLoading.value || chat.isRestoring.value || chat.isUploading.value" @click="onNewChat"><Plus class="size-4" /></button>
          </div>
          <SidebarGroupContent class="space-y-3 px-2">
            <div v-if="chat.isLoadingSessions.value && !chat.sessions.value.length" class="space-y-2 px-2" aria-label="正在加载历史记录">
              <div v-for="n in 3" :key="n" class="h-5 animate-pulse rounded bg-sidebar-foreground/10" />
            </div>
            <p v-else-if="chat.sessionsError.value" class="text-xs text-destructive">{{ chat.sessionsError.value }}</p>
            <p v-else-if="!historyGroups.length" class="text-xs text-sidebar-foreground/50">暂无历史聊天</p>
            <div v-for="group in historyGroups" :key="group.label">
              <div class="mb-1 px-2 text-[11px] text-sidebar-foreground/45">{{ group.label }}</div>
              <div v-for="session in group.items" :key="session.session_id"
                class="group flex min-w-0 items-center rounded-md transition-colors hover:bg-sidebar-accent/60"
                :class="chat.sessionId.value === session.session_id && route.path === '/chat' ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/75'">
                <input v-if="editingSessionId === session.session_id" v-model="titleDraft" data-session-title-input type="text" maxlength="100"
                  class="mx-1 min-w-0 flex-1 rounded-md border border-white/15 bg-[#20242b] px-1 py-1 text-[13px] text-white outline-none focus:border-white/30"
                  :aria-label="`重命名会话：${session.title}`" @click.stop @keydown.enter.prevent="saveRename(session.session_id)"
                  @keydown.esc.prevent="cancelRename" @blur="saveRename(session.session_id)" />
                <button v-else type="button" class="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-[13px]"
                  :title="session.title" :disabled="chat.isLoading.value || chat.isRestoring.value" @click="openSession(session.session_id)">
                  {{ session.title.trim() || 'New Chat' }}
                </button>
                <Popover>
                  <PopoverTrigger as-child>
                    <button type="button" class="mr-1 shrink-0 rounded p-1 opacity-0 hover:bg-white/10 group-hover:opacity-100 focus:opacity-100"
                      :aria-label="`会话操作：${session.title}`" :disabled="chat.isLoading.value || chat.isRestoring.value">
                      <MoreHorizontal class="size-4" />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent side="right" align="start" class="w-28 border-white/10 bg-[#171a20] p-1 text-white">
                    <button type="button" class="w-full rounded px-3 py-1.5 text-left text-sm hover:bg-white/10"
                      @click="startRename(session)">重命名</button>
                    <button type="button" class="w-full rounded px-3 py-1.5 text-left text-sm text-red-300 hover:bg-white/10"
                      @click="onDeleteSession(session.session_id)">删除</button>
                  </PopoverContent>
                </Popover>
              </div>
            </div>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div class="px-2 py-2 text-xs text-sidebar-foreground/60 group-data-[collapsible=icon]:hidden">
          YOUR MODELS · YOUR KNOWLEDGE · YOUR TOOLS
        </div>
      </SidebarFooter>
    </Sidebar>

    <SidebarInset :class="route.path === '/chat' ? 'min-w-0 overflow-hidden' : undefined">
      <header class="flex h-14 shrink-0 items-center gap-2 px-4">
        <SidebarTrigger />
      </header>
      <main class="flex flex-1 min-h-0 flex-col overflow-hidden">
        <RouterView />
      </main>
    </SidebarInset>
  </SidebarProvider>
  </div>
</template>

<style scoped>
.app-frame { min-height: 100svh; background: #08090b; color: #f2f3f6; }
.app-shell { height: 100svh; overflow: hidden; }
.app-frame :deep([data-sidebar="sidebar"]) { border-color: #ffffff14; }
.app-frame :deep(main) { background: radial-gradient(circle at 80% 10%, #5361820d, transparent 38%), #0b0d11; }
.app-frame :deep([data-sidebar="content"]) { scrollbar-color: #ffffff24 transparent; scrollbar-width: thin; }
</style>
