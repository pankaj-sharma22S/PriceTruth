export type Platform = {
  key: string;
  name: string;
  inspection: string;
  discovery: string;
  discovery_note: string;
  manual_search_url: string;
}

export type Offer = {
  id: number;
  listing_id?: number | null;
  platform: string;
  url: string;
  title: string;
  image_url?: string | null;
  price: string | null;
  mrp?: string | null;
  discount_percent?: string | null;
  currency: string | null;
  price_type: string;
  availability: string;
  observed_at: string | null;
  freshness?: string;
  status: string;
  match: {
    classification: string;
    evidence: string[];
    missing: string[];
    conflicts: string[];
  };
}

export type Product = {
  id: number;
  title: string;
  brand?: string;
  model?: string;
  origin_platform?: string;
  image_url?: string | null;
  identifiers: Record<string, string>;
  specs: Record<string, string>;
}

export type Candidate = {
  id: number;
  listing_id?: number | null;
  platform: string;
  url: string;
  title: string;
  brand?: string | null;
  model?: string | null;
  identifiers: Record<string, string>;
  specs: Record<string, string>;
  image_url?: string | null;
  match_classification: string;
  match_evidence: {
    evidence: string[];
    missing: string[];
    conflicts: string[];
  };
  price: string | null;
  mrp?: string | null;
  discount_percent?: string | null;
  currency: string | null;
  price_type: string;
  availability: string;
  observed_at: string;
  freshness: string;
}

export type PlatformCheck = {
  platform: string;
  status: string;
  message?: string | null;
  attempts: number;
  checked_at?: string | null;
  candidates: Candidate[];
}

export type DiscoveryRun = {
  id: number;
  product_id: number;
  status: string;
  created_at: string;
  completed_at?: string | null;
  checks: PlatformCheck[];
  lowest_verified_offer: Candidate | null;
}

export type Comparison = {
  product: Product;
  source?: {
    platform: string;
    status: string;
    observed_at: string;
  };
  offers: Offer[];
  lowest_verified_offer: Offer | Candidate | null;
  platforms: Platform[];
  discovery_run_id?: number;
}

export type TrackingJob = {
  id: number;
  product_id: number;
  product_title?: string;
  listing_id?: number | null;
  listing_platform?: string | null;
  listing_url?: string | null;
  current_price?: string | null;
  current_availability?: string | null;
  name?: string | null;
  active: boolean;
  mode: 'any_drop' | 'target_price' | 'percent_drop' | 'back_in_stock' | 'out_of_stock' | 'price_change';
  target_price: string | null;
  threshold_percent?: string | null;
  interval_minutes: number;
  last_checked_at: string | null;
  next_run_at: string;
  last_error?: string | null;
}

export type AlertEvent = {
  id: number;
  tracking_id: number;
  listing_id?: number | null;
  product_id?: number | null;
  kind: string;
  message: string;
  created_at: string;
}

export type DataCalculations = {
  data_sources: {
    total_products: number;
    total_listings: number;
    total_price_observations: number;
    total_stock_observations: number;
    active_tracking_jobs: number;
    total_discovery_runs: number;
  };
  data_extraction: {
    sources: {
      json_ld: number;
      html_selectors: number;
      embedded_scripts: number;
    };
    stock_distribution: {
      in_stock: number;
      out_of_stock: number;
      preorder: number;
      unknown: number;
    };
  };
  matching_verification: {
    exact_matches_found: number;
    similar_matches_found: number;
    critical_spec_rules: string[];
    match_algorithm: string;
  };
  price_calculations: {
    currency: string;
    max_discount_observed_pct: number;
    formula_mrp_discount: string;
    lowest_verified_price_rules: string;
  };
  alert_evaluation: {
    mode_distribution: Record<string, number>;
    total_alert_events: number;
    next_scheduled_check: string | null;
  };
  job_activity: {
    retailers: {
      key: string;
      name: string;
      listings_tracked: number;
      candidates_discovered: number;
      status: string;
    }[];
    recent_activity: {
      id: number;
      platform: string;
      price: string | null;
      currency: string | null;
      availability: string;
      status: string;
      source: string;
      observed_at: string;
    }[];
  };
}


// ==========================================
// User & Alert Types
// ==========================================

export type UserProfile = {
  id: string;
  email: string;
  full_name?: string | null;
  preferences: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export type SavedProduct = {
  id: number;
  product_id: number;
  title: string;
  brand?: string | null;
  model?: string | null;
  origin_platform?: string | null;
  origin_url?: string | null;
  notes?: string | null;
  saved_at: string;
  current_lowest_price?: number | null;
  has_active_alert: boolean;
}

export type PriceAlert = {
  id: number;
  user_id: string;
  product_id: number;
  listing_id?: number | null;
  name?: string | null;
  mode: 'target_price' | 'percent_drop' | 'back_in_stock' | 'out_of_stock' | 'any_drop' | 'price_change';
  target_price?: number | null;
  threshold_percent?: number | null;
  status: 'ACTIVE' | 'TRIGGERED' | 'PAUSED' | 'EXPIRED';
  trigger_price?: number | null;
  triggered_at?: string | null;
  interval_minutes: number;
  last_checked_at?: string | null;
  next_run_at?: string | null;
  created_at: string;
  updated_at: string;
  product?: {
    id: number;
    title: string;
    brand?: string | null;
    origin_platform?: string | null;
    origin_url?: string | null;
  } | null;
  listing?: {
    id: number;
    platform: string;
    title: string;
    url: string;
  } | null;
  current_lowest_price?: number | null;
}

export type UserAlertHistoryEvent = {
  id: number;
  alert_id?: number | null;
  user_id?: string | null;
  product_id?: number | null;
  listing_id?: number | null;
  kind: string;
  message: string;
  target_price?: number | null;
  trigger_price?: number | null;
  previous_price?: number | null;
  price_delta?: number | null;
  product_title?: string | null;
  platform?: string | null;
  listing_url?: string | null;
}

export type UserNotification = {
  id: number;
  user_id: string;
  alert_id?: number | null;
  title: string;
  message: string;
  channel: string;
  is_read: boolean;
  created_at: string;
}

export type PriceHistoryPoint = {
  id: number;
  listing_id: number;
  platform: string;
  listing_title: string;
  url: string;
  price: number;
  currency: string;
  availability: string;
  status: string;
  observed_at: string;
}

export type PriceHistoryResponse = {
  product_id: number;
  range: string;
  points: PriceHistoryPoint[];
  summary: {
    min_price: number | null;
    max_price: number | null;
    current_price: number | null;
    initial_price: number | null;
    price_change: number;
    total_observations: number;
  };
}
