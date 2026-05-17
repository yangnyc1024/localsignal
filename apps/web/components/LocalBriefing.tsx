import { ArrowUpRight, CalendarDays, MapPin, Newspaper, Sparkles } from "lucide-react";
import Link from "next/link";

import type { Report } from "@/lib/types";
import { buildLocalBriefing } from "@/lib/briefing";

type Props = {
  report: Report;
};

export function LocalBriefing({ report }: Props) {
  const briefing = buildLocalBriefing(report);

  return (
    <article className="mx-auto grid w-full max-w-4xl gap-10 px-4 py-8 md:px-8 md:py-12">
      <header className="grid gap-5 border-b border-line pb-8">
        <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-moss">
          <Newspaper size={16} />
          LocalSignal
          <span className="h-1 w-1 rounded-full bg-ink/30" />
          <span className="inline-flex items-center gap-1 text-ink/58">
            <CalendarDays size={15} />
            {briefing.eyebrow}
          </span>
        </div>

        <div>
          <h1 className="max-w-4xl text-4xl font-semibold leading-tight text-ink md:text-6xl">
            {briefing.title}
          </h1>
          <p className="mt-5 max-w-3xl text-lg leading-8 text-ink/74">
            {briefing.subtitle}
          </p>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-[170px_1fr]">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <Sparkles size={16} className="text-moss" />
          Why it matters
        </div>
        <p className="max-w-3xl text-lg leading-8 text-ink/78">{briefing.whyItMatters}</p>
      </section>

      {briefing.places.length ? (
        <section className="grid gap-4 md:grid-cols-[170px_1fr]">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <MapPin size={16} className="text-moss" />
            Places involved
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {briefing.places.slice(0, 3).map((place) => (
              <Link
                key={`${place.name}-${place.area}`}
                href={place.href}
                className="group rounded-lg border border-line bg-white p-4 shadow-sm transition hover:border-moss/45 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35"
              >
                <div className="text-xs font-semibold uppercase text-moss">{place.category}</div>
                <h2 className="mt-2 line-clamp-2 text-base font-semibold leading-5 text-ink group-hover:text-moss">{place.name}</h2>
                <div className="mt-2 text-sm text-ink/58">{place.area}</div>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {briefing.supportingReads.length ? (
        <section className="grid gap-4 border-t border-line pt-8">
          <div>
            <h2 className="text-2xl font-semibold text-ink">Also worth noting</h2>
            <p className="mt-2 text-sm leading-6 text-ink/60">Smaller reads that did not need a full dashboard.</p>
          </div>
          <div className="grid gap-3">
            {briefing.supportingReads.map((read) => (
              <Link
                key={read.href}
                href={read.href}
                className="group grid gap-3 rounded-lg border border-line bg-white p-4 shadow-sm transition hover:border-moss/45 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35 md:grid-cols-[1fr_180px]"
              >
                <div>
                  <h3 className="text-lg font-semibold leading-6 text-ink group-hover:text-moss">{read.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-ink/66">{read.summary}</p>
                </div>
                <div className="flex items-end justify-between gap-3 text-sm font-semibold text-ink/55 md:flex-col md:items-end">
                  <span>{read.place}</span>
                  <ArrowUpRight size={16} className="text-moss" />
                </div>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {briefing.sources.length ? (
        <details className="rounded-lg border border-line bg-white p-4 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-ink">Sources behind this read</summary>
          <div className="mt-4 grid gap-3">
            {briefing.sources.map((source) => (
              <Link key={`${source.label}-${source.href}`} href={source.href} className="group block rounded-md bg-paper p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-ink group-hover:text-moss">{source.label}</div>
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
