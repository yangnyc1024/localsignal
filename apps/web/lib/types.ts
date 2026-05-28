export type Place = {
  id: string;
  name: string;
  category: string;
  city: string;
  neighborhood?: string | null;
  address?: string | null;
  lat?: number | null;
  lng?: number | null;
  google_place_id?: string | null;
  map_url?: string | null;
};

export type Signal = {
  id: string;
  slug: string;
  signal_type: string;
  title: string;
  summary: string;
  momentum_driver: string;
  evidence_assessment: string;
  confidence: "High" | "Medium" | "Low";
  signal_strength: "Strong signal" | "Watching" | "Quiet";
  signal_strength_reason: string;
  evidence: {
    keywords?: string[];
    sources?: string[];
    place_profile?: PlaceProfile;
    food_signal?: FoodSignal;
    review_velocity?: number;
    velocity_ratio?: number;
    mention_count?: number;
    current_mention_count?: number;
    source_count?: number;
    outside_region_count?: number;
    average_sentiment?: number;
    [key: string]: unknown;
  };
  score: number;
  city: string;
  week_start: string;
  place: Place;
};

export type PlaceProfile = {
  known_for?: string;
  food_types?: string[];
  signature_items?: string[];
  flavor_cues?: string[];
  occasions?: string[];
  caveats?: string;
  source_count?: number;
};

export type FoodSignal = {
  summary?: string;
  primary_pull?: string;
  signal_dish?: string;
  flavor_cue?: string;
  occasion?: string;
  confidence?: "High" | "Medium" | "Low" | string;
  evidence_basis?: string;
  image_query?: string;
  image_alt?: string;
};

export type Report = {
  id: string;
  title: string;
  region: string;
  week_start: string;
  intro: string;
  briefing?: BriefingPayload | null;
  signals: Signal[];
};

export type BriefingPayload = {
  title?: string;
  subtitle?: string;
  why_it_matters?: string;
  places_involved?: Array<{
    name: string;
    area: string;
    category: string;
    signal_slug: string;
    reason: string;
  }>;
  supporting_reads?: Array<{
    title: string;
    summary: string;
    signal_slug: string;
  }>;
  sources?: Array<{
    label: string;
    detail: string;
    signal_slug: string;
  }>;
};

export type SignalMetric = {
  label: string;
  value: string;
  detail?: string | null;
  trend: "up" | "down" | "steady";
};

export type SignalEvidenceItem = {
  platform: string;
  timestamp: string;
  excerpt: string;
  relevance: string;
  metadata: Record<string, string>;
  source_url?: string | null;
};

export type RelatedSignal = {
  slug: string;
  title: string;
  place_name: string;
  neighborhood?: string | null;
  signal_type: string;
  score: number;
};

export type SignalDetail = Signal & {
  rank: number;
  region: string;
  date_range: string;
  tags: string[];
  ai_summary: string;
  what_changed: string[];
  why_this_matters: string;
  confidence_reason: string;
  baseline_context: BaselineContext;
  metrics: SignalMetric[];
  restaurant_brief?: RestaurantBrief | null;
  food_facts?: FoodFact[];
  evidence_items: SignalEvidenceItem[];
  related_signals: RelatedSignal[];
};

export type FoodFact = {
  fact_type: "dish" | "occasion" | "behavior";
  fact_value: string;
  evidence_text: string;
  source: string;
  source_url?: string | null;
  confidence: number;
  occurred_at?: string | null;
};

export type RestaurantBrief = {
  what_it_is: string;
  official_context_note: string;
  signature_menu_items: string[];
  location_format: string;
  vibe_tags?: string[];
  occasions?: string[];
  source_chips: string[];
  trust_note: string;
};

export type BaselineContext = {
  status: string;
  heat_score: number;
  summary: string;
  trailing_30d_mentions: number;
  trailing_90d_mentions: number;
  trailing_365d_mentions: number;
  source_diversity: number;
  recurring_keywords: string[];
  delta_vs_baseline?: string | null;
};

export type AlwaysHotPlace = {
  place_id: string;
  place_name: string;
  category: string;
  neighborhood?: string | null;
  city: string;
  status: string;
  heat_score: number;
  summary: string;
  recurring_keywords: string[];
  source_diversity: number;
};


export type SocialSourceRun = {
  id: string;
  provider: string;
  platform: string;
  dataset_id?: string | null;
  query?: string | null;
  status: string;
  total_records: number;
  normalized_records: number;
  fresh_records: number;
  old_records_dropped: number;
  parsed_items: number;
  resolved_items: number;
  review_items: number;
  unresolved_items: number;
  source_counts: Record<string, number>;
  error?: string | null;
  started_at: string;
  finished_at: string;
};
