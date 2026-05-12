import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import escape
from typing import Optional
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class Subscriber:
    id: UUID
    email: str


@dataclass(frozen=True)
class ReportSignal:
    title: str
    summary: str
    city: str
    score: float
    place_name: str


@dataclass(frozen=True)
class Report:
    id: UUID
    title: str
    region: str
    week_start: str
    intro: str
    signals: list[ReportSignal]


def send_latest_digest() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to send digests.")

    with psycopg.connect(database_url) as conn:
        report = _latest_report(conn)
        subscribers = _active_subscribers(conn)
        sent_count = 0

        for subscriber in subscribers:
            subject = f"LocalSignal: {report.title} for {report.week_start}"
            text_body = _render_text(report)
            html_body = _render_html(report)
            result = _send_email(subscriber.email, subject, text_body, html_body)
            _record_delivery(
                conn=conn,
                subscriber=subscriber,
                report=report,
                subject=subject,
                result=result,
                body_preview=text_body[:1000],
            )
            sent_count += 1

        conn.commit()
        return sent_count


def _latest_report(conn) -> Report:
    row = conn.execute(
        """
        SELECT id, title, region, week_start::text AS week_start, intro
        FROM reports
        ORDER BY week_start DESC, created_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        raise RuntimeError("No report exists. Generate a weekly report first.")

    signal_rows = conn.execute(
        """
        SELECT
          s.title,
          s.summary,
          s.city,
          s.score::float AS score,
          p.name AS place_name
        FROM report_signals rs
        JOIN signals s ON s.id = rs.signal_id
        JOIN places p ON p.id = s.place_id
        WHERE rs.report_id = %s
        ORDER BY rs.rank ASC
        """,
        (row[0],),
    ).fetchall()

    return Report(
        id=row[0],
        title=row[1],
        region=row[2],
        week_start=row[3],
        intro=row[4],
        signals=[
            ReportSignal(
                title=signal[0],
                summary=signal[1],
                city=signal[2],
                score=signal[3],
                place_name=signal[4],
            )
            for signal in signal_rows
        ],
    )


def _active_subscribers(conn) -> list[Subscriber]:
    rows = conn.execute(
        """
        SELECT id, email
        FROM subscribers
        WHERE status = 'active'
        ORDER BY created_at ASC
        """
    ).fetchall()
    return [Subscriber(id=row[0], email=row[1]) for row in rows]


@dataclass(frozen=True)
class SendResult:
    status: str
    provider: str
    provider_message_id: Optional[str] = None
    error: Optional[str] = None


def _send_email(recipient: str, subject: str, text_body: str, html_body: str) -> SendResult:
    api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("EMAIL_FROM", "LocalSignal <digest@localsignal.local>")
    if not api_key:
        return SendResult(status="dry_run", provider="local")

    payload = json.dumps(
        {
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "text": text_body,
            "html": html_body,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "LocalSignal/0.1",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
            return SendResult(status="sent", provider="resend", provider_message_id=body.get("id"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return SendResult(status="failed", provider="resend", error=str(exc))


def _record_delivery(
    conn,
    subscriber: Subscriber,
    report: Report,
    subject: str,
    result: SendResult,
    body_preview: str,
) -> None:
    conn.execute(
        """
        INSERT INTO email_deliveries (
          subscriber_id,
          report_id,
          recipient_email,
          subject,
          status,
          provider,
          provider_message_id,
          error,
          body_preview
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            subscriber.id,
            report.id,
            subscriber.email,
            subject,
            result.status,
            result.provider,
            result.provider_message_id,
            result.error,
            body_preview,
        ),
    )


def _render_text(report: Report) -> str:
    lines = [
        report.title,
        f"Week of {report.week_start}",
        report.region,
        "",
        report.intro,
        "",
    ]
    for index, signal in enumerate(report.signals, start=1):
        lines.extend(
            [
                f"{index}. {signal.title}",
                f"{signal.place_name} · {signal.city} · score {signal.score:.1f}",
                signal.summary,
                "",
            ]
        )
    return "\n".join(lines).strip()


def _render_html(report: Report) -> str:
    items = "\n".join(
        f"""
        <li>
          <h2>{escape(signal.title)}</h2>
          <p><strong>{escape(signal.place_name)}</strong> · {escape(signal.city)} · score {signal.score:.1f}</p>
          <p>{escape(signal.summary)}</p>
        </li>
        """
        for signal in report.signals
    )
    return f"""
    <main>
      <h1>{escape(report.title)}</h1>
      <p><strong>Week of {escape(report.week_start)}</strong></p>
      <p>{escape(report.region)}</p>
      <p>{escape(report.intro)}</p>
      <ol>{items}</ol>
    </main>
    """
