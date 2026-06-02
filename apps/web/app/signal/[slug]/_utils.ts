import { evidenceNotes, placeIdentity } from "@/lib/signalStory";
import type { RelatedSignal, SignalDetail, SignalEvidenceItem } from "@/lib/types";

export type ChartPoint = {
  label: string;
  value: number;
};

// ---------------------------------------------------------------------------
// Pure string utilities
// ---------------------------------------------------------------------------

export function cleanText(value: string) {
  return value
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
    .replace(/\(\s*(?:[0-9a-fA-F]{2,4}\s*)+\)/g, "")
    .replace(/\b[0-9a-fA-F]{6,}\b/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function shortPlaceName(value: string, maxLen = 40): string {
  // Strip CJK characters (Korean, Chinese, Japanese)
  let latin = value.replace(/[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F\u4E00-\u9FFF\u3040-\u30FF\uFF00-\uFFEF]+/g, "").trim();
  // Unwrap if parens wrap the entire remaining string e.g. "(Chungchoon Sikdang)"
  latin = latin.replace(/^\s*\(\s*(.*?)\s*\)\s*$/, "$1").trim();
  latin = latin.replace(/^[|/\-,\s]+|[|/\-,\s]+$/g, "").trim();
  const cleaned = cleanText(latin || value)
    .replace(/\s*\|.*$/, "")
    .replace(/\s*-\s*Cajun Seafood.*$/i, "")
    .replace(/\s+Nj\b/gi, "")
    .trim();
  if (cleaned.length <= maxLen) return cleaned;
  const cutAt = cleaned.search(/ [-|/] /);
  if (cutAt > 8 && cutAt <= maxLen) return cleaned.slice(0, cutAt).trim();
  return cleaned.slice(0, maxLen).trimEnd() + "\u2026";
}

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

export function truncateEvidence(value: string, limit: number) {
  const text = cleanText(value);
  if (text.length <= limit) return text;
  const clipped = text.slice(0, limit);
  const lastSpace = clipped.lastIndexOf(" ");
  return (lastSpace > limit * 0.6 ? clipped.slice(0, lastSpace) : clipped) + "…";
}

export function humanizeReason(value: string) {
  return cleanText(value)
    .replace(/Sharp rise in mention volume to about \S+ times the usual rate/i, "Recent mention pace is well above its usual rhythm")
    .replace(/Recent mention pace rose to \S+ (the )?previous baseline/i, "Recent mention pace is well above the previous baseline")
    .replace(/Mention velocity jumped to ([5-9]|\d{2,})x (the )?previous baseline/i, "Recent mention pace is well above the previous baseline")
    .replace(/Mention velocity jumped to ([^ ]+) times previous baseline/i, "Recent mention pace rose to $1x the previous baseline")
    .replace(/Repeated keywords such as 'food', 'service', and 'amazing' appear often/i, "Service language is showing up more often")
    .replace(/Repeated language around food, service, and amazing is showing up more often/i, "Service language is showing up more often")
    .replace(/Repeated keywords such as '([^']+)', '([^']+)', and '([^']+)' appear often/i, "Repeated language around $1, $2, and $3 is showing up more often")
    .replace(/Two independent sources contribute to the signal/i, "The signal is backed by two independent source paths")
    .replace(/Interest extended to at least one area outside the immediate neighborhood/i, "Some demand is coming from outside the immediate neighborhood");
}

export function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))];
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

// ---------------------------------------------------------------------------
// Signal-specific evidence helpers
// ---------------------------------------------------------------------------

/** Display-safe variant: runs cleanText on the string value. */
export function textEvidence(signal: SignalDetail, key: string) {
  const value = signal.evidence[key];
  return typeof value === "string" ? cleanText(value) : "";
}

export function evidenceList(signal: SignalDetail, key: string) {
  const value = signal.evidence[key];
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string");
  }
  return [];
}

// ---------------------------------------------------------------------------
// Derived data for page sections
// ---------------------------------------------------------------------------

export function heroFor(signal: SignalDetail) {
  const title = textEvidence(signal, "phenomenon_title") || `${shortPlaceName(signal.place.name)} gaining momentum`;
  const rawClaim = textEvidence(signal, "reader_hook") || signal.ai_summary || signal.summary;
  const claim = isOldSignalPhrase(rawClaim) ? foodSignalClaim(signal) : rawClaim;
  return {
    title: cleanTitle(title, signal),
    claim: cleanText(claim)
  };
}

export function profileCuisine(signal: SignalDetail) {
  const identity = placeIdentity(signal);
  const display = displayCuisine(signal, identity.cuisine);
  if (display !== "Local food") {
    return display;
  }
  const foodPull = cleanText(signal.evidence.food_signal?.primary_pull || "");
  if (foodPull) {
    return foodPull;
  }
  return display;
}

export function whyChanged(signal: SignalDetail) {
  const llmReasons = evidenceList(signal, "why_changed")
    .concat(evidenceList(signal, "what_changed"))
    .map(humanizeReason)
    .filter(Boolean);
  const changes = signal.what_changed.map(humanizeReason).filter(Boolean);
  const notes = evidenceNotes(signal).map(humanizeReason).filter(Boolean);
  return unique([...llmReasons, ...changes, ...notes]).slice(0, 4);
}

export function trendPoints(signal: SignalDetail): ChartPoint[] {
  const monthly = signal.baseline_context.trailing_30d_mentions || 0;
  const weeklyBaseline = Math.round(monthly / 4);
  const currentMentions =
    (signal.evidence.current_mention_count as number | undefined) ||
    (signal.evidence.mention_count as number | undefined) ||
    0;

  if (weeklyBaseline > 0 || currentMentions > 0) {
    return [
      { label: "Baseline/wk", value: weeklyBaseline },
      { label: "This week", value: currentMentions }
    ];
  }

  return [
    { label: "Baseline", value: clamp(Math.round(signal.baseline_context.heat_score || 0), 0, 100) },
    { label: "Now", value: clamp(Math.round(signal.score), 0, 100) }
  ];
}

export function curatedEvidence(signal: SignalDetail): SignalEvidenceItem[] {
  return signal.evidence_items
    .filter((item) => item.excerpt.trim())
    .slice(0, 5);
}

export function nearbyPlaces(signal: SignalDetail): RelatedSignal[] {
  return signal.related_signals.filter((related) => related.place_name !== signal.place.name).slice(0, 4);
}

export function nearbyContextLine(signal: SignalDetail, nearby: RelatedSignal[]) {
  if (!nearby.length) {
    return `${shortPlaceName(signal.place.name)} is the active place in this detail view; nearby context will get richer as more local places attach.`;
  }
  const names = nearby.slice(0, 3).map((place) => shortPlaceName(place.place_name)).join(", ");
  return `${shortPlaceName(signal.place.name)} sits near related local signals including ${names}.`;
}

export function googleMapsSearchUrl(signal: SignalDetail) {
  const query = [signal.place.name, signal.place.address, signal.city].filter(Boolean).join(" ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

export function googleMapsEmbedUrl(signal: SignalDetail) {
  const apiKey = process.env.GOOGLE_PLACES_API_KEY || process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
  if (apiKey && typeof signal.place.lat === "number" && typeof signal.place.lng === "number") {
    const center = `${signal.place.lat},${signal.place.lng}`;
    return `https://www.google.com/maps/embed/v1/view?key=${encodeURIComponent(apiKey)}&center=${encodeURIComponent(center)}&zoom=15&maptype=roadmap`;
  }
  const query = [shortPlaceName(signal.place.name), signal.place.address, signal.city].filter(Boolean).join(" ");
  return `https://maps.google.com/maps?output=embed&q=${encodeURIComponent(query)}`;
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

function cleanTitle(value: string, signal: SignalDetail) {
  const title = cleanText(value);
  if (!title || title.includes("|") || isOldSignalPhrase(title)) {
    return `${shortPlaceName(signal.place.name)} gaining momentum`;
  }
  return title;
}

function isOldSignalPhrase(value: string) {
  return /(activity is picking up at|keeps coming up at|tone is shifting at|talk is shifting at|use is changing at)/i.test(value);
}

function foodSignalClaim(signal: SignalDetail) {
  const food = signal.evidence.food_signal;
  const pull = cleanText(food?.primary_pull || profileCuisine(signal));
  const occasion = cleanText(food?.occasion || "a local visit");
  return `${shortPlaceName(signal.place.name)} is showing a food-level read around ${pull.toLowerCase()} for ${occasion.toLowerCase()}.`;
}

function displayCuisine(signal: SignalDetail, value: string) {
  const lower = value.toLowerCase();
  if (lower && lower !== "restaurant" && lower !== "food") {
    return value;
  }
  const haystack = [
    signal.place.name,
    signal.place.category,
    signal.title,
    signal.summary,
    ...(signal.evidence.keywords ?? [])
  ].join(" ").toLowerCase();
  if (haystack.includes("korean bbq") || haystack.includes("bbq")) return "Korean BBQ";
  if (haystack.includes("korean") || haystack.includes("tofu")) return "Korean food";
  if (haystack.includes("donkatsu") || haystack.includes("ramen") || haystack.includes("sushi")) return "Japanese";
  if (haystack.includes("seafood") || haystack.includes("crab")) return "Seafood";
  if (haystack.includes("cafe") || haystack.includes("coffee")) return "Cafe";
  return "Local food";
}
