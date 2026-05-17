import { Radar } from "lucide-react";

import { LocalBriefing } from "@/components/LocalBriefing";
import { getLatestReport } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const report = await getLatestReport();

  if (!report) {
    return (
      <main className="min-h-screen">
        <section className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 md:px-8 md:py-10">
          <div className="rounded-lg border border-line bg-white/88 p-6 shadow-sm">
            <div className="mb-4 inline-flex items-center gap-2 rounded-md border border-line bg-white/80 px-3 py-1.5 text-sm font-semibold text-moss">
              <Radar size={16} />
              LocalSignal
            </div>
            <h1 className="text-3xl font-semibold text-ink">This Week Nearby</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-ink/70">
              Real food signals are unavailable right now. Start the API and database, then refresh this page.
            </p>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen">
      <LocalBriefing report={report} />
    </main>
  );
}
