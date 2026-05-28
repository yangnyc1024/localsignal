"use client";

import {
  ArrowUpRight,
  Beef,
  Coffee,
  Croissant,
  Fish,
  Moon,
  Pizza,
  Salad,
  Soup,
  Sparkles,
  Utensils
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import type { BriefingSignalCard, CategorySignalSection, FoodCategoryKey } from "@/lib/briefing";

type FilterOption = {
  key: string;
  label: string;
  count: number;
};

type Props = {
  sections: CategorySignalSection[];
  allCards: BriefingSignalCard[];
  availableFilters: FilterOption[];
};

function iconForFilter(key: string) {
  const icons: Record<FoodCategoryKey | "all", typeof Sparkles> = {
    all: Sparkles,
    korean: Beef,
    japanese: Soup,
    seafood: Fish,
    mediterranean: Salad,
    pizza: Pizza,
    cafe: Coffee,
    brunch: Croissant,
    dinner: Utensils,
    "night-stay": Moon
  };
  return icons[key as FoodCategoryKey | "all"] ?? Sparkles;
}

export function CategoryFilterSection({ sections, allCards, availableFilters }: Props) {
  const [activeFilter, setActiveFilter] = useState("all");
  const activeSection = sections.find((section) => section.key === activeFilter);
  const filteredCards = activeFilter === "all" ? allCards : allCards.filter((card) => card.categoryKey === activeFilter);

  return (
    <section className="grid gap-4 border-t border-line pt-7">
      <div className="grid gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink/72">
          <Utensils size={16} className="text-moss" />
          Browse by craving or occasion
        </div>
        <div className="flex flex-wrap gap-2 md:max-w-4xl">
          {availableFilters.map((filter) => {
            const isActive = activeFilter === filter.key;
            const Icon = iconForFilter(filter.key);
            return (
              <button
                key={filter.key}
                type="button"
                disabled={filter.count === 0}
                onClick={() => setActiveFilter(filter.key)}
                className={`inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35 ${
                  isActive ? "border-moss bg-moss text-white" : "border-line bg-white text-ink/68 hover:border-moss/45 hover:text-ink"
                } disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink/68`}
              >
                <Icon size={15} />
                {filter.label}
              </button>
            );
          })}
        </div>
        <p className="max-w-2xl text-sm leading-6 text-ink/60">
          {activeSection?.description ?? "Pick a food lane, then open the card with the dish or occasion that matches."}
        </p>
      </div>
      <div className="grid gap-3">
        {filteredCards.map((card) => (
          <Link
            key={`${activeFilter}-${card.href}`}
            href={card.href}
            className="group grid min-w-0 gap-3 rounded-lg border border-line bg-white p-4 shadow-sm transition hover:border-moss/45 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35 md:p-5"
          >
            <div className="flex min-w-0 items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="break-words text-xs font-semibold uppercase text-moss">{card.category}</div>
                <h3 className="mt-2 break-words text-xl font-semibold leading-7 text-ink group-hover:text-moss">{card.place}</h3>
              </div>
              <ArrowUpRight size={16} className="mt-1 shrink-0 text-moss" />
            </div>
            <div className="rounded-md bg-paper/80 p-3">
              <div className="text-xs font-semibold uppercase text-ink/48">Food cue</div>
              <div className="mt-1 break-words text-base font-semibold leading-6 text-ink">{card.signatureDish}</div>
            </div>
            <div className="grid gap-2 text-[15px] leading-7 text-ink/66">
              <p>
                <span className="font-semibold text-ink/80">About this place: </span>
                {card.placeSummary}
              </p>
              <p>
                <span className="font-semibold text-ink/80">Why now: </span>
                {card.signalSummary}
              </p>
            </div>
            <div className="flex min-w-0 items-center justify-between gap-3 text-sm text-ink/56">
              <span className="min-w-0 break-words">{card.area}</span>
              <span className="shrink-0 font-semibold text-moss">Details</span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
