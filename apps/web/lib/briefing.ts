import type { Report, Signal } from "@/lib/types";
import { cuisineType, evidenceNotes, mentionCountFor, sourceCountFor } from "@/lib/signalStory";

export type FoodCategoryKey =
  | "cafe"
  | "korean"
  | "japanese"
  | "seafood"
  | "pizza"
  | "brunch"
  | "mediterranean"
  | "night-stay"
  | "dinner";

type FoodCategory = {
  key: FoodCategoryKey;
  label: string;
  description: string;
  terms: string[];
};

export const FOOD_CATEGORIES: FoodCategory[] = [
  {
    key: "korean",
    label: "Korean",
    description: "BBQ, tofu, shared tables, and Korean comfort-food nights.",
    terms: ["korean", "bbq", "soondubu", "tofu", "banchan", "samgyupsal", "hanam", "hansang", "chungchoon"]
  },
  {
    key: "japanese",
    label: "Japanese",
    description: "Donkatsu, ramen, sushi, and casual Japanese comfort-food stops.",
    terms: ["donkatsu", "tonkatsu", "ramen", "sushi", "izakaya", "japanese"]
  },
  {
    key: "seafood",
    label: "Seafood",
    description: "Crab boil, seafood, spice, and bigger dinner flavors.",
    terms: ["seafood", "crab", "boil", "cajun", "shrimp", "lobster"]
  },
  {
    key: "mediterranean",
    label: "Mediterranean",
    description: "Doner, kebab, falafel, and quick Mediterranean meals.",
    terms: ["doner", "döner", "kebab", "falafel", "gyro", "mediterranean"]
  },
  {
    key: "pizza",
    label: "Pizza",
    description: "Pizza-specific cards for when the craving is already obvious.",
    terms: ["pizza", "sourdough pizza", "pinsa"]
  },
  {
    key: "cafe",
    label: "Cafe",
    description: "Coffee, matcha, pastries, and longer sit-down visits.",
    terms: ["cafe", "coffee", "espresso", "latte", "matcha", "pastry"]
  },
  {
    key: "brunch",
    label: "Brunch",
    description: "Pancakes, benedicts, and cafe-grill plates.",
    terms: ["brunch", "pancake", "pancakes", "benedict", "omelet"]
  },
  {
    key: "dinner",
    label: "Dinner",
    description: "Waits, lines, and slower dinner expectations.",
    terms: ["wait", "line", "reservation", "dinner", "service pace"]
  },
  {
    key: "night-stay",
    label: "Night stay",
    description: "Late dinner, pocha energy, and places that fit a longer night.",
    terms: ["late", "late-night", "night", "pocha", "pub", "bar", "vibes"]
  }
];

const CATEGORY_MATCH_ORDER: FoodCategoryKey[] = [
  "brunch",
  "pizza",
  "mediterranean",
  "japanese",
  "seafood",
  "korean",
  "cafe",
  "night-stay",
  "dinner"
];

export type FoodRead = {
  label: string;
  why: string;
  href: string;
};

export type LocalBriefing = {
  eyebrow: string;
  scopeTitle: string;
  scopeSummary: string;
  title: string;
  subtitle: string;
  whyItMatters: string;
  foodReads: FoodRead[];
  longTermSignals: LongTermSignalCard[];
  categorySections: CategorySignalSection[];
  sources: BriefingSource[];
};

export type ReaderSignalCard = {
  place: string;
  area: string;
  category: string;
  categoryKey: string;
  signatureDish: string;
  placeSummary: string;
  signalSummary: string;
  href: string;
};

export type LongTermSignalCard = {
  place: string;
  category: string;
  signatureDish: string;
  href: string;
};

export type CategorySignalSection = {
  key: string;
  label: string;
  description: string;
  cards: ReaderSignalCard[];
};

export type BriefingSource = {
  label: string;
  detail: string;
  href: string;
};

export function buildLocalBriefing(report: Report): LocalBriefing {
  const sortedSignals = [...report.signals].sort((left, right) => right.score - left.score);
  const topCards = sortedSignals.slice(0, 3).map(signalCardFor);

  if (!sortedSignals.length) {
    return {
      eyebrow: `Week of ${formatDate(report.week_start)}`,
      title: "Nothing clear is changing this week",
      scopeTitle: "This is a weekly local food briefing",
      scopeSummary: scopeSummary(report),
      subtitle: "The local read is quiet, which is sometimes the most useful answer.",
      whyItMatters: "LocalSignal is holding back rather than turning thin evidence into a story.",
      foodReads: [],
      longTermSignals: [],
      categorySections: [],
      sources: []
    };
  }

  return {
    eyebrow: `${formatDate(report.week_start)} · ${report.region}`,
    scopeTitle: "This is a weekly local food briefing",
    scopeSummary: scopeSummary(report),
    title: weeklyReaderTitle(topCards),
    subtitle: weeklyReaderSubtitle(topCards),
    whyItMatters: weeklyReaderWhy(),
    foodReads: foodReadsFor(sortedSignals),
    longTermSignals: longTermSignalsFor(sortedSignals),
    categorySections: categorySectionsFor(sortedSignals),
    sources: sortedSignals.slice(0, 6).map((signal) => ({
      label: signal.place.name,
      detail: sourceLineFor(signal),
      href: `/signal/${signal.slug}`
    }))
  };
}

function weeklyReaderTitle(topCards: ReaderSignalCard[]) {
  const categories = [...new Set(topCards.map((signal) => signal.category))].slice(0, 3);
  return `This week: ${naturalJoin(categories)}`;
}

function weeklyReaderSubtitle(topCards: ReaderSignalCard[]) {
  const foods = naturalJoin([...new Set(topCards.map((signal) => signal.signatureDish))].slice(0, 3));
  return `A simpler read: these are the food lanes showing up most clearly, starting with ${foods}.`;
}

function weeklyReaderWhy() {
  return "Worth caring about because the signal is attached to actual food choices, not generic buzz: what to order, what kind of stop it fits, and which place has the clearest evidence card.";
}

function categorySectionsFor(signals: Signal[]) {
  const groups = new Map<FoodCategoryKey, ReaderSignalCard[]>();
  for (const signal of signals) {
    const category = categoryForSignal(signal);
    const existing = groups.get(category.key) ?? [];
    if (existing.length < 3) {
      existing.push(signalCardFor(signal));
      groups.set(category.key, existing);
    }
  }
  return FOOD_CATEGORIES
    .map((category) => ({
      key: category.key,
      label: category.label,
      description: categoryDescription(category.label, groups.get(category.key)?.length ?? 0),
      cards: groups.get(category.key) ?? []
    }))
    .filter((section) => section.cards.length > 0);
}

function foodReadsFor(signals: Signal[]): FoodRead[] {
  const used = new Set<string>();
  const reads: FoodRead[] = [];
  for (const signal of signals) {
    const label = readerCategory(signal);
    if (used.has(label)) {
      continue;
    }
    used.add(label);
    reads.push({
      label,
      why: categoryWhy(label, signal),
      href: `/signal/${signal.slug}`
    });
    if (reads.length === 3) {
      break;
    }
  }
  return reads;
}

function longTermSignalsFor(signals: Signal[]): LongTermSignalCard[] {
  const usedPlaces = new Set<string>();
  return FOOD_CATEGORIES.flatMap((category) => {
    const signal = signals.find((candidate) => {
      const place = cleanPlaceName(candidate.place.name);
      return categoryForSignal(candidate).key === category.key && !usedPlaces.has(place);
    });
    if (!signal) {
      return [];
    }
    usedPlaces.add(cleanPlaceName(signal.place.name));
    return [{
      place: cleanPlaceName(signal.place.name),
      category: category.label,
      signatureDish: signatureDish(signal),
      href: `/signal/${signal.slug}`
    }];
  }).slice(0, 8);
}

function signalCardFor(signal: Signal): ReaderSignalCard {
  const category = categoryForSignal(signal);
  return {
    place: cleanPlaceName(signal.place.name),
    area: placeArea(signal),
    category: category.label,
    categoryKey: category.key,
    signatureDish: signatureDish(signal),
    placeSummary: placeSummary(signal),
    signalSummary: signalSummary(signal),
    href: `/signal/${signal.slug}`
  };
}

function signatureDish(signal: Signal) {
  const category = categoryForSignal(signal);
  const explicitSignature = textEvidence(signal, "signature_item");
  if (explicitSignature) {
    return normalizeFoodCue(explicitSignature, category.key) || fallbackCueForCategory(category.key);
  }

  const cuisine = textEvidence(signal, "food_or_cuisine_type");
  if (cuisine) {
    const cuisineCue = normalizeFoodCue(cuisine, category.key);
    if (cuisineCue) {
      return cuisineCue;
    }
  }

  const hookDish = dishFromText(`${textEvidence(signal, "reader_hook")} ${textEvidence(signal, "what_to_notice")}`);
  if (hookDish) {
    return hookDish;
  }

  const keywords = (signal.evidence.keywords ?? []).map((keyword) => keyword.toLowerCase());
  const haystack = `${signal.place.name} ${signal.title} ${signal.summary} ${keywords.join(" ")}`.toLowerCase();
  if (haystack.includes("donkatsu") || haystack.includes("tonkatsu")) return "Donkatsu";
  if (haystack.includes("doner") || haystack.includes("döner")) return "Doner";
  if (haystack.includes("pizza")) return "Pizza";
  if (haystack.includes("pancake")) return "Pancakes";
  if (haystack.includes("benedict")) return "Eggs benedict";
  if (haystack.includes("wing")) return "Chicken wings";
  if (haystack.includes("crab") || haystack.includes("boil")) return "Crab boil";
  if (haystack.includes("seafood")) return "Spicy seafood";
  if (haystack.includes("bbq")) return "Korean BBQ";
  if (haystack.includes("tofu") || haystack.includes("soondubu")) return "Soondubu";
  if (haystack.includes("coffee") || haystack.includes("espresso") || haystack.includes("latte")) return "Coffee";
  if (haystack.includes("matcha")) return "Matcha";
  if (haystack.includes("cake")) return "Cake";
  if (haystack.includes("bakery") || haystack.includes("bread") || haystack.includes("croissant")) return "Bakery";
  if (haystack.includes("dessert")) return "Dessert";
  return fallbackCueForCategory(category.key);
}

function fallbackPlaceSummary(signal: Signal) {
  const llmReason = conciseText(textEvidence(signal, "place_anchor_reason") || textEvidence(signal, "best_read_as") || textEvidence(signal, "good_for"), 150);
  if (llmReason) {
    return llmReason;
  }

  const dish = signatureDish(signal).toLowerCase();
  const place = cleanPlaceName(signal.place.name);
  if (dish.includes("donkatsu")) return `${place} is useful when you want a crisp Japanese comfort-food plate.`;
  if (dish.includes("doner")) return `${place} is useful for a quick Mediterranean-style meal that still feels specific.`;
  if (dish.includes("pizza")) return `${place} is useful when pizza is the whole plan, not a fallback.`;
  if (dish.includes("pancake") || dish.includes("benedict")) return `${place} is useful for a brunch-leaning meal or cafe-grill comfort food.`;
  if (dish.includes("crab") || dish.includes("seafood")) return `${place} is useful when you want a bigger, messier seafood dinner with spice.`;
  if (dish.includes("bbq") || dish.includes("soondubu")) return `${place} is useful for Korean comfort food or a table built around sharing.`;
  if (dish.includes("coffee") || dish.includes("matcha")) return `${place} is useful for a cafe stop that can stretch beyond a quick drink.`;
  if (dish.includes("cake") || dish.includes("bakery") || dish.includes("dessert")) return `${place} is useful for a sweet stop that does not need a full dinner plan.`;
  if (dish.includes("wing")) return `${place} is useful for a casual group order built around wings.`;
  return `${place} is useful because the clearest signal is about what people may actually want to eat there.`;
}

function placeSummary(signal: Signal) {
  const explicit = conciseText(textEvidence(signal, "place_summary") || textEvidence(signal, "place_anchor_reason"), 150);
  if (explicit) {
    return explicit;
  }
  return fallbackPlaceSummary(signal);
}

function signalSummary(signal: Signal) {
  const changed = evidenceList(signal, "what_changed");
  const explicit = conciseText(changed[0] || textEvidence(signal, "what_to_notice") || textEvidence(signal, "reader_hook") || signal.summary, 150);
  if (explicit) {
    return explicit;
  }
  return `${cleanPlaceName(signal.place.name)} has a current food signal in the ${readerCategory(signal).toLowerCase()} lane.`;
}

function categoryForSignal(signal: Signal) {
  const displayCategory = textEvidence(signal, "display_category");
  if (displayCategory) {
    const configured = FOOD_CATEGORIES.find((category) => category.label.toLowerCase() === displayCategory.toLowerCase() || category.key === categoryKeyForLabel(displayCategory));
    if (configured) {
      return configured;
    }
  }

  const cuisine = cuisineType(signal);
  const cuisineCategory = categoryFromCuisine(cuisine) || categoryFromCuisine(textEvidence(signal, "food_or_cuisine_type"));
  if (cuisineCategory) {
    return cuisineCategory;
  }

  const haystack = [
    signal.place.name,
    signal.place.category,
    signal.title,
    signal.summary,
    cuisine,
    textEvidence(signal, "food_or_cuisine_type"),
    textEvidence(signal, "reader_hook"),
    textEvidence(signal, "what_to_notice"),
    ...(signal.evidence.keywords ?? [])
  ].join(" ").toLowerCase();

  return CATEGORY_MATCH_ORDER.map(categoryByKey).find((category) => hasFoodTerm(haystack, category.terms)) ?? dinnerCategory();
}

function readerCategory(signal: Signal) {
  return categoryForSignal(signal).label;
}

function categoryDescription(label: string, count: number) {
  const suffix = `${count} card${count === 1 ? "" : "s"} to open when that sounds like the night you want.`;
  const category = FOOD_CATEGORIES.find((candidate) => candidate.label === label);
  return `${category?.description ?? "A few local food cards in this lane."} ${suffix}`;
}

function categoryWhy(label: string, signal: Signal) {
  const dish = signatureDish(signal);
  if (label === "Cafe") return `${dish} is worth a look when you want something slower than a grab-and-go coffee.`;
  if (label === "Night stay") return `${dish} is worth a look when the plan is to linger after dinner.`;
  if (label === "Korean") return `${dish} is worth a look for comfort food, sharing, or a group table.`;
  if (label === "Seafood") return `${dish} is worth a look when spice and a bigger dinner are the point.`;
  if (label === "Dessert") return `${dish} is worth a look for an easy sweet stop.`;
  if (label === "Dinner") return `${dish} is worth a look if you are okay planning around a slower meal.`;
  if (label === "Japanese") return `${dish} is worth a look when you want a focused comfort-food plate.`;
  if (label === "Mediterranean") return `${dish} is worth a look for a quick meal with a specific craving attached.`;
  if (label === "Pizza") return `${dish} is worth a look when pizza is the plan.`;
  if (label === "Brunch") return `${dish} is worth a look for a brunch-leaning stop.`;
  return `${dish} is worth a look because it is the clearest food-specific signal here.`;
}

function placeArea(signal: Signal) {
  const neighborhood = signal.place.neighborhood?.trim();
  if (neighborhood && neighborhood !== signal.city) {
    return `${neighborhood}, ${signal.city}`;
  }
  return signal.city;
}

function dinnerCategory() {
  return FOOD_CATEGORIES.find((category) => category.key === "dinner") ?? FOOD_CATEGORIES[FOOD_CATEGORIES.length - 1];
}

function categoryByKey(key: FoodCategoryKey) {
  return FOOD_CATEGORIES.find((category) => category.key === key) ?? dinnerCategory();
}

function categoryFromCuisine(value: string) {
  const cuisine = value.toLowerCase();
  if (!cuisine || isGenericFoodLabel(cuisine)) {
    return null;
  }
  if (cuisine.includes("korean")) return categoryByKey("korean");
  if (cuisine.includes("japanese")) return categoryByKey("japanese");
  if (cuisine.includes("seafood") || cuisine.includes("cajun")) return categoryByKey("seafood");
  if (cuisine.includes("pizza")) return categoryByKey("pizza");
  if (cuisine.includes("cafe") || cuisine.includes("coffee")) return categoryByKey("cafe");
  if (cuisine.includes("mediterranean") || cuisine.includes("turkish")) return categoryByKey("mediterranean");
  return null;
}

function dishFromText(value: string) {
  const text = value.toLowerCase();
  const dishes: Array<[string, string[]]> = [
    ["Crab boil", ["crab boil", "crab", "seafood boil"]],
    ["Korean BBQ", ["korean bbq", "bbq", "all you can eat"]],
    ["Donkatsu", ["donkatsu", "tonkatsu"]],
    ["Doner", ["doner", "döner"]],
    ["Pizza", ["pizza"]],
    ["Pancakes", ["pancake", "pancakes"]],
    ["Eggs benedict", ["benedict"]],
    ["Coffee", ["coffee", "espresso", "latte"]],
    ["Matcha", ["matcha"]]
  ];
  return dishes.find(([, terms]) => terms.some((term) => text.includes(term)))?.[0] ?? "";
}

function normalizeFoodCue(value: string, categoryKey: FoodCategoryKey) {
  const cue = conciseText(value, 34);
  const lowerCue = cue.toLowerCase();
  if (!cue || isGenericFoodLabel(lowerCue)) {
    return "";
  }
  if (lowerCue.includes("korean bbq") || lowerCue === "bbq" || lowerCue.includes("all you can eat")) return "Korean BBQ";
  if (lowerCue.includes("korean restaurant") || lowerCue === "korean") return "Korean food";
  if (lowerCue.includes("japanese restaurant") || lowerCue === "japanese") return "Japanese comfort food";
  if (lowerCue.includes("seafood restaurant") || lowerCue === "seafood") return "Seafood dinner";
  if (lowerCue.includes("mediterranean restaurant") || lowerCue === "mediterranean") return "Mediterranean food";
  if (lowerCue.includes("cafe") || lowerCue === "coffee shop") return "Cafe stop";
  if (lowerCue === "night stay" || lowerCue === "late night") return "Late dinner";
  if (lowerCue === "dinner") return "Dinner plan";
  if (lowerCue.endsWith(" restaurant")) return fallbackCueForCategory(categoryKey);
  return cue;
}

function fallbackCueForCategory(categoryKey: FoodCategoryKey) {
  const cues: Record<FoodCategoryKey, string> = {
    korean: "Korean food",
    japanese: "Japanese comfort food",
    seafood: "Seafood dinner",
    mediterranean: "Mediterranean food",
    pizza: "Pizza",
    cafe: "Cafe stop",
    brunch: "Brunch plan",
    dinner: "Dinner plan",
    "night-stay": "Late dinner"
  };
  return cues[categoryKey];
}

function evidenceList(signal: Signal, key: string) {
  const value = signal.evidence[key];
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  }
  return [];
}

function conciseText(value: string, maxLength: number) {
  const cleaned = value.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ").replace(/\s+/g, " ").trim();
  if (!cleaned) {
    return "";
  }
  if (cleaned.length <= maxLength) {
    return cleaned;
  }
  return `${cleaned.slice(0, maxLength - 1).trim()}...`;
}

function isGenericFoodLabel(value: string) {
  return ["restaurant", "food", "local food signal", "cuisine"].includes(value.trim().toLowerCase());
}

function hasFoodTerm(text: string, terms: string[]) {
  return terms.some((term) => new RegExp(`(^|[^a-z0-9])${escapeRegExp(term)}([^a-z0-9]|$)`, "i").test(text));
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function categoryKeyForLabel(label: string) {
  const key = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return key || "dinner";
}

function scopeSummary(report: Report) {
  return `A quick food-first read for ${report.region}: what kind of meal is worth considering, what to order, and which cards to open for details.`;
}

function cleanPlaceName(value: string) {
  return value
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
    .replace(/\s*\|.*$/, "")
    .replace(/\s*-\s*Cajun Seafood.*$/i, "")
    .replace(/\s+Nj\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

function naturalJoin(values: string[]) {
  const cleaned = values.filter(Boolean);
  if (cleaned.length <= 1) {
    return cleaned[0] || "";
  }
  if (cleaned.length === 2) {
    return `${cleaned[0]} and ${cleaned[1]}`;
  }
  return `${cleaned.slice(0, -1).join(", ")}, and ${cleaned[cleaned.length - 1]}`;
}

function sourceLineFor(signal: Signal) {
  const mentions = mentionCountFor(signal);
  const sourceCount = Math.max(sourceCountFor(signal), 1);
  const notes = evidenceNotes(signal);
  const category = readerCategory(signal);
  const sourceText = sourceCount > 1 ? "a few local source paths" : "one local source path";
  const note = notes[0] ? ` ${notes[0]}` : "";
  const weight = mentions && mentions > 1 ? "More than one local note points this way." : "This is a light read, so open the card for context.";
  return `${weight} It sits in ${category.toLowerCase()} and comes from ${sourceText}.${note}`.trim();
}

function textEvidence(signal: Signal, key: string) {
  const value = signal.evidence[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC"
  }).format(new Date(value));
}
