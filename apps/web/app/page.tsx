import { CalendarDays, Radar, TrendingUp } from "lucide-react";

import { SignalCard } from "@/components/SignalCard";
import { getLatestReport } from "@/lib/api";

export default async function Home() {
  const report = await getLatestReport();

  return (
    <main className="min-h-screen">
      <section className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-8 md:px-8 md:py-10">
        <header className="grid gap-6 border-b border-line pb-8 md:grid-cols-[1fr_280px] md:items-end">
          <div>
            <div className="mb-4 inline-flex items-center gap-2 rounded-md border border-line bg-white/80 px-3 py-1.5 text-sm font-semibold text-moss">
              <Radar size={16} />
              LocalSignal
            </div>
            <h1 className="max-w-3xl text-4xl font-semibold leading-tight text-ink md:text-6xl">
              {report.title}
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-ink/75 md:text-lg">{report.intro}</p>
          </div>

          <div className="rounded-lg border border-line bg-white/88 p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <CalendarDays size={16} />
              Week of {formatDate(report.week_start)}
            </div>
            <div className="mt-3 text-sm leading-6 text-ink/65">{report.region}</div>
            <div className="mt-4 flex items-center gap-2 text-sm font-semibold text-moss">
              <TrendingUp size={16} />
              {report.signals.length} signals ranked
            </div>
          </div>
        </header>

        <section className="grid gap-4">
          {report.signals.map((signal, index) => (
            <SignalCard key={signal.id} signal={signal} rank={index + 1} />
          ))}
        </section>
      </section>
    </main>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric"
  }).format(new Date(value));
}
