import { CalendarDays, MapPin, Radar, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";

import { SubscribeForm } from "@/components/SubscribeForm";
import type { Report, Signal } from "@/lib/types";
import { evidenceNotes, mentionCountFor, phenomenonTitle, sourceCountFor, weeklyRead } from "@/lib/signalStory";

type Props = {
  report: Report;
};

export function DashboardOverview({ report }: Props) {
  const read = weeklyRead(report.signals);
  const topSignals = [...report.signals].sort((left, right) => right.score - left.score).slice(0, 3);
  const strong = report.signals.filter((signal) => signal.signal_strength === "Strong signal");
  const watching = report.signals.filter((signal) => signal.signal_strength === "Watching");
  const highConfidence = report.signals.filter((signal) => signal.confidence === "High");

  return (
    <section className="grid gap-6 border-b border-line pb-6">
      <header className="grid gap-6 md:grid-cols-[1fr_300px] md:items-end">
        <div>
          <div className="mb-4 inline-flex items-center gap-2 rounded-md border border-line bg-white/80 px-3 py-1.5 text-sm font-semibold text-moss shadow-sm">
            <Radar size={16} />
            LocalSignal
          </div>
          <h1 className="max-w-3xl text-4xl font-semibold leading-tight text-ink md:text-6xl">
            This Week Nearby
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-ink/78 md:text-lg">
            See what changed in the local food scene this week.
          </p>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-ink/64 md:text-base">
            A weekly read on places, dishes, and habits getting unusual attention around Fort Lee, Edgewater, and Palisades Park.
          </p>
        </div>

        <div className="grid gap-3">
          <div className="rounded-lg border border-line bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <CalendarDays size={16} className="text-moss" />
              Week of {formatDate(report.week_start)}
            </div>
            <div className="mt-3 flex items-start gap-2 text-sm leading-6 text-ink/64">
              <MapPin size={16} className="mt-0.5 shrink-0 text-moss" />
              <span>{report.region}</span>
            </div>
            <div className="mt-4 flex items-center gap-2 text-sm font-semibold text-moss">
              <TrendingUp size={16} />
              {report.signals.length} local changes tracked
            </div>
          </div>
          <SubscribeForm />
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="rounded-lg border border-line bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink/60">
            <Sparkles size={16} className="text-moss" />
            This week's read
          </div>
          <h2 className="mt-3 max-w-3xl text-2xl font-semibold leading-tight text-ink md:text-3xl">
            {read.headline}
          </h2>
          <p className="mt-4 max-w-3xl text-base leading-7 text-ink/74">{read.body}</p>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <MiniStat label="Moving now" value={strong.length} detail="Worth a closer look" tone="text-moss" />
            <MiniStat label="On the radar" value={watching.length} detail="Interesting, still early" tone="text-clay" />
            <MiniStat label="Feels solid" value={highConfidence.length} detail="Clearer local clues" tone="text-ink" />
          </div>
        </div>

        <aside className="rounded-lg border border-line bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-semibold uppercase text-ink/58">Start here</div>
            <div className="rounded-md bg-paper px-2 py-1 text-xs font-semibold text-ink/60">Top 3</div>
          </div>

          <div className="mt-3 grid gap-3">
            {topSignals.map((signal, index) => (
              <Link
                key={signal.id}
                href={`/signal/${signal.slug}`}
                className="group rounded-md border border-line bg-paper p-3 transition hover:border-moss/45 hover:bg-white focus:outline-none focus-visible:ring-2 focus-visible:ring-moss/35"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold uppercase text-moss">#{index + 1} worth noting</div>
                    <h3 className="mt-1 line-clamp-2 text-sm font-semibold leading-5 text-ink group-hover:text-moss">
                      {phenomenonTitle(signal)}
                    </h3>
                  </div>
                  <SignalPill signal={signal} />
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs font-medium text-ink/56">
                  <span>{signal.place.name}</span>
                  <span>{sourceCountFor(signal) || 1} place(s) we saw it</span>
                  <span>{mentionCountFor(signal) || "Some"} recent mentions</span>
                </div>
                <p className="mt-2 line-clamp-2 text-xs leading-5 text-ink/60">{evidenceNotes(signal)[0]}</p>
              </Link>
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}

function MiniStat({ label, value, detail, tone }: { label: string; value: number | string; detail: string; tone: string }) {
  return (
    <div className="rounded-md border border-line bg-paper px-3 py-2">
      <div className="flex items-baseline gap-2">
        <span className={`text-xl font-semibold ${tone}`}>{value}</span>
        <span className="text-sm font-semibold text-ink">{label}</span>
      </div>
      <div className="mt-1 text-xs leading-5 text-ink/58">{detail}</div>
    </div>
  );
}

function SignalPill({ signal }: { signal: Signal }) {
  if (signal.signal_strength === "Strong signal") {
    return <span className="shrink-0 rounded-md bg-moss px-2 py-1 text-xs font-semibold text-white">Act</span>;
  }
  if (signal.signal_strength === "Watching") {
    return <span className="shrink-0 rounded-md bg-clay/12 px-2 py-1 text-xs font-semibold text-clay">Watch</span>;
  }
  return <span className="shrink-0 rounded-md bg-ink/8 px-2 py-1 text-xs font-semibold text-ink/55">Quiet</span>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric"
  }).format(new Date(value));
}
