const NAMED_AREA = /kuala lumpur|old klang road|jalan klang lama|吉隆坡|旧巴生路/i

export function buildDiscoveryQuery(filters: { text: string }): string {
  const text = filters.text.trim()
  if (!text) return 'Old Klang Road'
  if (NAMED_AREA.test(text)) return text
  return `${text} Old Klang Road`
}

export interface FollowUpTurn {
  role: string
  response?: {
    intent?: string
    needs_clarification?: boolean
    constraints?: {
      region?: string | null
      city?: string | null
      cuisine?: string | null
      name_contains?: string | null
      cuisines?: string[]
      exclude_brands?: string[]
      exclude_cuisines?: string[]
    }
    results?: { name?: string | null, restaurant_id?: string | null }[]
  }
}

export function followUpContext(turns: FollowUpTurn[]) {
  const relevant = turns.filter((turn) => {
    const response = turn.response
    if (!response || response.intent === 'general_qa') return false
    if (response.needs_clarification && !response.constraints?.region && !response.constraints?.cuisine) return false
    return Boolean(response.constraints?.region || response.constraints?.cuisine || response.constraints?.cuisines?.length)
  })
  const previous = relevant.length ? relevant[relevant.length - 1].response : undefined
  if (!previous?.constraints) return undefined
  const shownNames = relevant.flatMap((turn) => (turn.response?.results ?? []).map((item) => item.name).filter((name): name is string => Boolean(name)))
  const shownIds = relevant.flatMap((turn) => (turn.response?.results ?? []).map((item) => item.restaurant_id).filter((id): id is string => Boolean(id)))
  return {
    region: previous.constraints.region,
    city: previous.constraints.city,
    cuisine: previous.constraints.cuisine,
    name_contains: previous.constraints.name_contains,
    cuisines: previous.constraints.cuisines,
    exclude_brands: previous.constraints.exclude_brands,
    exclude_cuisines: previous.constraints.exclude_cuisines,
    shown_names: [...new Set(shownNames)],
    shown_ids: [...new Set(shownIds)],
  }
}
