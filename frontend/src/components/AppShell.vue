<script setup lang="ts">
import {
  Compass,
  MessageSquareText,
  Activity,
} from '@lucide/vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
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

import { computed } from 'vue'

const route = useRoute()
const copilot = computed(() => route.path === '/copilot')
const items = [
  { title: 'Explore', to: '/', icon: Compass },
  { title: 'AI Copilot', to: '/copilot', icon: MessageSquareText },
  { title: 'System Status', to: '/status', icon: Activity },
]
</script>

<template>
  <SidebarProvider class="h-dvh overflow-hidden">
    <Sidebar collapsible="offcanvas">
      <SidebarHeader class="px-4 py-5">
        <p class="text-xs font-semibold tracking-[0.22em] text-[#6B3E0A] uppercase">Old Klang Road</p>
        <p class="font-heading text-2xl leading-tight text-sidebar-foreground">Food Copilot</p>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem v-for="item in items" :key="item.to">
                <RouterLink v-slot="{ href, navigate, isExactActive }" :to="item.to" custom>
                  <SidebarMenuButton
                    as="a"
                    :href="href"
                    :data-active="isExactActive || undefined"
                    @click="navigate"
                  >
                    <component :is="item.icon" />
                    <span>{{ item.title }}</span>
                  </SidebarMenuButton>
                </RouterLink>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter class="px-4 py-4 text-xs leading-5 text-sidebar-foreground/70">
        Stored restaurants first. Prices, addresses, and halal status stay unknown until a record says otherwise.
      </SidebarFooter>
    </Sidebar>
    <SidebarInset class="h-dvh overflow-hidden">
      <div class="flex h-full min-h-0 flex-col overflow-hidden">
        <div class="flex shrink-0 items-center gap-3 border-b border-border/80 bg-card/70 px-4 py-3 backdrop-blur-sm">
          <SidebarTrigger />
          <span class="text-sm text-muted-foreground">Restaurant discovery</span>
          <span class="ml-auto rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground">Old Klang Road</span>
        </div>
        <main
          class="min-h-0 flex-1 px-4 sm:px-8"
          :class="copilot ? 'overflow-hidden py-4' : 'overflow-y-auto py-8'"
        >
          <RouterView />
        </main>
      </div>
    </SidebarInset>
  </SidebarProvider>
</template>
