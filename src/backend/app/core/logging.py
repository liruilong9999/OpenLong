import logging


def configure_logging(environment: str) -> None:
    level = logging.DEBUG if environment.lower() in {"dev", "development"} else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
