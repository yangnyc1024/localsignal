import type { Report, Signal } from "@/lib/types";
import { bestReadAs, evidenceNotes, mentionCountFor, phenomenonTitle, placeIdentity, readerSummary, sourceCountFor } from "@/lib/signalStory";

export type LocalBriefing = {
  eyebrow: string;
  title: string;
  subtitle: string;
  whyItMatters: string;
  places: BriefingPlace[];
  supportingReads: MiniRead[];
  sources: BriefingSource[];
};

export type BriefingPlace = {
  name: string;
  area: string;
  category: string;
  href: string;
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
  const sortedSignals = [...report.signals].sort((left, right) => right.score - left.score);
  const main = sortedSignals[0];
  const supporting = sortedSignals.slice(1, 4);

  if (!main) {
    return {
      eyebrow: `Week of ${formatDate(report.week_start)}`,
      title: "Nothing clear is changing this week",
      subtitle: "The local read is quiet, which is sometimes the most useful answer.",
      whyItMatters: "LocalSignal is holding back rather than turning thin evidence into a story.",
      places: [],
      supportingReads: [],
      sources: []
    };
  }

  const mainIdentity = placeIdentity(main);
  const supportingPlaces = supporting.map(placeForSignal);
  const places = [placeForSignal(main), ...supportingPlaces].filter(uniquePlace);

  return {
    eyebrow: `${formatDate(report.week_start)} · ${report.region}`,
    title: titleFor(main),
    subtitle: subtitleFor(main, supporting),
    whyItMatters: whyItMattersFor(main),
    places,
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

function titleFor(signal: Signal) {
  const backendTitle = textEvidence(signal, "briefing_title");
  if (backendTitle) {
    return backendTitle;
  }
  return phenomenonTitle(signal);
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
    name: identity.name,
    area: identity.area,
    category: identity.cuisine,
    href: `/signal/${signal.slug}`
  };
}

function sourceLineFor(signal: Signal, fallbackCategory: string) {
  const mentions = mentionCountFor(signal);
  const sourceCount = Math.max(sourceCountFor(signal), 1);
  const notes = evidenceNotes(signal);
  const category = placeIdentity(signal).cuisine || fallbackCategory;
  const mentionText = mentions ? `${mentions} recent mention${mentions === 1 ? "" : "s"}` : "recent local evidence";
  return `${mentionText}, ${sourceCount} source type${sourceCount === 1 ? "" : "s"}, ${category.toLowerCase()}. ${notes[0] ?? ""}`.trim();
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
