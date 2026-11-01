"""Consume the shared FIFO queue: python -m vestaboard.run_display_worker."""

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import math
import os
import signal
from threading import Event
import time
from uuid import uuid4

from redis.exceptions import LockError, RedisError

from app import BoardContainer, build_board_container
from vestaboard.message_queue import AttemptsExhausted, MessageClaim
from vestaboard.queued_message import QueuedMessage


logger = logging.getLogger(__name__)


class DisplayWorker:
    def __init__(self, board: BoardContainer, min_interval_s: float = 16) -> None:
        if not math.isfinite(min_interval_s) or min_interval_s < 15:
            raise ValueError("DISPLAY_MIN_INTERVAL_S must be at least 15 seconds.")
        self.board = board
        self.min_interval_s = min_interval_s
        self.stop_requested = Event()
        # Renew during waits; allow ample time for one bounded HTTP request.
        self.lease_timeout_s = max(60, 3 * board.vestaboard_messenger.timeout_s)
        self.lock = board.redis_data_store.display_lock(self.lease_timeout_s)
        self._claim: MessageClaim | None = None
        self._queued: QueuedMessage | None = None
        self._lease_token = ""
        board.vestaboard_messenger.write_guard = self._guard_write
        board.vestaboard_messenger.retry_sleep = self._sleep_with_lease

    def request_stop(self, *_args) -> None:
        logger.info("Stopping after the current message")
        self.stop_requested.set()

    def _renew_lease(self) -> None:
        # extend verifies the token; a former owner must not send or retry.
        self.lock.extend(self.lease_timeout_s, replace_ttl=True)

    def _sleep_with_lease(self, duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while True:
            self._renew_lease()
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                return
            time.sleep(min(1, remaining_s))

    @contextmanager
    def _guard_write(self, is_content_write: bool):
        self._renew_lease()
        store = self.board.redis_data_store
        if is_content_write:
            while (remaining_s := store.get_display_cooldown_s()) > 0:
                self._sleep_with_lease(remaining_s)
        self._renew_lease()
        assert self._claim is not None and self._queued is not None
        attempt = self.board.message_queue.start_attempt(
            self._claim, self._lease_token, is_content_write,
            self.board.vestaboard_messenger.retry_attempts,
        )
        logger.info(
            "Sending message %s source=%s operation=%s attempt=%d",
            self._queued.message_id, self._queued.message.source,
            "content" if is_content_write else "transition", attempt,
        )
        if is_content_write:
            # Reserve before sending. If killed mid-request, a successor waits
            # beyond lease expiry rather than assuming that nothing was sent.
            store.set_display_cooldown(self.lease_timeout_s + self.min_interval_s)
        try:
            yield
        finally:
            self._renew_lease()
            if is_content_write:
                # A timeout may still mean the board accepted the message.
                store.set_display_cooldown(self.min_interval_s)

    def process_next_message(self) -> bool:
        """Process one message while holding the lease, or report no available work."""
        lease_token = uuid4().hex
        if not self.lock.acquire(blocking=False, token=lease_token):
            return False
        self._lease_token = lease_token
        try:
            if self.stop_requested.is_set():
                return False
            claim = self.board.message_queue.claim(lease_token)
            if claim is None:
                return False
            self._claim = claim
            try:
                queued = QueuedMessage.from_json(claim.payload_json)
            except ValueError as exc:
                self.board.message_queue.fail(claim, lease_token, exc)
                logger.exception("Retained an invalid payload in the failed-message list")
                return True
            self._queued = queued
            delay_s = max(0, (datetime.now(timezone.utc) - queued.created_at).total_seconds())
            logger.info(
                "%s message %s source=%s queue_delay_s=%.1f content_attempts=%d transition_attempts=%d",
                "Recovered" if claim.recovered else "Claimed", queued.message_id,
                queued.message.source, delay_s, claim.content_attempts, claim.transition_attempts,
            )

            # The lease covers claim, transition, all send attempts, and acknowledgment.
            self._renew_lease()
            try:
                max_attempts = self.board.vestaboard_messenger.retry_attempts
                if max(claim.content_attempts, claim.transition_attempts) >= max_attempts:
                    raise AttemptsExhausted("HTTP retry limit reached before recovery")
                transition = self.board.display_manager.send(queued.message)
            except RedisError:
                # Without Redis/ownership we cannot safely continue sending.
                logger.exception("Display coordination failed for message %s", queued.message_id)
                raise
            except Exception as exc:
                self.board.message_queue.fail(claim, lease_token, exc, queued)
                logger.exception("Retained failed message %s; continuing", queued.message_id)
            else:
                # Redis state and flight deduplication commit with the acknowledgment.
                # If this fails, the in-flight record remains recoverable.
                self.board.message_queue.acknowledge(claim, lease_token, queued, transition)
                logger.info(
                    "Message sent: %s source=%s", queued.message_id, queued.message.source
                )
            return True
        finally:
            self._claim = None
            self._queued = None
            try:
                self.lock.release()
            except LockError:
                logger.warning("Display lease was lost before release")

    def run(self) -> None:
        logger.info("Display worker started; minimum interval %.1fs", self.min_interval_s)
        while not self.stop_requested.is_set():
            if not self.process_next_message():
                self.stop_requested.wait(1)
        logger.info("Display worker stopped")


def worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    board = build_board_container()
    min_interval_s = float(os.environ.get("DISPLAY_MIN_INTERVAL_S", "16"))
    display_worker = DisplayWorker(board, min_interval_s=min_interval_s)
    signal.signal(signal.SIGINT, display_worker.request_stop)
    signal.signal(signal.SIGTERM, display_worker.request_stop)
    display_worker.run()


if __name__ == "__main__":
    worker()
