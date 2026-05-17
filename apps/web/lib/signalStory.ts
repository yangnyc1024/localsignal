import type { Signal } from "@/lib/types";

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

function storyText(signal: Signal, key: string) {
  const value = signal.evidence[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function storyReceipt(signal: Signal) {
  const value = signal.evidence.evidence_receipt;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

function receiptText(receipt: Record<string, unknown>, key: string) {
  const value = receipt[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

export function cuisineType(signal: Signal) {
  const backendType = storyText(signal, "food_or_cuisine_type");
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
  if (neighborhood && neighborhood !== signal.city) {
    return `${neighborhood}, ${signal.city}`;
  }
  return signal.city;
}

export function placeIdentity(signal: Signal) {
  return {
    cuisine: cuisineType(signal),
    name: signal.place.name,
    area: placeArea(signal)
  };
}

export function phenomenonTitle(signal: Signal) {
  const backendTitle = storyText(signal, "phenomenon_title");
  if (backendTitle) {
    return backendTitle;
  }

  const topic = topicFor(signal);
  const area = signal.place.neighborhood || signal.city;

  if (signal.signal_strength === "Quiet") {
    return `${topic} is quiet this week`;
  }

  if (signal.signal_type === "sentiment_shift") {
    return topic === "Wait-time" ? `Wait-time talk is shifting at ${signal.place.name}` : `${topic} tone is shifting at ${signal.place.name}`;
  }

  if (signal.signal_type === "keyword_spike") {
    return `${topic} is becoming the repeated clue at ${signal.place.name}`;
  }

  if (signal.signal_type === "new_place_detected") {
    return `${signal.place.name} is newly on the local radar`;
  }

  if (signal.signal_strength === "Watching") {
    return `${topic} is worth watching at ${signal.place.name}`;
  }

  return `${topic} activity is picking up at ${signal.place.name}`;
}

export function readerSummary(signal: Signal) {
  const backendHook = storyText(signal, "reader_hook");
  const hook = backendHook || signalHook(signal);
  const sourceCount = sourceCountFor(signal);
  const evidenceText = sourceCount > 1 ? `It repeats across ${sourceCount} source types.` : "Right now this is still mostly a one-source read.";

  if (signal.signal_strength === "Strong signal") {
    return `${hook} ${evidenceText}`;
  }

  if (signal.signal_strength === "Watching") {
    return `${hook} ${evidenceText}`;
  }

  return `${hook} The system is watching for fresher, repeated evidence before calling it movement.`;
}

export function evidenceNotes(signal: Signal) {
  const notes: string[] = [];
  const velocity = signal.evidence.velocity_ratio;
  const mentionCount = mentionCountFor(signal);
  const sourceCount = sourceCountFor(signal);
  const keywords = cleanKeywords(signal).slice(0, 4);
  const receipt = storyReceipt(signal);
  const repeatedTerms = receiptText(receipt, "repeated_terms");

  const backendNotice = storyText(signal, "what_to_notice");
  notes.push(backendNotice || signalMicroNote(signal));

  if (repeatedTerms && repeatedTerms !== "Still forming") {
    notes.push(`Repeated clue: ${repeatedTerms}.`);
  } else if (keywords.length) {
    notes.push(`Repeated clue: ${keywords.slice(0, 3).join(", ")}.`);
  }

  if (sourceCount > 1) {
    notes.push(`Seen across ${sourceCount} source types.`);
  } else if (typeof velocity === "number" && velocity >= 5) {
    notes.push("The pace is unusual, but confirmation is still narrow.");
  } else if (mentionCount) {
    notes.push(`${mentionCount} recent mention${mentionCount === 1 ? "" : "s"} in the current window.`);
  } else {
    notes.push("Evidence coverage is still forming.");
  }

  return notes.slice(0, 3);
}

export function goodFor(signal: Signal) {
  const backendGoodFor = storyText(signal, "good_for");
  if (backendGoodFor) {
    return backendGoodFor;
  }

  const category = categoryLabel(signal.place.category).toLowerCase();
  const keywords = cleanKeywords(signal);
  const topic = keywords.slice(0, 2).join(" / ") || category;

  if (signal.signal_strength === "Quiet") {
    return `Keeping an eye on ${category} without forcing a trend.`;
  }
  if (signal.signal_type === "sentiment_shift") {
    return `People tracking whether local attention around ${topic} is changing tone.`;
  }
  if (category.includes("bakery") || category.includes("dessert")) {
    return `Dessert and bakery watchers around ${signal.place.neighborhood || signal.city}.`;
  }
  if (category.includes("cafe")) {
    return `Cafe watchers and people comparing daytime local habits.`;
  }
  if (category.includes("korean")) {
    return `Korean food watchers and group-dinner planners.`;
  }
  return `People tracking ${topic} movement nearby.`;
}

export function watchOut(signal: Signal) {
  const backendSkeptic = storyText(signal, "skeptic_note");
  if (backendSkeptic) {
    return backendSkeptic;
  }

  const backendWatchOut = storyText(signal, "watch_out");
  if (backendWatchOut) {
    return backendWatchOut;
  }

  const sourceCount = sourceCountFor(signal);
  const mentionCount = mentionCountFor(signal);

  if (signal.signal_strength === "Quiet") {
    return "No strong movement is visible yet.";
  }
  if (sourceCount <= 1) {
    return "Evidence is still mostly one-source, so treat it as early.";
  }
  if (mentionCount > 0 && mentionCount < 3) {
    return "Mention count is still small, even if the direction is interesting.";
  }
  return "This is movement evidence, not a guarantee that you will like the place.";
}

export function bestReadAs(signal: Signal) {
  const backendRead = storyText(signal, "best_read_as");
  if (backendRead) {
    return backendRead;
  }

  if (signal.signal_strength === "Strong signal") {
    return "A local movement worth noticing, with judgment left to you.";
  }
  if (signal.signal_strength === "Watching") {
    return "An early clue to watch, not enough to hype yet.";
  }
  return "A quiet read. The system is saying not much is breaking out right now.";
}

export function placeContext(signal: Signal) {
  const backendContext = storyText(signal, "place_anchor_reason");
  if (backendContext) {
    return backendContext;
  }
  return `${signal.place.name} is the place attached to this signal. We use it as the anchor where the activity is showing up, not as a blanket recommendation.`;
}

export function evidenceReceipt(signal: Signal) {
  const receipt = storyReceipt(signal);
  const keywords = cleanKeywords(signal).slice(0, 3);
  const sourceCount = sourceCountFor(signal);
  const mentionCount = mentionCountFor(signal);
  const items = [
    { label: "Recent mentions", value: receiptText(receipt, "recent_mentions") || mentionCount || "Building" },
    { label: "Source types", value: receiptText(receipt, "source_types") || sourceCount || 1 },
    { label: "Repeated terms", value: receiptText(receipt, "repeated_terms") || (keywords.length ? keywords.join(", ") : "Still forming") },
    { label: "Evidence read", value: receiptText(receipt, "evidence_read") || signal.confidence }
  ];
  const freshness = receiptText(receipt, "freshness");
  return freshness ? [...items, { label: "Freshness", value: freshness }] : items;
}

export function weeklyRead(signals: Signal[]) {
  const strong = signals.filter((signal) => signal.signal_strength === "Strong signal");
  const watching = signals.filter((signal) => signal.signal_strength === "Watching");
  const movementCount = strong.length + watching.length;
  const top = [...signals].sort((left, right) => right.score - left.score)[0];
  const topCategory = categoryLabel(top?.place.category || "food").toLowerCase();
  const activeCategories = topCategories(signals).slice(0, 2);

  if (!signals.length) {
    return {
      headline: "No clear local breakout yet",
      body: "The system is still watching fresh mentions, menu language, and cross-platform activity before calling anything a signal.",
      bullets: ["No strong weekly movement is visible yet.", "Quiet weeks are shown honestly instead of filled with generated recommendations."]
    };
  }

  return {
    headline: `${capitalize(topCategory)} is carrying the clearest movement this week`,
    body: `${movementCount} local change${movementCount === 1 ? "" : "s"} are visible across Fort Lee, Edgewater, and Palisades Park. Read these as evidence-backed local movement, not a best-of list.`,
    bullets: [
      activeCategories.length ? `${activeCategories.join(" and ")} are the most active lanes right now.` : "Food activity is mixed across categories.",
      strong.length ? `${strong.length} item${strong.length === 1 ? "" : "s"} look strong enough to call moving now.` : "Most movement is still early, so it stays in watching.",
      "Each card keeps the place as an anchor, while the story starts with what changed."
    ]
  };
}

export function sourceCountFor(signal: Signal) {
  return signal.evidence.sources?.length || signal.evidence.source_count || 0;
}

export function mentionCountFor(signal: Signal) {
  return signal.evidence.current_mention_count || signal.evidence.mention_count || 0;
}

function signalHook(signal: Signal) {
  const keywords = cleanKeywords(signal);
  const place = signal.place.name;
  const cuisine = cuisineType(signal).toLowerCase();
  const has = (term: string) => keywords.includes(term);

  if (has("wait") || has("long")) {
    return `Wait-time language is the thing to watch around ${place}.`;
  }
  if (has("empanadas")) {
    return `Empanadas are the clearest food clue inside the recent ${place} chatter.`;
  }
  if (has("chicken") && has("wings")) {
    return `Chicken wings, with spicy jjambbong nearby in the language, are standing out at ${place}.`;
  }
  if (has("bread") || has("salt") || has("salty")) {
    return `Bread, especially salty/salted bread language, is carrying the recent ${place} signal.`;
  }
  if (has("pizza")) {
    return `Pizza is the repeated item, with wait/service language worth watching separately.`;
  }
  if (has("seafood")) {
    return `Seafood is the most concrete repeated clue in the recent ${place} mentions.`;
  }
  if (has("pork") && has("belly")) {
    return `Pork belly is the specific BBQ clue showing up around ${place}.`;
  }
  if (has("music")) {
    return `The signal is less about a single dish and more about dinner plus music/atmosphere at ${place}.`;
  }
  if (cuisine.includes("turkish")) {
    return `The read is broad Turkish/Mediterranean attention rather than one standout dish yet.`;
  }
  if (cuisine.includes("korean")) {
    return `The Korean food signal is present, but the dish-level clue is still forming.`;
  }
  return `The signal is broad ${cuisine} activity, not a specific dish breakout yet.`;
}

function signalMicroNote(signal: Signal) {
  const keywords = cleanKeywords(signal);
  const has = (term: string) => keywords.includes(term);
  const velocity = signal.evidence.velocity_ratio;

  if (has("wait") || has("long")) return "Wait/crowd language is part of the pattern.";
  if (has("music")) return "Food language is mixed with atmosphere and music.";
  if (has("bread") || has("pizza") || has("empanadas") || has("seafood")) return "A concrete item is showing up repeatedly.";
  if (has("chicken") && has("wings")) return "A specific dish is carrying the signal.";
  if (typeof velocity === "number" && velocity >= 5) return "The recent pace is well above baseline.";
  return "The language is still broad, so this stays cautious.";
}

function topicFor(signal: Signal) {
  const keywords = cleanKeywords(signal);
  const allowedTerms = new Set([
    "line", "wait", "wait time", "sold out", "worth the drive", "viral", "new menu",
    "opening", "soft opening", "reservation", "packed", "quiet work spot", "late night",
    "pizza", "sourdough", "bread", "pastry", "croissant", "bun", "cake", "dessert",
    "matcha", "cream", "coffee", "latte", "seafood", "crab", "chicken wings", "wings",
    "bbq", "korean bbq", "ramen", "sushi", "gyro", "kebab", "falafel", "empanadas"
  ]);
  const useful = keywords.filter((keyword) => allowedTerms.has(keyword));
  if (keywords.includes("chicken") && keywords.includes("wings") && !useful.includes("chicken wings")) {
    useful.unshift("chicken wings");
  }
  if (useful.length) {
    const labelMap: Record<string, string> = { wait: "Wait-time", "wait time": "Wait-time", "late night": "Late-night", "chicken wings": "Chicken wings" };
    return labelMap[useful[0]] || titleCase(useful[0]);
  }
  return categoryLabel(signal.place.category);
}

function cleanKeywords(signal: Signal) {
  return (signal.evidence.keywords || [])
    .map((keyword) => keyword.trim().toLowerCase())
    .filter((keyword) => keyword.length > 2 && !fillerWords.has(keyword));
}

function topCategories(signals: Signal[]) {
  const counts = new Map<string, number>();
  for (const signal of signals) {
    const label = categoryLabel(signal.place.category);
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1])
    .map(([label]) => label);
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

function titleCase(value: string) {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
