import { createRouter, createWebHistory } from 'vue-router'
import CopilotView from '@/views/CopilotView.vue'
import ExploreView from '@/views/ExploreView.vue'
import StatusView from '@/views/StatusView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'explore', component: ExploreView },
    { path: '/copilot', name: 'copilot', component: CopilotView },
    { path: '/status', name: 'status', component: StatusView },
    { path: '/preferences', redirect: '/' },
    { path: '/evidence', redirect: '/' },
  ],
})
