import { Database, ExternalLink, Gauge, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import type { SocialSourceRun } from "@/lib/types";

type Props = {
  runs: SocialSourceRun[];
};

export function SocialSourceHealth({ runs }: Props) {
  const latest = runs[0];
  const totals = runs.reduce(
    (acc, run) => ({
      fresh: acc.fresh + run.fresh_records,
      resolved: acc.resolved + run.resolved_items,
      old: acc.old + run.old_records_dropped,
      parsed: acc.parsed + run.parsed_items,
      searched: acc.searched + (run.provider === "apify_search" ? 1 : 0)
    }),
    { fresh: 0, resolved: 0, old: 0, parsed: 0, searched: 0 }
  );

  return (
    <section className="grid gap-4 border-t border-line pt-6 md:grid-cols-[260px_1fr]">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <ShieldCheck size={16} />
          Social source health
        </div>
        <p className="mt-2 text-sm leading-6 text-ink/65">
          Tracks whether imported Instagram, TikTok, or Xiaohongshu metadata is fresh, place-resolved, and usable as evidence.
        </p>
        <Link href="/source-health" className="mt-3 inline-flex text-sm font-semibold text-moss">Source Health</Link>
      </div>

      <div className="grid gap-3">
        <div className="grid gap-3 sm:grid-cols-4">
          <Metric label="Fresh records" value={totals.fresh} icon={<Database size={15} />} />
          <Metric label="Resolved" value={totals.resolved} icon={<Gauge size={15} />} />
          <Metric label="Search runs" value={totals.searched} icon={<Search size={15} />} />
          <Metric label="Old dropped" value={totals.old} />
        </div>

        <div className="overflow-hidden rounded-lg border border-line bg-white/88 shadow-sm">
          {runs.length ? (
            <div className="divide-y divide-line">
              {runs.map((run) => (
                <div key={run.id} className="grid gap-3 p-4 md:grid-cols-[1fr_92px_92px_92px] md:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
                      <span>{providerLabel(run.provider)}</span>
                      <span className="rounded-md border border-line px-2 py-0.5 text-xs text-ink/65">{run.platform}</span>
                      <span className={run.status === "succeeded" ? "text-moss" : "text-red-700"}>{run.status}</span>
                    </div>
                    <div className="mt-1 flex min-w-0 items-center gap-1 text-xs text-ink/55">
                      <ExternalLink size={13} />
                      <span className="truncate">{run.query || run.dataset_id || "manual import"}</span>
                    </div>
                    {run.error ? <div className="mt-1 text-xs text-red-700">{run.error}</div> : null}
                  </div>
                  <SmallStat label={run.provider === "apify_search" ? "Found" : "Fresh"} value={run.provider === "apify_search" ? run.total_records : run.fresh_records} />
                  <SmallStat label="Resolved" value={run.resolved_items} />
                  <SmallStat label="Old" value={run.old_records_dropped} />
                </div>
              ))}
            </div>
          ) : (
            <div className="p-4 text-sm leading-6 text-ink/65">No social source runs recorded yet. Run the evidence pipeline after importing compliant metadata.</div>
          )}
        </div>

        {latest ? <p className="text-xs text-ink/55">Latest check: {formatDate(latest.finished_at)}. Search rows show discovery; Apify rows show evidence import quality.</p> : null}
      </div>
    </section>
  );
}

function providerLabel(provider: string) {
  if (provider === "apify_search") {
    return "apify search";
  }
  return provider;
}

function Metric({ label, value, icon }: { label: string; value: number; icon?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-white/88 p-3 shadow-sm">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-ink/55">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-ink">{value}</div>
    </div>
  );
}

function SmallStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-sm md:text-right">
      <div className="text-xs text-ink/50">{label}</div>
      <div className="font-semibold text-ink">{value}</div>
    </div>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}
