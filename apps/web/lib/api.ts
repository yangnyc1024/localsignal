import type { Report } from "@/lib/types";

const fallbackReport: Report = {
  id: "demo",
  title: "This Week Nearby",
  region: "Fort Lee / Edgewater / Palisades Park",
  week_start: new Date().toISOString().slice(0, 10),
  intro:
    "A quick read on the local places showing unusual momentum, behavior changes, or early quality shifts.",
  signals: [
    {
      id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      signal_type: "keyword_spike",
      title: "Han Bun Bakery is suddenly rising",
      summary:
        "Han Bun Bakery appears to be moving from a neighborhood bakery into a regional food stop, with salt bread driving the attention.",
      evidence: {
        review_velocity: 4.8,
        keywords: ["salt bread", "line", "Manhattan"],
        sources: ["google_reviews", "reddit"]
      },
      score: 91.5,
      city: "Fort Lee",
      week_start: new Date().toISOString().slice(0, 10),
      place: {
        id: "11111111-1111-1111-1111-111111111111",
        name: "Han Bun Bakery",
        category: "bakery",
        city: "Fort Lee",
        neighborhood: "Main Street"
      }
    },
    {
      id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      signal_type: "behavior_shift",
      title: "River Desk Cafe is becoming a remote-work hotspot",
      summary:
        "Weekday afternoon mentions increasingly describe quiet seating, outlets, and longer stays.",
      evidence: {
        review_velocity: 2.7,
        keywords: ["wifi", "outlet", "quiet"],
        sources: ["google_reviews", "yelp"]
      },
      score: 78.2,
      city: "Edgewater",
      week_start: new Date().toISOString().slice(0, 10),
      place: {
        id: "22222222-2222-2222-2222-222222222222",
        name: "River Desk Cafe",
        category: "cafe",
        city: "Edgewater",
        neighborhood: "River Road"
      }
    },
    {
      id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
      signal_type: "sentiment_shift",
      title: "Seoul Table has early signs of quality drift",
      summary:
        "Recent mentions remain busy but show a mild increase in service and wait-time complaints.",
      evidence: {
        keywords: ["wait", "service", "crowded"],
        sources: ["google_reviews"],
        average_sentiment: -0.18
      },
      score: 69.4,
      city: "Palisades Park",
      week_start: new Date().toISOString().slice(0, 10),
      place: {
        id: "33333333-3333-3333-3333-333333333333",
        name: "Seoul Table",
        category: "restaurant",
        city: "Palisades Park",
        neighborhood: "Broad Avenue"
      }
    }
  ]
};

export async function getLatestReport(): Promise<Report> {
  const baseUrl = process.env.INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    return fallbackReport;
  }

  try {
    const response = await fetch(`${baseUrl}/reports/latest`, {
      next: { revalidate: 60 }
    });

    if (!response.ok) {
      return fallbackReport;
    }

    return response.json();
  } catch {
    return fallbackReport;
  }
}
