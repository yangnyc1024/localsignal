import logging
from localsignal_engine.email.send import send_latest_digest

logger = logging.getLogger(__name__)


def main() -> None:
    delivery_count = send_latest_digest()
    logger.info(f"Queued {delivery_count} digest deliveries.")


if __name__ == "__main__":
    main()
