import { ArrowUpRight, CalendarDays, MapPin, Newspaper, Sparkles, Utensils } from "lucide-react";
import Link from "next/link";

import type { Report } from "@/lib/types";
import { buildLocalBriefing } from "@/lib/briefing";

type Props = {
  report: Report;
};

export function LocalBriefing({ report }: Props) {
  const briefing = buildLocalBriefing(report);

  return (
    <article className="mx-auto grid w-full max-w-[1180px] gap-8 px-4 py-7 md:px-8 md:py-10 lg:gap-10 lg:px-10">
      <header className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))] gap-6 border-b border-line pb-8 lg:gap-8">
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-semibold text-moss">
          <Newspaper size={16} />
          LocalSignal
          <span className="h-1 w-1 rounded-full bg-ink/30" />
          <span className="inline-flex min-w-0 items-center gap-1 break-words text-ink/58">
            <CalendarDays size={15} />
            {briefing.eyebrow}
          </span>
        </div>

        <div className="grid min-w-0 gap-4">
          <div className="min-w-0">
            <div className="text-sm font-semibold uppercase text-ink/48">What this page is</div>
            <h1 className="mt-2 break-words text-4xl font-semibold leading-tight text-ink md:text-[3rem] lg:text-[3.4rem]">
              {briefing.scopeTitle}
            </h1>
            <p className="mt-4 text-lg leading-8 text-ink/72 lg:text-xl lg:leading-9">
              {briefing.scopeSummary}
            </p>
          </div>

        </div>

        <section className="min-w-0 rounded-lg border border-line bg-white p-5 shadow-sm md:p-6 lg:p-7">
          <div className="flex items-center gap-2 text-sm font-semibold text-moss">
            <Sparkles size={16} />
            This week&apos;s read
          </div>
          <h2 className="mt-3 break-words text-3xl font-semibold leading-tight text-ink md:text-[2.25rem] lg:text-[2.45rem]">
            {briefing.title}
          </h2>
          <p className="mt-4 text-[17px] leading-8 text-ink/74 lg:text-lg lg:leading-8">{briefing.subtitle}</p>
          <p className="mt-4 border-l-2 border-moss pl-4 text-base leading-7 text-ink/70">
            {briefing.whyItMatters}
          </p>
        </section>
      </header>

      {briefing.topSignals.length ? (
        <section className="grid gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-ink/72">
              <Utensils size={16} className="text-moss" />
              Start with these three
            </div>
            <p className="mt-1 text-sm leading-6 text-ink/60">
              Open one when you already know the craving, the occasion, or the kind of night you want.
            </p>
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,320px),1fr))] gap-4">
            {briefing.topSignals.map((signal) => (
              <Link
                key={signal.href}
                href={signal.href}
                className="group min-w-0 rounded-lg border border-line bg-white p-5 shadow-sm transition hover:border-moss/45 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35 lg:p-6"
              >
                <div className="text-xs font-semibold uppercase text-moss">{signal.category}</div>
                <h2 className="mt-2 break-words text-2xl font-semibold leading-8 text-ink group-hover:text-moss lg:text-[1.7rem] lg:leading-9">{signal.place}</h2>
                <p className="mt-3 text-[17px] font-semibold leading-7 text-ink/78">{signal.pull}</p>
                <div className="mt-4 grid gap-3 text-[15px] leading-6 text-ink/66">
                  <p>
                    <span className="font-semibold text-ink/80">Good for: </span>
                    {signal.goodFor}
                  </p>
                  <p>
                    <span className="font-semibold text-ink/80">What changed: </span>
                    {signal.changed}
                  </p>
                </div>
                <div className="mt-4 flex min-w-0 items-center justify-between gap-3 text-sm font-semibold text-ink/50">
                  <span className="min-w-0 break-words">{signal.area}</span>
                  <span className="inline-flex items-center gap-1 text-moss">
                    Open details
                    <ArrowUpRight size={16} />
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {briefing.places.length ? (
        <section className="grid gap-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink/72">
            <MapPin size={16} className="text-moss" />
            Places behind this week&apos;s read
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,300px),1fr))] gap-4">
            {briefing.places.slice(0, 3).map((place) => (
              <Link
                key={`${place.name}-${place.area}`}
                href={place.href}
                className="group min-w-0 rounded-lg border border-line bg-white p-4 shadow-sm transition hover:border-moss/45 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35 md:p-5 lg:p-6"
              >
                <div className="text-xs font-semibold uppercase text-moss">{place.category}</div>
                <h2 className="mt-2 break-words text-xl font-semibold leading-7 text-ink group-hover:text-moss">{place.name}</h2>
                <div className="mt-2 break-words text-sm text-ink/58">{place.area}</div>
                {place.reason ? <p className="mt-3 text-[15px] leading-6 text-ink/62">{place.reason}</p> : null}
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {briefing.categorySections.length ? (
        <section className="grid gap-4 border-t border-line pt-7">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink/72">
            <Utensils size={16} className="text-moss" />
            Browse by craving or occasion
          </div>
          <div className="grid gap-5">
            {briefing.categorySections.map((section) => (
              <section key={section.label} className="grid gap-3">
                <div>
                  <h2 className="text-xl font-semibold text-ink">{section.label}</h2>
                  <p className="mt-1 text-sm leading-6 text-ink/60">{section.description}</p>
                </div>
                <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,300px),1fr))] gap-4">
                  {section.cards.map((card) => (
                    <Link
                      key={`${section.label}-${card.href}`}
                      href={card.href}
                      className="group min-w-0 rounded-lg border border-line bg-white p-4 shadow-sm transition hover:border-moss/45 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35 md:p-5"
                    >
                      <div className="break-words text-xs font-semibold uppercase text-moss">{card.area}</div>
                      <h3 className="mt-2 break-words text-lg font-semibold leading-7 text-ink group-hover:text-moss">{card.title}</h3>
                      <p className="mt-2 text-[15px] leading-7 text-ink/64">{card.changed}</p>
                      <p className="mt-2 text-sm leading-6 text-ink/58">
                        <span className="font-semibold text-ink/70">Good for: </span>
                        {card.goodFor}
                      </p>
                      <div className="mt-3 flex min-w-0 items-center justify-between gap-3 text-sm font-semibold text-ink/50">
                        <span className="min-w-0 break-words">{card.place}</span>
                        <span className="inline-flex items-center gap-1 text-moss">
                          Details
                          <ArrowUpRight size={15} />
                        </span>
                      </div>
                    </Link>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </section>
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
    </article>
  );
}
