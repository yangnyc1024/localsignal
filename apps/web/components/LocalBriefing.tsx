import {
  ArrowUpRight,
  CalendarDays,
  Newspaper,
  Sparkles,
  Star
} from "lucide-react";
import Link from "next/link";

import type { Report } from "@/lib/types";
import { FOOD_CATEGORIES, buildLocalBriefing } from "@/lib/briefing";
import { CategoryFilterSection } from "@/components/CategoryFilterSection";
import { SubscribeForm } from "@/components/SubscribeForm";

type Props = {
  report: Report;
};

export function LocalBriefing({ report }: Props) {
  const briefing = buildLocalBriefing(report);
  const allCards = briefing.categorySections.flatMap((section) => section.cards);
  const counts = new Map(briefing.categorySections.map((section) => [section.key, section.cards.length]));
  const availableFilters = [
    { key: "all", label: "All", count: allCards.length },
    ...FOOD_CATEGORIES.map((category) => ({
      key: category.key,
      label: category.label,
      count: counts.get(category.key) ?? 0
    }))
  ];

  return (
    <article className="mx-auto grid w-full max-w-[1440px] gap-8 px-4 py-7 md:px-6 md:py-10 lg:gap-10 lg:px-8 xl:px-10">
      <header className="grid gap-6 border-b border-line pb-8 lg:gap-8">
        {/* Top bar — full width */}
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-semibold text-moss">
          <Newspaper size={16} />
          LocalSignal
          <span className="h-1 w-1 rounded-full bg-ink/30" />
          <span className="inline-flex min-w-0 items-center gap-1 break-words text-ink/58">
            <CalendarDays size={15} />
            {briefing.eyebrow}
          </span>
        </div>

        {/* Two-column layout: AI narrative title left, food-reads card right */}
        <div className="grid gap-6 lg:grid-cols-[3fr_2fr] lg:items-start lg:gap-10">
          {/* Dynamic headline + subtitle */}
          <div className="grid min-w-0 gap-5">
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide text-ink/44">Food briefing</div>
              <h1 className="mt-3 break-words text-4xl font-semibold leading-tight text-ink md:text-[2.8rem] lg:text-[3.2rem]">
                {briefing.title}
              </h1>
              <p className="mt-4 text-lg leading-8 text-ink/70 lg:text-xl lg:leading-9">
                {briefing.subtitle}
              </p>
            </div>
            {briefing.whyItMatters ? (
              <p className="border-l-2 border-moss pl-4 text-base leading-7 text-ink/60">
                {briefing.whyItMatters}
              </p>
            ) : null}
          </div>

          {/* What to open — compact navigation card */}
          <section className="min-w-0 rounded-lg border border-line bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-moss">
              <Sparkles size={16} />
              What to open
            </div>
            {briefing.foodReads.length ? (
              <div className="mt-4 grid gap-2.5">
                {briefing.foodReads.map((read) => (
                  <Link
                    key={`${read.label}-${read.href}`}
                    href={read.href}
                    className="group grid gap-1 rounded-md border border-line bg-paper/75 p-3 transition hover:border-moss/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35"
                  >
                    <div className="flex min-w-0 items-center justify-between gap-3">
                      <span className="break-words text-sm font-semibold text-ink group-hover:text-moss">{read.label}</span>
                      <ArrowUpRight size={14} className="shrink-0 text-moss" />
                    </div>
                    <p className="text-xs leading-5 text-ink/62">{read.why}</p>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm leading-6 text-ink/60">{briefing.scopeSummary}</p>
            )}
          </section>
        </div>
      </header>

      {briefing.longTermSignals.length ? (
        <section className="grid gap-4">
          <div className="flex min-w-0 items-end justify-between gap-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink/72">
              <Star size={16} className="text-moss" />
              Longer-running signals
            </div>
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(132px,1fr))] gap-3 sm:grid-cols-[repeat(auto-fit,minmax(150px,1fr))]">
            {briefing.longTermSignals.map((signal) => (
              <Link
                key={`${signal.place}-${signal.href}`}
                href={signal.href}
                className="group flex aspect-square min-w-0 flex-col justify-between rounded-lg border border-line bg-white p-4 shadow-sm transition hover:border-moss/45 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35"
              >
                <div className="min-w-0">
                  <div className="break-words text-xs font-semibold uppercase leading-5 text-moss">{signal.category}</div>
                  <h2 className="mt-2 break-words text-lg font-semibold leading-6 text-ink group-hover:text-moss">{signal.place}</h2>
                </div>
                <div className="flex min-w-0 items-end justify-between gap-2">
                  <div className="min-w-0 break-words text-sm font-semibold leading-5 text-ink/68">{signal.signatureDish}</div>
                  <ArrowUpRight size={15} className="shrink-0 text-moss" />
                </div>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {briefing.categorySections.length ? (
        <CategoryFilterSection
          sections={briefing.categorySections}
          allCards={allCards}
          availableFilters={availableFilters}
        />
      ) : null}

      {briefing.sources.length ? (
        <details className="rounded-lg border border-line bg-white p-4 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-ink">Sources behind this read</summary>
          <div className="mt-4 grid gap-3">
            {briefing.sources.map((source) => (
              <Link key={`${source.label}-${source.href}`} href={source.href} className="group block min-w-0 rounded-md bg-paper p-3">
                <div className="flex min-w-0 items-center justify-between gap-3">
                  <div className="min-w-0 break-words text-sm font-semibold text-ink group-hover:text-moss">{source.label}</div>
                  <ArrowUpRight size={15} className="shrink-0 text-moss" />
                </div>
                <p className="mt-1 text-sm leading-5 text-ink/62">{source.detail}</p>
              </Link>
            ))}
          </div>
        </details>
      ) : null}

      <div className="grid gap-4 border-t border-line pt-7 md:grid-cols-[1fr_auto]">
        <div className="grid content-center gap-1">
          <p className="text-sm font-semibold text-ink">Get this every week</p>
          <p className="text-sm leading-6 text-ink/60">
            Local food signals for {report.region} — delivered to your inbox.
          </p>
        </div>
        <div className="md:w-80">
          <SubscribeForm />
        </div>
      </div>
    </article>
  );
}
