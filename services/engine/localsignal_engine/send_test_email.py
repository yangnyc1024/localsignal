import json
import os
import urllib.error
import urllib.request


def main() -> None:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is required.")

    recipient = os.getenv("TEST_EMAIL_TO", "linyangnyc@gmail.com")
    sender = os.getenv("EMAIL_FROM", "onboarding@resend.dev")
    subject = os.getenv("TEST_EMAIL_SUBJECT", "Hello World")
    html = os.getenv("TEST_EMAIL_HTML", "<p>Congrats on sending your <strong>first email</strong>!</p>")

    payload = json.dumps(
        {
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "html": html,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"))
        raise


if __name__ == "__main__":
    main()
