import { Compass, Sparkles } from "lucide-react";

import type { Signal } from "@/lib/types";
import { weeklyRead } from "@/lib/signalStory";

type Props = {
  signals: Signal[];
};

export function WeeklyRead({ signals }: Props) {
  const read = weeklyRead(signals);

  return (
    <section className="grid gap-4 border-b border-line pb-8 md:grid-cols-[280px_1fr]">
      <div className="flex items-center gap-2 text-sm font-semibold text-ink">
        <Compass size={16} className="text-moss" />
        This week's read
      </div>
      <div>
        <h2 className="max-w-3xl text-2xl font-semibold leading-tight text-ink md:text-3xl">{read.headline}</h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-ink/72 md:text-base">{read.body}</p>
        <div className="mt-4 grid gap-2 md:grid-cols-3">
          {read.bullets.map((bullet) => (
            <div key={bullet} className="flex gap-2 rounded-lg border border-line bg-white/78 p-3 text-sm leading-5 text-ink/68">
              <Sparkles size={15} className="mt-0.5 shrink-0 text-moss" />
              <span>{bullet}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
