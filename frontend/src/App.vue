<script setup lang="ts">
import { onMounted } from 'vue'
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
import { RouterLink, useRoute } from 'vue-router'
import { MessageSquare, FileText, Settings, House } from 'lucide-vue-next'
import WorkspaceSelector from '@/components/workspace/WorkspaceSelector.vue'
import ProjectTree from '@/components/projects/ProjectTree.vue'
import { cn } from '@/lib/utils'
import { useChat } from '@/lib/chat'

const route = useRoute()
const chat = useChat()
onMounted(() => { void chat.loadSessions(); void chat.loadModels() })

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
        <SidebarGroup class="min-h-0 group-data-[collapsible=icon]:hidden">
          <SidebarGroupContent><ProjectTree /></SidebarGroupContent>
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
