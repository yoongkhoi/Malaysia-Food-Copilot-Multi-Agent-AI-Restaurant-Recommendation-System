export interface EvidenceCard {
  dataset_origin?: string
  name?: string | null
  location_verified?: boolean
  stored_address?: string | null
}

export function evidenceLines(restaurant: EvidenceCard): string[] {
  const source = restaurant.dataset_origin === 'discovered'
    ? 'Source: unverified web candidate, not a canonical record'
    : 'Source: canonical OSM record'
  const identity = restaurant.name
    ? 'Identity: stored name only; the business is not verified'
    : 'Identity: name is not on file'
  const location = restaurant.location_verified
    ? 'Location: street address is verified'
    : restaurant.stored_address
      ? 'Location: street address is stored but not verified'
      : 'Location: street address is not on file'
  return [source, identity, location, 'Operating status: not recorded']
}
