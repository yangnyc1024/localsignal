import type { Signal } from "@/lib/types";

/**
 * Display-friendly place name. Mirrors the engine's place.names cleaning:
 * drop marketing payloads ("| All You Can EAT", " - Cajun Seafood ...") but
 * keep CJK characters — they are meaningful to the local audience.
 * Canonical cleaning lives server-side in places.display_name; this guards
 * older data that predates that column.
 */
export function displayPlaceName(name: string, maxLen = 40): string {
  let cleaned = name.replace(/[\u0000-\u001f]/g, " ").split("|")[0];
  const head = cleaned.split(/\s+[-–—/]\s+/)[0].trim();
  if (head.length >= 6) cleaned = head;
  cleaned =
    cleaned
      .replace(/\s+/g, " ")
      .replace(/^[\s\-–—/,|]+|[\s\-–—/,|]+$/g, "")
      .trim() || name.trim();
  if (cleaned.length <= maxLen) return cleaned;
  const cutAt = cleaned.search(/ [-|/] /);
  if (cutAt > 8 && cutAt <= maxLen) return cleaned.slice(0, cutAt).trim();
  return cleaned.slice(0, maxLen).trimEnd() + "…";
}

const fillerWords = new Set([
  "food",
  "place",
  "restaurant",
  "service",
  "really",
  "great",
  "good",
  "best",
  "just",
  "new",
  "nice",
  "love",
  "everything",
  "experience",
  "time"
]);

export function cuisineType(signal: Signal) {
  const backendType = textEvidence(signal, "food_or_cuisine_type");
  if (backendType) {
    return backendType;
  }

  const haystack = `${signal.place.name} ${signal.place.category} ${signal.title} ${signal.summary} ${(signal.evidence.keywords || []).join(" ")}`.toLowerCase();
  const rules: Array<[string, string[]]> = [
    ["Korean BBQ", ["korean bbq", "bbq", "samgyupsal", "pork belly"]],
    ["Korean", ["korean", "tofu", "soondubu", "banchan", "pocha"]],
    ["Cajun seafood", ["cajun", "seafood", "crab", "boil"]],
    ["Bakery", ["bakery", "bread", "pastry", "croissant", "bun"]],
    ["Dessert", ["dessert", "cake", "cream", "matcha", "sweet"]],
    ["Cafe", ["cafe", "coffee", "espresso", "latte"]],
    ["Turkish / Mediterranean", ["doner", "döner"]],
    ["Mediterranean", ["mediterranean", "gyro", "kebab", "falafel"]],
    ["Latin / Caribbean", ["latin", "caribbean", "coqui", "puerto"]],
    ["Japanese", ["ramen", "sushi", "izakaya", "japanese"]],
    ["Pizza", ["pizza", "pinsa"]]
  ];
  for (const [label, terms] of rules) {
    if (terms.some((term) => haystack.includes(term))) {
      return label;
    }
  }
  return categoryLabel(signal.place.category);
}

export function placeArea(signal: Signal) {
  const neighborhood = signal.place.neighborhood?.trim();
  const city = signal.city?.trim();
  if (neighborhood && city && neighborhood !== city) {
    return `${neighborhood}, ${city}`;
  }
  return neighborhood || city || "";
}

export function placeIdentity(signal: Signal) {
  return {
    cuisine: cuisineType(signal),
    name: signal.place.name,
    area: placeArea(signal)
  };
}

export function evidenceNotes(signal: Signal) {
  const notes: string[] = [];
  const backendNotice = textEvidence(signal, "what_to_notice");
  const keywords = cleanKeywords(signal).slice(0, 4);
  const sourceCount = sourceCountFor(signal);
  const mentionCount = mentionCountFor(signal);

  notes.push(backendNotice || signalMicroNote(signal));

  if (keywords.length) {
    notes.push(`Repeated language around ${keywords.slice(0, 3).join(", ")} is showing up more often.`);
  }

  if (sourceCount > 1) {
    notes.push(`Seen across ${sourceCount} source paths.`);
  } else if (mentionCount) {
    notes.push(`${mentionCount} recent mention${mentionCount === 1 ? "" : "s"} in the current window.`);
  } else {
    notes.push("Evidence coverage is still forming.");
  }

  return notes.slice(0, 3);
}

export function sourceCountFor(signal: Signal) {
  return signal.evidence.sources?.length || signal.evidence.source_count || 0;
}

export function mentionCountFor(signal: Signal) {
  return signal.evidence.current_mention_count || signal.evidence.mention_count || 0;
}

export function textEvidence(signal: Signal, key: string) {
  const value = signal.evidence[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function signalMicroNote(signal: Signal) {
  const keywords = cleanKeywords(signal);
  const has = (term: string) => keywords.includes(term);

  if (has("wait") || has("long")) return "Wait or crowd language is part of the pattern.";
  if (has("music")) return "Food language is mixed with atmosphere and music.";
  if (has("bread") || has("pizza") || has("empanadas") || has("seafood")) return "A concrete item is showing up repeatedly.";
  if (has("chicken") && has("wings")) return "A specific dish is carrying the signal.";
  return "The food read is still broad, so this stays cautious.";
}

function cleanKeywords(signal: Signal) {
  return (signal.evidence.keywords || [])
    .map((keyword) => keyword.trim().toLowerCase())
    .filter((keyword) => keyword.length > 2 && !fillerWords.has(keyword));
}

function categoryLabel(category: string) {
  const lower = category.toLowerCase();
  if (lower.includes("bakery")) return "Bakery";
  if (lower.includes("cafe") || lower.includes("coffee")) return "Cafe";
  if (lower.includes("dessert")) return "Dessert";
  if (lower.includes("korean")) return "Korean food";
  if (lower.includes("bar")) return "Late-night food";
  return "Food";
}
