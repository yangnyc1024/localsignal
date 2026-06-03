import os
import re
import urllib.parse
from html import escape

from .models import Report
from .models import ReportSignal


def _display_place_name(name: str, max_len: int = 40) -> str:
    """Return a clean, Latin-only, truncated place name for display."""
    # Strip CJK characters
    latin = re.sub(r"[가-힯ᄀ-ᇿ㄰-㆏一-鿿぀-ヿ＀-￯]+", "", name).strip()
    # Unwrap if parens wrap the whole remaining string
    latin = re.sub(r"^\s*\(\s*(.*?)\s*\)\s*$", r"\1", latin).strip()
    # Strip leading/trailing punctuation artifacts
    latin = re.sub(r"^[|/\-,\s]+|[|/\-,\s]+$", "", latin).strip()
    cleaned = re.sub(r"\s*\|.*$", "", (latin or name)).strip()
    cleaned = re.sub(r"\s*-\s*Cajun Seafood.*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+Nj\b", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= max_len:
        return cleaned
    m = re.search(r" [-|/] ", cleaned)
    if m and 8 < m.start() <= max_len:
        return cleaned[: m.start()].strip()
    return cleaned[:max_len].rstrip() + "…"


def _label_for(signal_type: str) -> str:
    labels = {
        "keyword_spike": "Keyword spike",
        "behavior_shift": "Behavior shift",
        "sentiment_shift": "Sentiment shift",
        "new_place_detected": "New place",
        "review_velocity_spike": "Review velocity spike",
    }
    return labels.get(signal_type, "Local signal")


def _briefing_summary(report: Report) -> str:
    if not report.signals:
        return "No published food signals are available this week."
    top = report.signals[0]
    neighborhoods = sorted({signal.place_neighborhood or signal.city for signal in report.signals})
    categories = sorted({signal.place_category for signal in report.signals})
    return (
        f"This week's strongest signal is {top.place_name}, led by {_label_for(top.signal_type).lower()} evidence. "
        f"The feed spans {', '.join(neighborhoods[:3])} across {', '.join(categories[:3])}, with confidence weighted by source diversity and recent evidence."
    )


def _has_briefing(report: Report) -> bool:
    briefing = report.briefing or {}
    return bool(briefing.get("title") and briefing.get("subtitle") and briefing.get("why_it_matters"))


def _signal_text(signal: ReportSignal) -> str:
    keywords = " ".join(str(keyword) for keyword in signal.evidence.get("keywords", []))
    return " ".join(
        [
            signal.title,
            signal.summary,
            signal.place_name,
            signal.place_category,
            signal.signal_type,
            keywords,
        ]
    ).lower()


def _matches_korean(signal: ReportSignal) -> bool:
    text = _signal_text(signal)
    return any(term in text for term in ["korean", "tofu", "bbq", "banchan", "so gong dong", "bcd"])


def _matches_cafe(signal: ReportSignal) -> bool:
    text = _signal_text(signal)
    return any(term in text for term in ["cafe", "coffee", "kuppi", "remote", "wifi", "outlet"])


def _matches_dessert(signal: ReportSignal) -> bool:
    text = _signal_text(signal)
    return any(term in text for term in ["dessert", "bakery", "cake", "pastry", "matcha", "sweet", "cream"])


def _matches_late_night(signal: ReportSignal) -> bool:
    text = _signal_text(signal)
    return any(term in text for term in ["late night", "late-night", "after 9", "midnight", "night"])


def _matches_opening(signal: ReportSignal) -> bool:
    text = _signal_text(signal)
    return any(term in text for term in ["opening", "new menu", "soft opening", "new place"])


def _is_strong_signal(signal: ReportSignal) -> bool:
    source_count = int(signal.evidence.get("source_count") or len(signal.evidence.get("sources", [])) or 0)
    mention_count = int(signal.evidence.get("current_mention_count") or signal.evidence.get("mention_count") or 0)
    return signal.score >= 70 and source_count >= 2 and mention_count >= 2


def _evidence_assessment(signal: ReportSignal) -> str:
    source_count = int(signal.evidence.get("source_count") or len(signal.evidence.get("sources", [])) or 0)
    mention_count = int(signal.evidence.get("current_mention_count") or signal.evidence.get("mention_count") or 0)
    if source_count >= 2 and mention_count >= 3:
        return f"Strong support: {mention_count} recent mentions across {source_count} sources."
    if mention_count >= 2:
        return f"Developing support: {mention_count} recent mentions, with evidence still building."
    return "Evidence coverage is still building for this signal."


def _confidence(signal: ReportSignal) -> str:
    source_count = int(signal.evidence.get("source_count") or len(signal.evidence.get("sources", [])) or 0)
    mention_count = int(signal.evidence.get("current_mention_count") or 0)
    if source_count >= 2 and mention_count >= 3:
        return "High"
    if source_count >= 2 or mention_count >= 2:
        return "Medium"
    return "Low"


def _maps_url(signal: ReportSignal) -> str:
    query = urllib.parse.quote_plus(f"{signal.place_name} {signal.city} NJ")
    return f"https://www.google.com/maps/search/{query}"


def _category_statuses(report: Report) -> list:
    channels = [
        ("Korean Food", _matches_korean),
        ("Cafes", _matches_cafe),
        ("Desserts", _matches_dessert),
        ("Late-night", _matches_late_night),
        ("New Opening", _matches_opening),
    ]
    statuses = []
    for label, matcher in channels:
        matched = [signal for signal in report.signals if matcher(signal)]
        strong = [signal for signal in matched if _is_strong_signal(signal)]
        if strong:
            top = max(strong, key=lambda signal: signal.score)
            statuses.append(
                {
                    "label": label,
                    "status": "Strong signal",
                    "detail": f"{top.place_name} is carrying the clearest weekly evidence.",
                    "color": "#4f6b5d",
                }
            )
        elif matched:
            top = max(matched, key=lambda signal: signal.score)
            statuses.append(
                {
                    "label": label,
                    "status": "Watching",
                    "detail": f"Early movement around {top.place_name}, but evidence is still developing.",
                    "color": "#9a563c",
                }
            )
        else:
            statuses.append(
                {
                    "label": label,
                    "status": "No strong signal detected",
                    "detail": "Still monitoring new mentions, wait-time changes, and cross-platform activity.",
                    "color": "rgba(22,32,29,0.52)",
                }
            )
    return statuses


def _category_status_text(report: Report) -> list:
    return [f"- {status['label']}: {status['status']} — {status['detail']}" for status in _category_statuses(report)]


def _category_status_html(report: Report) -> str:
    items = "\n".join(
        f"""
        <tr>
          <td style="padding:9px 8px 9px 0;border-top:1px solid #e5dccf;font-size:14px;line-height:20px;font-weight:700;color:#16201d;">{escape(status['label'])}</td>
          <td style="padding:9px 8px;border-top:1px solid #e5dccf;font-size:13px;line-height:19px;font-weight:700;color:{escape(status['color'])};">{escape(status['status'])}</td>
          <td style="padding:9px 0 9px 8px;border-top:1px solid #e5dccf;font-size:13px;line-height:19px;color:rgba(22,32,29,0.68);">{escape(status['detail'])}</td>
        </tr>
        """
        for status in _category_statuses(report)
    )
    return f"""
      <div style="margin-top:18px;padding:15px;border:1px solid #ddd4c6;border-radius:8px;background:rgba(255,255,255,0.88);">
        <div style="font-size:13px;line-height:18px;font-weight:700;text-transform:uppercase;color:#4f6b5d;">Category watch</div>
        <div style="margin-top:5px;font-size:13px;line-height:20px;color:rgba(22,32,29,0.66);">Signals are only generated when evidence clears the weekly threshold.</div>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px;border-collapse:collapse;">
          {items}
        </table>
      </div>
    """


def _render_briefing_html(report: Report) -> str:
    briefing = report.briefing
    web_base = os.getenv("WEB_BASE_URL", "http://localhost:3000")

    # Build slug lookup from signals
    slug_by_name: dict = {}
    food_by_name: dict = {}
    known_for_by_name: dict = {}
    for sig in report.signals:
        if sig.slug:
            slug_by_name[sig.place_name] = sig.slug
        if sig.food_signal and sig.food_signal.get("primary_pull"):
            food_by_name[sig.place_name] = sig.food_signal
        if sig.place_profile and sig.place_profile.get("known_for"):
            known_for_by_name[sig.place_name] = sig.place_profile["known_for"]

    def _place_row(place: dict) -> str:
        name = _display_place_name(str(place.get("name") or ""))
        area = str(place.get("area") or "")
        reason = str(place.get("reason") or "")
        slug = slug_by_name.get(name)
        fs = food_by_name.get(name, {})
        pull = str(fs.get("primary_pull") or "").strip()
        flavor = str(fs.get("flavor_cue") or "").strip()
        known_for = known_for_by_name.get(name, "")
        detail_url = f"{web_base}/signal/{slug}" if slug else web_base

        food_pill = ""
        if pull:
            food_pill = f"""<div style="margin-top:8px;display:inline-block;padding:4px 10px;border-radius:20px;background:#eef3ef;font-size:12px;line-height:18px;font-weight:700;color:#4f6b5d;">
              🍽 {escape(pull)}{(' · ' + escape(flavor)) if flavor else ''}
            </div>"""

        known_for_line = ""
        if known_for:
            # Truncate to keep email concise
            short = known_for[:120] + ("…" if len(known_for) > 120 else "")
            known_for_line = f"""<div style="margin-top:6px;font-size:13px;line-height:19px;color:rgba(22,32,29,0.58);font-style:italic;">{escape(short)}</div>"""

        return f"""
        <tr>
          <td style="padding:14px 14px 14px 0;border-top:1px solid #e5dccf;vertical-align:top;width:44%;">
            <a href="{escape(detail_url)}" style="font-size:15px;line-height:21px;font-weight:700;color:#16201d;text-decoration:none;">{escape(name)}</a>
            <div style="margin-top:2px;font-size:12px;line-height:18px;color:rgba(22,32,29,0.50);">{escape(area)}</div>
            {food_pill}
            {known_for_line}
          </td>
          <td style="padding:14px 0;border-top:1px solid #e5dccf;vertical-align:top;font-size:14px;line-height:22px;color:rgba(22,32,29,0.72);">
            {escape(reason)}
            {"<br><a href='" + escape(detail_url) + "' style='display:inline-block;margin-top:10px;font-size:13px;font-weight:700;color:#4f6b5d;text-decoration:none;'>Read signal →</a>" if slug else ""}
          </td>
        </tr>
        """

    def _read_card(read: dict) -> str:
        title = str(read.get("title") or "")
        summary = str(read.get("summary") or "")
        slug = str(read.get("signal_slug") or "")
        detail_url = f"{web_base}/signal/{slug}" if slug else web_base
        return f"""
        <article style="margin:0 0 12px 0;padding:18px;border:1px solid #ddd4c6;border-radius:8px;background:rgba(255,255,255,0.9);">
          <h2 style="margin:0;font-size:17px;line-height:24px;font-weight:700;color:#16201d;">
            {"<a href='" + escape(detail_url) + "' style='color:#16201d;text-decoration:none;'>" + escape(title) + "</a>" if slug else escape(title)}
          </h2>
          <p style="margin:8px 0 0 0;font-size:14px;line-height:22px;color:rgba(22,32,29,0.70);">{escape(summary)}</p>
          {"<a href='" + escape(detail_url) + "' style='display:inline-block;margin-top:10px;font-size:13px;font-weight:700;color:#4f6b5d;text-decoration:none;'>Read signal →</a>" if slug else ""}
        </article>
        """

    places_html = "\n".join(_place_row(p) for p in (briefing.get("places_involved") or [])[:4])
    reads_html = "\n".join(_read_card(r) for r in (briefing.get("supporting_reads") or [])[:3])

    return f"""
    <!doctype html>
    <html>
      <body style="margin:0;padding:0;background:#f7f3eb;font-family:Arial,Helvetica,sans-serif;color:#16201d;">
        <div style="display:none;max-height:0;overflow:hidden;color:#f7f3eb;">
          {escape(str(briefing.get("subtitle") or report.intro))}
        </div>
        <main style="width:100%;background:#f7f3eb;padding:28px 12px;">
          <div style="max-width:720px;margin:0 auto;">
            <header style="padding:0 0 26px 0;border-bottom:1px solid #ddd4c6;">
              <div style="display:inline-block;padding:7px 11px;border:1px solid #ddd4c6;border-radius:6px;background:rgba(255,255,255,0.82);font-size:14px;line-height:18px;font-weight:700;color:#4f6b5d;">
                LocalSignal
              </div>
              <h1 style="max-width:640px;margin:16px 0 0 0;font-size:38px;line-height:44px;font-weight:700;color:#16201d;">{escape(str(briefing.get("title") or report.title))}</h1>
              <p style="max-width:610px;margin:15px 0 0 0;font-size:17px;line-height:27px;color:rgba(22,32,29,0.75);">{escape(str(briefing.get("subtitle") or report.intro))}</p>
              <p style="max-width:610px;margin:16px 0 0 0;padding-left:14px;border-left:2px solid #4f6b5d;font-size:15px;line-height:24px;color:rgba(22,32,29,0.72);">{escape(str(briefing.get("why_it_matters") or ""))}</p>
              <div style="margin-top:18px;font-size:14px;line-height:20px;color:rgba(22,32,29,0.60);">Week of {escape(report.week_start)} · {escape(report.region)}</div>
            </header>

            <section style="padding-top:22px;">
              <h2 style="margin:0 0 8px 0;font-size:18px;line-height:24px;font-weight:700;color:#16201d;">Places involved</h2>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                {places_html}
              </table>
            </section>

            <section style="padding-top:28px;">
              <h2 style="margin:0 0 12px 0;font-size:18px;line-height:24px;font-weight:700;color:#16201d;">Also worth noting</h2>
              {reads_html}
            </section>

            <footer style="margin-top:32px;padding-top:20px;border-top:1px solid #ddd4c6;font-size:13px;line-height:20px;color:rgba(22,32,29,0.50);">
              <a href="{escape(web_base)}" style="color:#4f6b5d;font-weight:700;text-decoration:none;">View full report online →</a>
            </footer>
          </div>
        </main>
      </body>
    </html>
    """


def _render_text(report: Report) -> str:
    if _has_briefing(report):
        briefing = report.briefing
        lines = [
            str(briefing["title"]),
            f"Week of {report.week_start}",
            report.region,
            "",
            str(briefing["subtitle"]),
            "",
            "Why it matters",
            str(briefing["why_it_matters"]),
            "",
            "Places involved",
        ]
        for place in briefing.get("places_involved") or []:
            lines.append(f"- {place.get('name')} · {place.get('area')}: {place.get('reason')}")
        supporting = briefing.get("supporting_reads") or []
        if supporting:
            lines.extend(["", "Also worth noting"])
            for read in supporting:
                lines.append(f"- {read.get('title')}: {read.get('summary')}")
        return "\n".join(lines).strip()

    lines = [
        report.title,
        f"Week of {report.week_start}",
        report.region,
        "",
        report.intro,
        "",
        _briefing_summary(report),
        "",
        "Category watch",
        *_category_status_text(report),
        "",
    ]
    for index, signal in enumerate(report.signals, start=1):
        lines.extend(
            [
                f"{index}. {signal.title}",
                f"{signal.place_name} · {signal.city} · score {signal.score:.1f}",
                signal.momentum_driver or signal.summary,
                "",
            ]
        )
    return "\n".join(lines).strip()


def _render_html(report: Report) -> str:
    if _has_briefing(report):
        return _render_briefing_html(report)

    items = "\n".join(
        f"""
        <article style="margin:0 0 14px 0;padding:22px;border:1px solid #ddd4c6;border-radius:8px;background:rgba(255,255,255,0.92);box-shadow:0 1px 2px rgba(22,32,29,0.06);">
          <div style="font-size:12px;line-height:18px;font-weight:700;text-transform:uppercase;color:#4f6b5d;">
            #{index} &nbsp; {escape(_label_for(signal.signal_type))} &nbsp; {escape(signal.city)}
          </div>
          <h2 style="margin:10px 0 0 0;font-size:23px;line-height:29px;font-weight:700;color:#16201d;">{escape(signal.title)}</h2>
          <p style="margin:12px 0 0 0;font-size:15px;line-height:24px;color:rgba(22,32,29,0.74);">{escape(signal.momentum_driver or signal.summary)}</p>
          <p style="margin:8px 0 0 0;font-size:13px;line-height:20px;color:rgba(22,32,29,0.58);">{escape(_evidence_assessment(signal))}</p>

          <div style="margin-top:18px;padding:14px;border-radius:7px;background:#f7f3eb;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
              <tr>
                <td style="padding:0 12px 0 0;vertical-align:top;">
                  <div style="font-size:11px;line-height:16px;font-weight:700;text-transform:uppercase;color:rgba(22,32,29,0.48);">Place</div>
                  <div style="margin-top:3px;font-size:15px;line-height:21px;font-weight:700;color:#16201d;">{escape(signal.place_name)}</div>
                  <div style="margin-top:2px;font-size:13px;line-height:19px;text-transform:capitalize;color:rgba(22,32,29,0.66);">{escape(signal.place_category)}</div>
                </td>
                <td style="padding:0 12px;vertical-align:top;">
                  <div style="font-size:11px;line-height:16px;font-weight:700;text-transform:uppercase;color:rgba(22,32,29,0.48);">Area</div>
                  <div style="margin-top:3px;font-size:14px;line-height:21px;color:#16201d;">{escape(signal.place_neighborhood or signal.city)}</div>
                </td>
                <td align="right" style="padding:0;vertical-align:top;">
                  <div style="font-size:11px;line-height:16px;font-weight:700;text-transform:uppercase;color:rgba(22,32,29,0.48);">Score</div>
                  <div style="margin-top:3px;font-size:18px;line-height:22px;font-weight:700;color:#16201d;">{signal.score:.1f}</div>
                  <div style="margin-top:4px;font-size:12px;line-height:17px;font-weight:700;color:#4f6b5d;">{escape(signal.confidence_level or _confidence(signal))} confidence</div>
                  <a href="{escape(_maps_url(signal))}" style="display:inline-block;margin-top:8px;font-size:13px;line-height:18px;font-weight:700;color:#9a563c;text-decoration:none;">Open Maps</a>
                </td>
              </tr>
            </table>
          </div>
        </article>
        """
        for index, signal in enumerate(report.signals, start=1)
    )
    return f"""
    <!doctype html>
    <html>
      <body style="margin:0;padding:0;background:#f7f3eb;font-family:Arial,Helvetica,sans-serif;color:#16201d;">
        <div style="display:none;max-height:0;overflow:hidden;color:#f7f3eb;">
          {escape(report.intro)}
        </div>
        <main style="width:100%;background:#f7f3eb;padding:28px 12px;">
          <div style="max-width:720px;margin:0 auto;">
            <header style="padding:0 0 26px 0;border-bottom:1px solid #ddd4c6;">
              <div style="display:inline-block;padding:7px 11px;border:1px solid #ddd4c6;border-radius:6px;background:rgba(255,255,255,0.82);font-size:14px;line-height:18px;font-weight:700;color:#4f6b5d;">
                LocalSignal
              </div>
              <h1 style="max-width:620px;margin:16px 0 0 0;font-size:42px;line-height:46px;font-weight:700;color:#16201d;">{escape(report.title)}</h1>
              <p style="max-width:610px;margin:15px 0 0 0;font-size:17px;line-height:27px;color:rgba(22,32,29,0.75);">{escape(report.intro)}</p>
              <p style="max-width:610px;margin:12px 0 0 0;font-size:15px;line-height:24px;color:rgba(22,32,29,0.68);">{escape(_briefing_summary(report))}</p>
              {_category_status_html(report)}
              <div style="margin-top:18px;padding:15px;border:1px solid #ddd4c6;border-radius:8px;background:rgba(255,255,255,0.88);">
                <div style="font-size:14px;line-height:20px;font-weight:700;color:#16201d;">Week of {escape(report.week_start)}</div>
                <div style="margin-top:5px;font-size:14px;line-height:20px;color:rgba(22,32,29,0.66);">{escape(report.region)}</div>
                <div style="margin-top:9px;font-size:14px;line-height:20px;font-weight:700;color:#4f6b5d;">{len(report.signals)} signals ranked</div>
              </div>
            </header>
            <section style="padding-top:18px;">
              {items}
            </section>
          </div>
        </main>
      </body>
    </html>
    """
