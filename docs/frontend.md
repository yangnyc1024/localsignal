# LocalSignal Frontend Architecture

## Stack

| Layer | Choice |
|---|---|
| Framework | Next.js 14 App Router |
| Language | TypeScript (strict) |
| Styling | Tailwind CSS (custom token palette) |
| Icons | lucide-react |
| API calls | native `fetch` in Server Components |
| Package root | `apps/web/` |

No state management library. No client-side data fetching library (no SWR, no React Query). All data arrives through Server Component `async` functions.

---

## Route Map

```
app/
├── layout.tsx              — root HTML shell, <body>
├── page.tsx                — / (homepage): weekly briefing
├── signal/[slug]/
│   ├── page.tsx            — /signal/:slug (signal detail)
│   ├── _utils.ts           — pure data functions for the detail page
│   └── _components/        — co-located components for the detail page
│       ├── Section.tsx
│       ├── AboutPlaceSection.tsx
│       ├── WhatsMovingSection.tsx
│       ├── TrendChart.tsx
│       ├── MiniMap.tsx
│       └── EvidenceSection.tsx
├── admin/
│   └── page.tsx            — /admin: pipeline health dashboard
└── source-health/
    └── page.tsx            — /source-health: social evidence run log
```

All pages are `force-dynamic` (no static generation). Every page render fetches fresh data from the API.

---

## Server Component vs Client Component Boundary

The rule: **push the client boundary as late as possible**. A component becomes `"use client"` only when it needs `useState` or browser events.

```
app/page.tsx                    SERVER — fetches report, renders LocalBriefing
  └── components/LocalBriefing.tsx    SERVER — builds briefing from report, renders layout
        └── components/CategoryFilterSection.tsx  CLIENT — filter state (useState)
        └── components/SubscribeForm.tsx           CLIENT — form state (useState)

app/signal/[slug]/page.tsx      SERVER — fetches SignalDetail, wires components
  └── _components/AboutPlaceSection   SERVER
  └── _components/WhatsMovingSection  SERVER
  └── _components/TrendChart          SERVER
  └── _components/MiniMap             SERVER (iframe, static links)
  └── _components/EvidenceSection     SERVER (details/summary, no JS state)
  └── _components/Section             SERVER

app/admin/page.tsx              SERVER
app/source-health/page.tsx      SERVER
  └── components/SocialSourceHealth   SERVER
```

**Client components: 2** (`CategoryFilterSection`, `SubscribeForm`). Everything else renders on the server.

---

## Data Flow

```
FastAPI (services/api)
    ↓  fetch in Server Component
lib/api.ts  (typed fetch wrappers)
    ↓
Page component  (async, runs on server)
    ↓  props
Child components  (server or client)
    ↓
HTML streamed to browser
```

`lib/api.ts` is the only place that calls the API. All fetches use `cache: "no-store"` so every render is fresh. `INTERNAL_API_BASE_URL` is used server-side (container-to-container); `NEXT_PUBLIC_API_BASE_URL` is the fallback and the one exposed to the browser for `SubscribeForm`.

---

## Library Layer (`lib/`)

### `lib/types.ts` — shared TypeScript types

The single source of truth for the API contract on the frontend. All types mirror what `GET /reports/latest` and `GET /signals/{slug}` return.

Key types:

| Type | Source endpoint | Purpose |
|---|---|---|
| `Report` | `/reports/latest` | Weekly report with signals + briefing |
| `Signal` | embedded in Report | One signal card on the homepage |
| `SignalDetail` | `/signals/{slug}` | Full signal data for the detail page |
| `RestaurantBrief` | nested in SignalDetail | "About this place" structured brief |
| `FoodSignal` | nested in SignalDetail | "What's moving this week" weekly read |
| `BaselineContext` | nested in SignalDetail | Trailing mention counts + heat score |
| `BriefingPayload` | nested in Report | AI-generated report narrative |
| `SocialSourceRun` | `/api/source-health/social` | Evidence pipeline run log |

### `lib/signalStory.ts` — signal display logic (shared across pages)

Exports:

| Function | Purpose |
|---|---|
| `placeIdentity(signal)` | `{ cuisine, name, area }` — canonical display identity |
| `cuisineType(signal)` | Resolves cuisine label from backend field or keyword heuristic |
| `placeArea(signal)` | `"Neighborhood, City"` or just city |
| `textEvidence(signal, key)` | Safe string extraction from `signal.evidence` bag |
| `evidenceNotes(signal)` | 2–3 human-readable bullet points from evidence |
| `mentionCountFor(signal)` | Preferred mention count (current > trailing) |
| `sourceCountFor(signal)` | Number of distinct source paths |

All functions take `Signal` (not `SignalDetail`) so they work on both list and detail contexts.

### `lib/briefing.ts` — homepage briefing builder

`buildLocalBriefing(report): LocalBriefing` transforms the raw `Report` DTO into a display-ready structure used by `LocalBriefing.tsx`. It runs entirely on the server — no client-side execution.

Output shape:

```
LocalBriefing {
  eyebrow          — week label string
  title            — AI narrative headline
  subtitle         — one-paragraph supporting copy
  whyItMatters     — pull-quote for the border-left callout
  foodReads        — top 3 signals as "What to open" cards
  longTermSignals  — "Watching" or high-heat-score places
  categorySections — signals grouped by food category (for filter)
  sources          — signal slugs/titles as source references
}
```

`categorySections` is what `CategoryFilterSection` receives as props. The server computes the full filtered lists; the client only manages which filter tab is active.

---

## Signal Detail Page

The detail page (`app/signal/[slug]/`) is intentionally self-contained. It does not use any shared `/components` — only its own `_components/` and `_utils.ts`.

### `_utils.ts` — pure data functions

All derived-data logic lives here. No JSX, no imports from React. Functions are exported individually so each component only imports what it needs.

Key functions:

| Function | Returns |
|---|---|
| `heroFor(signal)` | `{ title, claim }` for the page header |
| `profileCuisine(signal)` | Display cuisine string (prefers food_signal pull) |
| `whyChanged(signal)` | Up to 4 humanized "why" bullet points |
| `trendPoints(signal)` | `ChartPoint[]` — baseline/wk vs this-week mentions |
| `curatedEvidence(signal)` | Top 5 non-empty evidence excerpts |
| `nearbyPlaces(signal)` | Up to 4 related signals (different place) |
| `cleanText(value)` | Strip control chars, hex tokens, normalize whitespace |
| `shortPlaceName(value)` | Strip pipe suffixes, "Cajun Seafood" chain name, "NJ" |
| `humanizeReason(value)` | Replace verbose ML-output phrases with readable copy |
| `googleMapsEmbedUrl(signal)` | Prefer lat/lng embed; fall back to text search |

`trendPoints` uses real data: `baseline_context.trailing_30d_mentions / 4` (weekly baseline average) vs `evidence.current_mention_count` (this week). Falls back to score comparison when mention data is absent.

### Two-section layout

```
About this place        ← RestaurantBrief (place_documents.metadata)
  - what_it_is
  - highlight_items
  - signature_menu_items
  - vibe_tags + occasions
  Falls back to → evidence.place_profile when brief is null

What's moving this week ← FoodSignal (signals.food_signal column)
  - signal_dish / primary_pull
  - occasion
  - top 3 evidence excerpts ("Recent voices")

Why This Signal Happened
Signal vs Baseline      ← TrendChart (trailing_30d_mentions, current_mention_count)
Nearby Context          ← MiniMap (Google Maps iframe + related_signals)
Evidence                ← EvidenceSection (collapsible, evidence_items)
```

---

## Design Tokens

Five semantic colors, defined in `tailwind.config.ts`:

| Token | Hex | Use |
|---|---|---|
| `ink` | `#16201d` | Primary text |
| `moss` | `#3f6f5b` | Primary accent, CTAs, active states |
| `clay` | `#b85636` | External links, error states |
| `paper` | `#f7f3eb` | Card backgrounds, inset surfaces |
| `line` | `#ded7ca` | Borders, dividers |

Opacity variants (`text-ink/60`, `bg-moss/8`, etc.) are used extensively instead of new color definitions. This keeps the palette narrow.

---

## Internal Pages

### `/admin`

Server Component. Calls `getLatestReport()` and `getSocialSourceRuns()` in parallel. Shows:
- Signal count, briefing readiness, evidence stats
- Quick links to public briefing, source health, latest signal detail
- Current briefing title + why-it-matters copy

Not auth-protected in the MVP (internal tool only).

### `/source-health`

Server Component. Calls `getSocialSourceRuns()`. Delegates table rendering to `SocialSourceHealth` (also a Server Component). Shows per-run stats: provider, platform, fresh/resolved/old record counts, error state.

---

## Environment Variables

| Variable | Used in | Purpose |
|---|---|---|
| `INTERNAL_API_BASE_URL` | Server Components | Container-to-container API URL |
| `NEXT_PUBLIC_API_BASE_URL` | Server + browser | Public API URL (SubscribeForm uses this at runtime) |
| `GOOGLE_PLACES_API_KEY` or `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` | `_utils.ts` (server) | Google Maps embed URL construction |

---

## Near-Term Direction

1. **`SocialSourceHealth` still has inline private helpers** (`Metric`, `SmallStat`, `formatDate`). Low priority — the page is internal only.

2. **`SubscribeForm` hardcodes `http://localhost:8000` as fallback.** Should fail explicitly when `NEXT_PUBLIC_API_BASE_URL` is unset rather than silently falling back to localhost in production.

3. **`shortPlaceName` strips `"Cajun Seafood"` by string match** (fix ⑤, not yet done). The right fix is a `display_name` field in the `places` table so the data layer owns name formatting, not the render layer.

4. **No loading states or error boundaries.** Pages return `null` or an empty state when the API is down. `Suspense` + `error.tsx` per route would give better UX.

5. **Detail page components are all Server Components.** If any section ever needs interactivity (e.g., expanding evidence, voting on a signal), extract that sub-tree into a `"use client"` component following the `CategoryFilterSection` pattern — don't mark the whole detail page as client.
