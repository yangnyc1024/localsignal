import { ArrowRight, Database, FileText, HeartPulse, Newspaper } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { getLatestReport, getSocialSourceRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AdminPage() {
  const [report, runs] = await Promise.all([getLatestReport(), getSocialSourceRuns()]);
  const latestSignal = report?.signals?.[0] ?? null;
  const freshEvidence = runs.reduce((sum, run) => sum + run.fresh_records, 0);
  const resolvedEvidence = runs.reduce((sum, run) => sum + run.resolved_items, 0);
  const erroredRuns = runs.filter((run) => run.status.toLowerCase() === "error").length;
  const hasBriefing = Boolean(report?.briefing?.title && report.briefing?.why_it_matters);

  return (
    <main className="min-h-screen">
      <section className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-8 md:px-8 md:py-10">
        <header className="border-b border-line pb-6">
          <div className="inline-flex items-center gap-2 text-sm font-semibold text-moss">
            <HeartPulse size={16} />
            LocalSignal Admin
          </div>
          <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight text-ink md:text-5xl">
            Internal review surface
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-ink/68 md:text-base">
            Use this side to inspect evidence, pipeline health, and whether the public briefing is ready to feel like a local editor wrote it.
          </p>
        </header>

        <section className="grid gap-3 md:grid-cols-4">
          <Metric label="Published signals" value={report?.signals.length ?? 0} />
          <Metric label="Briefing ready" value={hasBriefing ? "Yes" : "No"} />
          <Metric label="Fresh evidence" value={freshEvidence} />
          <Metric label="Source errors" value={erroredRuns} />
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          <AdminLink
            href="/"
            icon={<Newspaper size={18} />}
            title="Public briefing"
            detail="The user-facing weekly read. Keep this short, narrative, and free of pipeline language."
          />
          <AdminLink
            href="/source-health"
            icon={<Database size={18} />}
            title="Source health"
            detail={`${runs.length} recent runs, ${resolvedEvidence} resolved evidence items.`}
          />
          <AdminLink
            href={latestSignal ? `/signal/${latestSignal.slug}` : "/"}
            icon={<FileText size={18} />}
            title="Latest signal detail"
            detail={latestSignal ? latestSignal.title : "No signal detail is available yet."}
          />
        </section>

        <section className="border-t border-line pt-6">
          <div className="text-xs font-semibold uppercase text-ink/50">Current editor read</div>
          <h2 className="mt-2 max-w-3xl text-2xl font-semibold leading-snug text-ink">
            {report?.briefing?.title ?? report?.title ?? "No briefing generated yet"}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-ink/68">
            {report?.briefing?.why_it_matters ??
              report?.intro ??
              "Run the weekly pipeline to generate the first public briefing."}
          </p>
        </section>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-line bg-white/88 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase text-ink/55">{label}</div>
      <div className="mt-2 text-3xl font-semibold text-ink">{value}</div>
    </div>
  );
}

function AdminLink({
  href,
  icon,
  title,
  detail
}: {
  href: string;
  icon: ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <Link href={href} className="group rounded-lg border border-line bg-white/88 p-5 shadow-sm transition hover:border-moss/40 hover:bg-white">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          {icon}
          {title}
        </div>
        <ArrowRight size={16} className="text-ink/35 transition group-hover:translate-x-0.5 group-hover:text-moss" />
      </div>
      <p className="mt-3 text-sm leading-6 text-ink/64">{detail}</p>
    </Link>
  );
}
