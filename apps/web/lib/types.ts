export type Place = {
  id: string;
  name: string;
  category: string;
  city: string;
  neighborhood?: string | null;
};

export type Signal = {
  id: string;
  signal_type: string;
  title: string;
  summary: string;
  evidence: {
    keywords?: string[];
    sources?: string[];
    review_velocity?: number;
    mention_count?: number;
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

export type Report = {
  id: string;
  title: string;
  region: string;
  week_start: string;
  intro: string;
  signals: Signal[];
};
