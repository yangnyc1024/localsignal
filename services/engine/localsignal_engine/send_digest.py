from localsignal_engine.email import send_latest_digest


def main() -> None:
    delivery_count = send_latest_digest()
    print(f"Queued {delivery_count} digest deliveries.")


if __name__ == "__main__":
    main()
