<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import PageHeader from '@/components/PageHeader.vue'
import { deleteUser, preferences, savePreference } from '@/lib/api'
import { useSessionStore } from '@/stores/session'
import type { Preference } from '@/types/api'

const session = useSessionStore()
const rows = ref<Preference[]>([])
const keyName = ref('ambience')
const value = ref('')
const confirmed = ref(false)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const confirmDelete = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const payload = await preferences(session.userId)
    rows.value = payload.preferences
  } catch (caught) {
    rows.value = []
    error.value = caught instanceof Error ? caught.message : 'Preferences could not be loaded.'
  } finally {
    loading.value = false
  }
}

async function save() {
  notice.value = ''
  error.value = ''
  if (!confirmed.value) {
    error.value = 'Tick the confirmation before saving. A one-off request is not stored.'
    return
  }
  try {
    const saved = await savePreference(session.userId, keyName.value.trim(), value.value.trim(), true)
    if (!saved.confirmed) {
      error.value = 'The API did not confirm this preference.'
      return
    }
    notice.value = `Saved ${saved.key}. This is a preference, not a restaurant fact.`
    confirmed.value = false
    value.value = ''
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'The preference was not saved.'
  }
}

async function removeMemory() {
  error.value = ''
  notice.value = ''
  try {
    const result = await deleteUser(session.userId)
    rows.value = []
    notice.value = `Deleted memory for this browser id. Sessions removed: ${result.deleted_sessions.length}.`
    confirmDelete.value = false
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Memory was not deleted.'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="My Preferences"
      title="Only confirmed preferences are kept."
      description="This browser id is stored locally so the demo can read and delete its own memory. It is not an account, and it does not prove that a restaurant matches the preference."
    />
    <p class="mb-6 font-mono text-xs text-muted-foreground">Browser user {{ session.userId }}</p>
    <ErrorState v-if="error" class="mb-4" :message="error" />
    <p v-if="notice" class="mb-4 text-sm text-primary">{{ notice }}</p>
    <EmptyState v-if="!loading && rows.length === 0" title="No saved preferences" description="Nothing is stored until you confirm a preference and the API accepts it." />
    <ul v-else class="space-y-2">
      <li v-for="row in rows" :key="row.key" class="rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <span class="font-medium">{{ row.key }}</span>
        <span class="mx-2 text-muted-foreground">{{ row.value }}</span>
        <span>{{ row.confirmed ? 'Confirmed' : 'Not confirmed' }}</span>
      </li>
    </ul>
    <form class="mt-8 grid max-w-xl gap-3" @submit.prevent="save">
      <div>
        <Label for="pref-key">Preference</Label>
        <Input id="pref-key" v-model="keyName" class="mt-2" />
      </div>
      <div>
        <Label for="pref-value">Value</Label>
        <Input id="pref-value" v-model="value" class="mt-2" placeholder="quiet" />
      </div>
      <label class="flex items-start gap-2 text-sm">
        <input v-model="confirmed" type="checkbox" class="mt-1 size-4 accent-primary" />
        Save this as a long-term preference. I understand it will not change restaurant facts.
      </label>
      <Button type="submit">Save preference</Button>
    </form>
    <Button class="mt-8" variant="outline" @click="confirmDelete = true">Delete my memory</Button>
    <Dialog :open="confirmDelete" @update:open="confirmDelete = $event">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this browser's memory?</DialogTitle>
          <DialogDescription>
            This removes the saved preferences and conversation rows for the local user id. It does not change restaurant data.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="confirmDelete = false">Cancel</Button>
          <Button @click="removeMemory">Delete</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
