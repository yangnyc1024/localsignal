import type { BriefingPayload, Report, Signal } from "@/lib/types";
import { bestReadAs, cuisineType, evidenceNotes, mentionCountFor, phenomenonTitle, placeIdentity, readerSummary, sourceCountFor } from "@/lib/signalStory";

export type LocalBriefing = {
  eyebrow: string;
  scopeTitle: string;
  scopeSummary: string;
  title: string;
  subtitle: string;
  whyItMatters: string;
  places: BriefingPlace[];
  topSignals: ReaderSignalCard[];
  categorySections: CategorySignalSection[];
  supportingReads: MiniRead[];
  sources: BriefingSource[];
};

export type BriefingPlace = {
  name: string;
  area: string;
  category: string;
  reason: string;
  href: string;
};

export type ReaderSignalCard = {
  title: string;
  place: string;
  area: string;
  category: string;
  pull: string;
  goodFor: string;
  changed: string;
  summary: string;
  href: string;
};

export type CategorySignalSection = {
  label: string;
  description: string;
  cards: ReaderSignalCard[];
};

export type MiniRead = {
  title: string;
  summary: string;
  href: string;
  place: string;
};

export type BriefingSource = {
  label: string;
  detail: string;
  href: string;
};

export function buildLocalBriefing(report: Report): LocalBriefing {
  const llmBriefing = fromBackendBriefing(report);
  if (llmBriefing) {
    return llmBriefing;
  }

  const sortedSignals = [...report.signals].sort((left, right) => right.score - left.score);
  const main = sortedSignals[0];
  const supporting = sortedSignals.slice(1, 4);

  if (!main) {
    return {
      eyebrow: `Week of ${formatDate(report.week_start)}`,
      title: "Nothing clear is changing this week",
      scopeTitle: "This is a weekly local food briefing",
      scopeSummary: scopeSummary(report),
      subtitle: "The local read is quiet, which is sometimes the most useful answer.",
      whyItMatters: "LocalSignal is holding back rather than turning thin evidence into a story.",
      places: [],
      topSignals: [],
      categorySections: [],
      supportingReads: [],
      sources: []
    };
  }

  const mainIdentity = placeIdentity(main);
  const supportingPlaces = supporting.map(placeForSignal);
  const places = [placeForSignal(main), ...supportingPlaces].filter(uniquePlace);

  return {
    eyebrow: `${formatDate(report.week_start)} · ${report.region}`,
    scopeTitle: "This is a weekly local food briefing",
    scopeSummary: scopeSummary(report),
    title: weeklyReaderTitle(report),
    subtitle: weeklyReaderSubtitle(report),
    whyItMatters: weeklyReaderWhy(report),
    places,
    topSignals: sortedSignals.slice(0, 3).map(signalCardFor),
    categorySections: categorySectionsFor(sortedSignals),
    supportingReads: supporting.map((signal) => ({
      title: phenomenonTitle(signal),
      summary: oneSentence(readerSummary(signal)),
      href: `/signal/${signal.slug}`,
      place: `${signal.place.name} · ${signal.place.neighborhood ?? signal.city}`
    })),
    sources: sortedSignals.slice(0, 6).map((signal) => ({
      label: signal.place.name,
      detail: sourceLineFor(signal, mainIdentity.cuisine),
      href: `/signal/${signal.slug}`
    }))
  };
}

function fromBackendBriefing(report: Report): LocalBriefing | null {
  const payload = report.briefing;
  if (!isUsableBriefing(payload)) {
    return null;
  }

  return {
    eyebrow: `${formatDate(report.week_start)} · ${report.region}`,
    scopeTitle: "This is a weekly local food briefing",
    scopeSummary: scopeSummary(report),
    title: weeklyReaderTitle(report),
    subtitle: weeklyReaderSubtitle(report),
    whyItMatters: weeklyReaderWhy(report),
    places: (payload.places_involved ?? []).slice(0, 3).map((place) => ({
      name: cleanPlaceName(place.name),
      area: place.area,
      category: place.category,
      reason: place.reason,
      href: `/signal/${place.signal_slug}`
    })),
    topSignals: topSignalsFor(report),
    categorySections: categorySectionsFor([...report.signals].sort((left, right) => right.score - left.score)),
    supportingReads: (payload.supporting_reads ?? []).slice(0, 3).map((read) => ({
      title: read.title,
      summary: read.summary,
      href: `/signal/${read.signal_slug}`,
      place: placeLabelForSlug(report, read.signal_slug)
    })),
    sources: (payload.sources ?? []).slice(0, 6).map((source) => {
      const signal = report.signals.find((candidate) => candidate.slug === source.signal_slug);
      return {
        label: signal ? cleanPlaceName(signal.place.name) : source.label,
        detail: signal ? sourceLineFor(signal, readerCategory(signal)) : source.detail,
        href: `/signal/${source.signal_slug}`
      };
    })
  };
}

function isUsableBriefing(payload: BriefingPayload | null | undefined): payload is Required<Pick<BriefingPayload, "title" | "subtitle" | "why_it_matters">> & BriefingPayload {
  return Boolean(payload?.title && payload.subtitle && payload.why_it_matters);
}

function placeLabelForSlug(report: Report, slug: string) {
  const signal = report.signals.find((candidate) => candidate.slug === slug);
  if (!signal) {
    return "Local read";
  }
  return `${cleanPlaceName(signal.place.name)} · ${signal.place.neighborhood ?? signal.city}`;
}

function titleFor(signal: Signal) {
  const backendTitle = textEvidence(signal, "briefing_title");
  if (backendTitle) {
    return backendTitle;
  }
  return phenomenonTitle(signal);
}

function weeklyReaderTitle(report: Report) {
  const top = topSignalsFor(report);
  if (!top.length) {
    return report.briefing?.title || report.title;
  }
  const categories = [...new Set(top.map((signal) => signal.category))];
  if (categories.includes("Spicy seafood") && categories.includes("Korean BBQ & tofu")) {
    return "Spicy seafood and Korean group dinners are the clearest reads this week";
  }
  if (categories.includes("Coffee / work-friendly cafes")) {
    return "Coffee, wifi, and longer sit-down visits are easier to notice this week";
  }
  if (categories.includes("Dinner waits")) {
    return "Some dinner plans may need a little more patience this week";
  }
  return `${top[0].pull} is the clearest local food pull this week`;
}

function weeklyReaderSubtitle(report: Report) {
  const top = topSignalsFor(report);
  if (!top.length) {
    return report.briefing?.subtitle || report.intro;
  }
  const placeText = naturalJoin(top.map((signal) => signal.place));
  const pulls = naturalJoin([...new Set(top.map((signal) => signal.pull))].slice(0, 3));
  return `Start with ${placeText}: the useful read is ${pulls}.`;
}

function weeklyReaderWhy(report: Report) {
  const top = topSignalsFor(report);
  if (!top.length) {
    return report.briefing?.why_it_matters || "Open a card when you want the evidence behind the read.";
  }
  return `This is useful when you are choosing where to eat nearby: it turns this week's local food talk into a few concrete cravings, visit occasions, and places to open for details.`;
}

function subtitleFor(main: Signal, supporting: Signal[]) {
  const backendSubtitle = textEvidence(main, "briefing_subtitle");
  if (backendSubtitle) {
    return backendSubtitle;
  }

  const places = [main, ...supporting].slice(0, 3).map((signal) => signal.place.name);
  const placeText = places.length > 1 ? `${places.slice(0, -1).join(", ")} and ${places[places.length - 1]}` : places[0];
  return `${readerSummary(main)} The places making it worth a closer look include ${placeText}.`;
}

function whyItMattersFor(signal: Signal) {
  const backendWhy = textEvidence(signal, "why_this_matters");
  if (backendWhy) {
    return backendWhy;
  }
  return bestReadAs(signal);
}

function placeForSignal(signal: Signal): BriefingPlace {
  const identity = placeIdentity(signal);
  return {
    name: cleanPlaceName(identity.name),
    area: identity.area,
    category: identity.cuisine,
    reason: signalPull(signal),
    href: `/signal/${signal.slug}`
  };
}

function topSignalsFor(report: Report) {
  return [...report.signals].sort((left, right) => right.score - left.score).slice(0, 3).map(signalCardFor);
}

function categorySectionsFor(signals: Signal[]) {
  const groups = new Map<string, ReaderSignalCard[]>();
  for (const signal of signals) {
    const label = readerCategory(signal);
    const existing = groups.get(label) ?? [];
    if (existing.length < 3) {
      existing.push(signalCardFor(signal));
      groups.set(label, existing);
    }
  }
  return [...groups.entries()]
    .filter(([, cards]) => cards.length > 0)
    .slice(0, 5)
    .map(([label, cards]) => ({
      label,
      description: categoryDescription(label, cards.length),
      cards
    }));
}

function signalCardFor(signal: Signal): ReaderSignalCard {
  const identity = placeIdentity(signal);
  return {
    title: readerTitle(signal),
    place: cleanPlaceName(identity.name),
    area: identity.area,
    category: readerCategory(signal),
    pull: signalPull(signal),
    goodFor: goodFor(signal),
    changed: whatChanged(signal),
    summary: plainReaderSummary(signal),
    href: `/signal/${signal.slug}`
  };
}

function readerTitle(signal: Signal) {
  const category = readerCategory(signal).toLowerCase();
  const place = cleanPlaceName(signal.place.name);
  const pull = signalPull(signal).toLowerCase();
  if (pull.includes("wait")) return `${place} may need a slower dinner mindset`;
  if (pull.includes("coffee") || pull.includes("cafe")) return `${place} is showing more weekday cafe energy`;
  if (pull.includes("seafood") || pull.includes("crab")) return `${place} is getting more seafood dinner talk`;
  if (pull.includes("bbq") || pull.includes("korean")) return `${place} is showing more Korean group-dinner energy`;
  return `${place} is standing out in ${category}`;
}

function signalPull(signal: Signal) {
  const keywords = (signal.evidence.keywords ?? []).map((keyword) => keyword.toLowerCase());
  const nameText = signal.place.name.toLowerCase();
  const titleText = `${signal.title} ${signal.summary}`.toLowerCase();
  const haystack = `${nameText} ${titleText} ${keywords.join(" ")}`;

  if (haystack.includes("wing")) return "chicken wings and group-dinner energy";
  if (haystack.includes("crab") || haystack.includes("seafood") || haystack.includes("boil")) return "crab boil, spicy seafood, and group dinner";
  if (haystack.includes("bbq") || haystack.includes("korean")) return "Korean BBQ, tofu, and group meals";
  if (haystack.includes("coffee") || haystack.includes("cafe") || haystack.includes("wifi")) return "coffee, wifi, and longer sit-down visits";
  if (haystack.includes("wait") || haystack.includes("line")) return "waits, lines, and slower dinner pacing";
  if (haystack.includes("tofu")) return "tofu, Korean comfort food, and dinner traffic";
  if (haystack.includes("dessert") || haystack.includes("cake") || haystack.includes("bakery")) return "dessert and casual sweet stops";
  return `${readerCategory(signal).toLowerCase()} food pull`;
}

function plainReaderSummary(signal: Signal) {
  const place = cleanPlaceName(signal.place.name);
  return `${place} is showing more local talk around ${signalPull(signal)}.`;
}

function goodFor(signal: Signal) {
  const pull = signalPull(signal).toLowerCase();
  if (pull.includes("crab") || pull.includes("seafood")) return "a group dinner when you want bold seafood instead of a quick bite";
  if (pull.includes("bbq") || pull.includes("tofu") || pull.includes("korean")) return "a Korean food night, especially if you are choosing for a group";
  if (pull.includes("coffee") || pull.includes("wifi")) return "a longer cafe stop, laptop time, or a calmer weekday meet-up";
  if (pull.includes("wait") || pull.includes("line")) return "a slower dinner plan where waiting a bit would not ruin the night";
  if (pull.includes("dessert")) return "an after-dinner stop or a low-commitment sweet craving";
  return "deciding what nearby food lane feels more alive this week";
}

function whatChanged(signal: Signal) {
  const pull = signalPull(signal).toLowerCase();
  const place = cleanPlaceName(signal.place.name);
  if (pull.includes("crab") || pull.includes("seafood")) return `${place} has more local talk around crab boil, spice, and seafood dinners.`;
  if (pull.includes("bbq") || pull.includes("korean")) return `${place} has more local talk around Korean food and group-meal occasions.`;
  if (pull.includes("coffee") || pull.includes("wifi")) return `${place} has more local talk around quiet cafe use and longer stays.`;
  if (pull.includes("wait") || pull.includes("line")) return `${place} has more local talk around waits, lines, and dinner pacing.`;
  if (pull.includes("dessert")) return `${place} has more local talk around sweet stops and casual visits.`;
  return `${place} has a small shift in how locals describe the visit.`;
}

function readerCategory(signal: Signal) {
  const cuisine = cuisineType(signal);
  const haystack = `${signal.place.name} ${signal.title} ${signal.summary} ${(signal.evidence.keywords ?? []).join(" ")}`.toLowerCase();
  if (haystack.includes("coffee") || haystack.includes("cafe") || cuisine.toLowerCase().includes("cafe")) return "Coffee / work-friendly cafes";
  if (haystack.includes("bbq") || haystack.includes("tofu") || haystack.includes("korean") || cuisine.toLowerCase().includes("korean")) return "Korean BBQ & tofu";
  if (haystack.includes("seafood") || haystack.includes("crab") || haystack.includes("boil")) return "Spicy seafood";
  if (haystack.includes("dessert") || haystack.includes("bakery") || haystack.includes("cake")) return "Dessert stops";
  if (haystack.includes("wait") || haystack.includes("line")) return "Dinner waits";
  return cuisine || "Food";
}

function categoryDescription(label: string, count: number) {
  const suffix = `${count} card${count === 1 ? "" : "s"} to open when that sounds like the night you want.`;
  if (label === "Coffee / work-friendly cafes") return `Coffee, wifi, quieter weekdays, and longer sit-down visits. ${suffix}`;
  if (label === "Korean BBQ & tofu") return `BBQ, tofu, group meals, and Korean comfort-food nights. ${suffix}`;
  if (label === "Spicy seafood") return `Crab boil, seafood, spice, and bigger dinner flavors. ${suffix}`;
  if (label === "Dessert stops") return `Sweet stops, bakery runs, and casual after-meal visits. ${suffix}`;
  if (label === "Dinner waits") return `Waits, lines, and slower dinner expectations. ${suffix}`;
  return `A few local food cards in this lane. ${suffix}`;
}

function scopeSummary(report: Report) {
  return `LocalSignal reads recent local food talk for ${report.region} and turns it into a weekly briefing: what people may want to eat, which places are involved, and which cards are worth opening for details.`;
}

function cleanPlaceName(value: string) {
  return value
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

function sourceLineFor(signal: Signal, fallbackCategory: string) {
  const mentions = mentionCountFor(signal);
  const sourceCount = Math.max(sourceCountFor(signal), 1);
  const notes = evidenceNotes(signal);
  const category = placeIdentity(signal).cuisine || fallbackCategory;
  const sourceText = sourceCount > 1 ? "a few local source paths" : "one local source path";
  const note = notes[0] ? ` ${notes[0]}` : "";
  const weight = mentions && mentions > 1 ? "More than one local note points this way." : "This is a light read, so open the card for context.";
  return `${weight} It sits in ${category.toLowerCase()} and comes from ${sourceText}.${note}`.trim();
}

function textEvidence(signal: Signal, key: string) {
  const value = signal.evidence[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function uniquePlace(place: BriefingPlace, index: number, places: BriefingPlace[]) {
  return places.findIndex((candidate) => candidate.name === place.name && candidate.area === place.area) === index;
}

function oneSentence(value: string) {
  const first = value.split(/(?<=[.!?])\s+/)[0];
  return first || value;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric"
  }).format(new Date(value));
}
