import { ArrowLeft, Database, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { SocialSourceHealth } from "@/components/SocialSourceHealth";
import { getSocialSourceRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SourceHealthPage() {
  const runs = await getSocialSourceRuns();
  const searchRuns = runs.filter((run) => run.provider === "apify_search").length;
  const importRuns = runs.filter((run) => run.provider !== "apify_search").length;
  const fresh = runs.reduce((sum, run) => sum + run.fresh_records, 0);
  const resolved = runs.reduce((sum, run) => sum + run.resolved_items, 0);

  return (
    <main className="min-h-screen">
      <section className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-8 md:px-8 md:py-10">
        <header className="border-b border-line pb-6">
          <Link href="/admin" className="inline-flex items-center gap-2 text-sm font-semibold text-moss">
            <ArrowLeft size={16} />
            Back to admin
          </Link>
          <div className="mt-5 flex items-center gap-2 text-sm font-semibold text-ink">
            <ShieldCheck size={16} />
            Source Health
          </div>
          <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight text-ink md:text-5xl">
            Internal source quality
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-ink/68 md:text-base">
            Use this page to decide whether the system truly has no new signal, or whether the source query, freshness window, or place resolution needs work.
          </p>
        </header>

        <section className="grid gap-3 md:grid-cols-4">
          <Metric label="Search runs" value={searchRuns} icon={<Search size={16} />} />
          <Metric label="Import runs" value={importRuns} icon={<Database size={16} />} />
          <Metric label="Fresh evidence" value={fresh} />
          <Metric label="Resolved evidence" value={resolved} />
        </section>

        <SocialSourceHealth runs={runs} />
      </section>
    </main>
  );
}

function Metric({ label, value, icon }: { label: string; value: number; icon?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-white/88 p-4 shadow-sm">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-ink/55">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-3xl font-semibold text-ink">{value}</div>
    </div>
  );
}
