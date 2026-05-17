"use client";

import { Search, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import { SignalCard } from "@/components/SignalCard";
import type { Signal } from "@/lib/types";
import { sourceCountFor } from "@/lib/signalStory";

type Props = {
  signals: Signal[];
};

const filters = [
  "All",
  "Worth going",
  "Keep an eye on",
  "Bakeries",
  "Cafes",
  "Desserts",
  "Korean Food",
  "Moving Fast",
  "Late Night",
  "Menu Buzz"
] as const;

type Filter = (typeof filters)[number];

export function SignalFeed({ signals }: Props) {
  const [activeFilter, setActiveFilter] = useState<Filter>("All");
  const [confidenceFilter, setConfidenceFilter] = useState<"All" | "High" | "Medium" | "Low">("All");

  const filteredSignals = useMemo(() => {
    return signals.filter((signal) => matchesFilter(signal, activeFilter) && (confidenceFilter === "All" || signal.confidence === confidenceFilter));
  }, [activeFilter, confidenceFilter, signals]);

  const rankedSignals = useMemo(() => new Map(signals.map((signal, index) => [signal.id, index + 1])), [signals]);

  const sortedSignals = useMemo(() => [...filteredSignals].sort((left, right) => priorityFor(right) - priorityFor(left)), [filteredSignals]);

  return (
    <section className="grid gap-5">
      <div className="rounded-lg border border-line bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <SlidersHorizontal size={16} className="text-moss" />
              Find a place to check
            </div>
            <p className="mt-1 text-sm leading-6 text-ink/62">Pick a lane, then open the cards that feel worth your time.</p>
          </div>

          <div className="flex flex-wrap gap-2">
            {(["All", "High", "Medium", "Low"] as const).map((confidence) => (
              <button
                key={confidence}
                type="button"
                onClick={() => setConfidenceFilter(confidence)}
                className={
                  confidenceFilter === confidence
                    ? "inline-flex items-center gap-1.5 rounded-md border border-moss bg-moss px-3 py-1.5 text-sm font-semibold text-white"
                    : "inline-flex items-center gap-1.5 rounded-md border border-line bg-paper px-3 py-1.5 text-sm font-semibold text-ink/70 transition hover:border-moss hover:text-moss"
                }
              >
                <ShieldCheck size={14} />
                {confidence === "All" ? "Any read" : confidence === "High" ? "Feels solid" : confidence === "Medium" ? "Still forming" : "Light clue"}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {filters.map((filter) => (
            <button
              key={filter}
              type="button"
              onClick={() => setActiveFilter(filter)}
              className={
                activeFilter === filter
                  ? "rounded-md border border-moss bg-moss px-3 py-1.5 text-sm font-semibold text-white"
                  : "rounded-md border border-line bg-white px-3 py-1.5 text-sm font-semibold text-ink/70 transition hover:border-moss hover:text-moss"
              }
            >
              {filter} <span className="ml-1 opacity-70">{signals.filter((signal) => matchesFilter(signal, filter)).length}</span>
            </button>
          ))}
        </div>
      </div>

      {sortedSignals.length ? (
        <div className="grid gap-3">
          <div className="flex flex-col gap-2 border-b border-line pb-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-ink">Places worth a closer look</h2>
              <p className="mt-1 text-sm leading-6 text-ink/62">
                The strongest reads float up first. Skim the right side when you want to know why it made the list.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs font-semibold text-ink/55">
              <span className="rounded-md bg-white px-2 py-1">{sortedSignals.length} visible</span>
              <span className="rounded-md bg-white px-2 py-1">{sortedSignals.reduce((sum, signal) => sum + Math.max(sourceCountFor(signal), 1), 0)} supporting clues</span>
            </div>
          </div>
          {sortedSignals.map((signal) => (
            <SignalCard key={signal.id} signal={signal} rank={rankedSignals.get(signal.id) ?? 0} />
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-line bg-white p-6 text-sm leading-6 text-ink/70">
          <div className="mb-2 flex items-center gap-2 font-semibold text-ink">
            <Search size={16} className="text-moss" />
            Nothing here right now
          </div>
          Try a wider read or switch back to All. Quiet lanes stay quiet until something real shows up.
        </div>
      )}
    </section>
  );
}

function priorityFor(signal: Signal) {
  const strengthScore = signal.signal_strength === "Strong signal" ? 200 : signal.signal_strength === "Watching" ? 100 : 0;
  const confidenceScore = signal.confidence === "High" ? 30 : signal.confidence === "Medium" ? 15 : 0;
  return strengthScore + confidenceScore + signal.score;
}

function matchesFilter(signal: Signal, filter: Filter) {
  if (filter === "All") {
    return true;
  }
  if (filter === "Worth going") {
    return signal.signal_strength === "Strong signal";
  }
  if (filter === "Keep an eye on") {
    return signal.signal_strength === "Watching";
  }

  const category = signal.place.category.toLowerCase();
  const text = `${signal.signal_type} ${signal.title} ${signal.summary} ${(signal.evidence.keywords ?? []).join(" ")}`.toLowerCase();

  if (filter === "Bakeries") {
    return category.includes("bakery") || text.includes("bakery");
  }
  if (filter === "Cafes") {
    return category.includes("cafe") || text.includes("coffee") || text.includes("remote");
  }
  if (filter === "Desserts") {
    return category.includes("dessert") || text.includes("dessert") || text.includes("sweet");
  }
  if (filter === "Korean Food") {
    return category.includes("korean") || text.includes("tofu") || text.includes("korean") || text.includes("banchan");
  }
  if (filter === "Moving Fast") {
    return signal.signal_type === "review_velocity_spike" || signal.score >= 80;
  }
  if (filter === "Late Night") {
    return text.includes("late night") || text.includes("late-night") || text.includes("after 9") || text.includes("night");
  }
  if (filter === "Menu Buzz") {
    return signal.signal_type === "keyword_spike" || text.includes("menu") || text.includes("dish") || text.includes("dessert") || text.includes("viral");
  }

  return true;
}
