import type { AlwaysHotPlace, Report, SignalDetail, SocialSourceRun } from "@/lib/types";

const API_BASE_URL = process.env.INTERNAL_API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;

export async function getLatestReport(): Promise<Report | null> {
  if (!API_BASE_URL) {
    return null;
  }

  const response = await fetch(`${API_BASE_URL}/reports/latest`, {
    cache: "no-store"
  });

  if (!response.ok) {
    return null;
  }

  return response.json();
}

export async function getSignalDetail(slug: string): Promise<SignalDetail | null> {
  if (!API_BASE_URL) {
    return null;
  }

  const response = await fetch(`${API_BASE_URL}/signals/${encodeURIComponent(slug)}`, {
    cache: "no-store"
  });

  if (!response.ok) {
    return null;
  }

  return response.json();
}

export async function getAlwaysHotPlaces(): Promise<AlwaysHotPlace[]> {
  if (!API_BASE_URL) {
    return [];
  }

  const response = await fetch(`${API_BASE_URL}/api/baseline/always-hot`, {
    cache: "no-store"
  });

  if (!response.ok) {
    return [];
  }

  return response.json();
}


export async function getSocialSourceRuns(): Promise<SocialSourceRun[]> {
  if (!API_BASE_URL) {
    return [];
  }

  const response = await fetch(`${API_BASE_URL}/api/source-health/social?limit=8`, {
    cache: "no-store"
  });

  if (!response.ok) {
    return [];
  }

  return response.json();
}
