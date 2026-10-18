export interface ReviewEvidenceLine {
  restaurant_name?: string
  kind?: string
  rating?: number | null
  source?: string
  span?: string
}

export function reviewEvidenceLine(item: ReviewEvidenceLine): string {
  const rating = item.rating == null
    ? ''
    : ` Stored rating on this review: ${item.rating} (${item.source || 'source not named'}).`
  return `${item.restaurant_name || 'Unnamed restaurant'} — ${item.kind || 'opinion'}, not a verified fact.${rating} ${item.span || ''}`.trim()
}
