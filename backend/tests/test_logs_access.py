"""OBS-2: what the access log of the HTTP server may say."""

import logging

from frontdesk import logs


def test_obs_2_the_access_log_leaves_out_the_query_string() -> None:
    """Meta's subscription check sends the webhook's verify token in the query string.

    On the first deployment that line reached the log workspace with the token in it.
    """
    logs.configure()
    seen: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    access = logging.getLogger("uvicorn.access")
    keeping = Keep()
    access.addHandler(keeping)
    try:
        # The format and the arguments uvicorn logs a request with.
        access.info(
            '%s - "%s %s HTTP/%s" %d',
            "100.100.0.132:59826",
            "GET",
            "/channels/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=s3cret",
            "1.1",
            200,
        )
    finally:
        access.removeHandler(keeping)

    assert seen == ['100.100.0.132:59826 - "GET /channels/whatsapp/webhook HTTP/1.1" 200']
