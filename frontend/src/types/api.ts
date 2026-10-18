export interface RestaurantResult {
  restaurant_id: string
  name: string | null
  stored_address: string | null
  location_verified: boolean
  price_status: string
  price_min_myr: number | null
  price_max_myr: number | null
  halal_status: string
  family_friendly: string
  evidence_urls: string[]
  match_reason: string
  map_url?: string | null
  photo_url?: string | null
  cuisine_label?: string | null
  latitude?: number | null
  longitude?: number | null
  dataset_origin?: string
}

export interface DiscoveryResponse {
  answer: string
  constraints: {
    city: string | null
    region: string | null
    max_budget_myr: number | null
    require_halal_verified: boolean
    family: boolean
    text: string
    cuisine?: string | null
  }
  results: RestaurantResult[]
  exclusion_counts: Record<string, number>
  needs_clarification: boolean
  sources_note: string
  tools_called: string[]
  language: string
  retriever: string
}

export interface ReviewEvidence {
  review_id?: string
  restaurant_id?: string
  restaurant_name?: string
  source?: string
  source_file?: string
  rating?: number | null
  match_status?: string
  span?: string
  kind?: string
  opinion_not_verified_fact?: boolean
}

export interface ChatResponse extends DiscoveryResponse {
  memory_saved: boolean
  memory_note: string
  review_evidence?: ReviewEvidence[]
  review_note?: string
  agent_mode?: string
  tools_called: string[]
  model_name?: string
  model_note?: string
  intent?: string
  trace?: {
    total_ms?: number
    llm_called?: boolean
    model?: string
    model_note?: string
    tools?: string[]
    nodes?: string[]
    intent?: string
    stages?: Record<string, number>
    timing_note?: string
    agents?: { name: string, ok?: boolean, latency_ms?: number }[]
    synthesis?: string
    mcp_status?: string
    mcp_tools?: string[]
  }
}

export interface EvidenceItem {
  restaurant_id: string
  claim: string
  source_url: string
  source_name: string | null
  collected_at: string | null
}

export interface RestaurantDetails {
  ok: boolean
  restaurant: Record<string, unknown>
  evidence: EvidenceItem[]
}

export interface RestaurantEvidence {
  ok: boolean
  restaurant_id: string
  address: string | null
  location_verified: boolean
  location_evidence: string | null
  price_status: string
  price_min_myr: number | null
  price_max_myr: number | null
  halal_status: string
  halal_source_url: string | null
  evidence: EvidenceItem[]
}

export interface MemoryStatus {
  postgres: boolean
  redis: boolean
}

export interface Preference {
  key: string
  value: string
  confirmed: boolean
}

export interface HealthStatus {
  status: string
  pilot: string
  expansion: string
  dataset?: string
  dataset_records?: number
  llm_agent?: boolean
  langgraph?: boolean
  retrieval?: string
  web_search?: boolean
  discovered_records?: number
}
