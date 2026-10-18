<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { RestaurantResult } from '@/types/api'

const props = defineProps<{
  restaurants: RestaurantResult[]
  selectedId?: string
}>()
const emit = defineEmits<{ select: [id: string] }>()
const host = ref<HTMLElement | null>(null)
let map: { remove: () => void, flyTo: (center: [number, number], zoom: number) => void } | null = null
let markers = new Map<string, { openPopup: () => void, setStyle: (style: object) => void }>()

function located() {
  return props.restaurants.filter((item) => typeof item.latitude === 'number' && typeof item.longitude === 'number')
}

async function draw() {
  if (!host.value) return
  const places = located()
  if (!places.length) return
  const leaflet = await import('leaflet')
  await import('leaflet/dist/leaflet.css')
  if (map) {
    map.remove()
    map = null
  }
  markers = new Map()
  const first = places.find((item) => item.restaurant_id === props.selectedId) || places[0]
  const created = leaflet.map(host.value).setView([first.latitude as number, first.longitude as number], 14)
  leaflet.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
    maxZoom: 19,
  }).addTo(created)
  for (const place of places) {
    const active = place.restaurant_id === (props.selectedId || first.restaurant_id)
    const marker = leaflet.circleMarker([place.latitude as number, place.longitude as number], {
      radius: active ? 11 : 8,
      color: active ? '#8A5A12' : '#6B4E2E',
      fillColor: active ? '#E2A325' : '#F8E3A8',
      fillOpacity: 0.95,
      weight: 2,
    }).addTo(created)
    const address = place.stored_address || 'Street address is not on file'
    const photo = place.photo_url ? `<br><img src="${place.photo_url}" alt="" width="120">` : ''
    marker.bindPopup(
      `<strong>${place.name || 'Unnamed restaurant'}</strong><br>${place.cuisine_label || 'Cuisine not recorded'}<br>${address}${photo}<br><a href="${place.map_url || '#'}" target="_blank" rel="noreferrer">Open this pin on OpenStreetMap</a>`,
    )
    marker.on('click', () => emit('select', place.restaurant_id))
    markers.set(place.restaurant_id, marker)
  }
  const chosen = markers.get(props.selectedId || first.restaurant_id)
  chosen?.openPopup()
  map = created
}

onMounted(draw)
watch(() => [props.restaurants, props.selectedId], draw)
onBeforeUnmount(() => map?.remove())
</script>

<template>
  <div>
    <div ref="host" class="h-80 w-full overflow-hidden rounded-2xl border border-border shadow-sm" />
    <p v-if="!located().length" class="mt-2 text-xs text-muted-foreground">
      These results have no stored coordinates, so the map cannot place a pin.
    </p>
    <p v-else class="mt-2 text-xs text-muted-foreground">
      OpenStreetMap tiles. Click a pin or a card to move the popup to that restaurant. The other recommendations stay on the map.
    </p>
  </div>
</template>
