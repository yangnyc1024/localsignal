import { Utensils } from "lucide-react";

import type { HighlightItem, RestaurantBrief, SignalDetail } from "@/lib/types";
import { cleanText, shortPlaceName } from "../_utils";

type Props = {
  signal: SignalDetail;
  cuisine: string;
};

export function AboutPlaceSection({ signal, cuisine }: Props) {
  const brief = signal.restaurant_brief as RestaurantBrief | null | undefined;
  const place = shortPlaceName(signal.place.name);
  const whatItIs = brief?.what_it_is || signal.evidence.place_profile?.known_for || "";
  const dishes = brief?.signature_menu_items?.slice(0, 6) ?? (signal.evidence.place_profile?.signature_items ?? []).slice(0, 6);
  const highlights = (brief?.highlight_items ?? []) as HighlightItem[];
  const vibeTags = brief?.vibe_tags ?? [];
  const occasions = brief?.occasions ?? (signal.evidence.place_profile?.occasions ?? []).slice(0, 3);
  const locationFormat = brief?.location_format || signal.place.neighborhood || signal.city;

  return (
    <section className="rounded-lg border border-line bg-white/88 p-5 shadow-sm md:p-6">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-normal text-ink/60">
        <Utensils size={17} className="text-moss" />
        About this place
      </h2>
      <div className="grid gap-6">
        {/* Hero: name + description */}
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-moss">{cuisine}</div>
          <p className="mt-2 text-xl font-semibold leading-7 text-ink">{place}</p>
          {whatItIs ? (
            <p className="mt-3 max-w-3xl text-base leading-7 text-ink/72">{cleanText(whatItIs)}</p>
          ) : null}
        </div>

        {/* Highlight items — what makes it distinctive */}
        {highlights.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {highlights.map((h) => (
              <div key={h.aspect} className="rounded-lg border border-line bg-paper p-4">
                <div className="text-sm font-semibold text-ink">{h.aspect}</div>
                <p className="mt-1.5 text-sm leading-6 text-ink/66">{h.detail}</p>
              </div>
            ))}
          </div>
        ) : null}

        {/* Signature dishes + experience */}
        <div className="grid gap-3 sm:grid-cols-2">
          {dishes.length > 0 ? (
            <div className="rounded-lg border border-line bg-paper p-4">
              <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">Signature dishes</div>
              <ul className="mt-3 grid gap-2">
                {dishes.map((item) => {
                  const [name, ...rest] = item.split(/\s+-\s+/);
                  const detail = rest.join(" - ");
                  return (
                    <li key={item} className="text-sm leading-6 text-ink/74">
                      <span className="font-semibold text-ink">{cleanText(name)}</span>
                      {detail ? <span>: {cleanText(detail)}</span> : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          <div className="rounded-lg border border-line bg-paper p-4">
            <div className="text-xs font-semibold uppercase tracking-normal text-ink/48">The experience</div>
            <p className="mt-3 text-sm leading-6 text-ink/72">{locationFormat}</p>
            {vibeTags.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {vibeTags.map((tag) => (
                  <span key={tag} className="rounded-full border border-line bg-white/82 px-2.5 py-1 text-xs font-semibold text-ink/68">
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
            {occasions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {occasions.map((o) => (
                  <span key={o} className="rounded-full border border-moss/30 bg-moss/8 px-2.5 py-1 text-xs font-semibold text-moss">
                    {cleanText(o)}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        {brief?.source_chips?.length ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink/48">
            <span className="font-semibold">Sources</span>
            {brief.source_chips.slice(0, 4).map((chip) => (
              <span key={chip} className="rounded-full border border-line bg-white/82 px-2.5 py-1 font-semibold">
                {chip}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
