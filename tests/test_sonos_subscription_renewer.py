import asyncio
import os
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from sonos_app.subscription_renewer import PlaybackMetadataSubscriptionRenewer


class SubscriptionRenewerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_checks_immediately_and_repeats_after_five_minutes(self):
        with patch.dict(os.environ, {}, clear=True):
            renewer = PlaybackMetadataSubscriptionRenewer(Mock(), Mock())
        self.assertEqual(renewer.renew_after_seconds, 172800)
        events = Mock()
        check = AsyncMock(return_value={"due_count": 0, "failed": [], "reauthorization_required": False})
        sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
        events.attach_mock(check, "check")
        events.attach_mock(sleep, "sleep")

        with patch.object(renewer, "renew_due", check), patch(
            "sonos_app.subscription_renewer.asyncio.sleep", sleep
        ):
            with self.assertRaises(asyncio.CancelledError):
                await renewer.run_forever()

        self.assertEqual(events.mock_calls, [call.check(), call.sleep(300), call.check(), call.sleep(300)])

    async def test_worker_retries_on_the_next_interval_after_an_unexpected_failure(self):
        renewer = PlaybackMetadataSubscriptionRenewer(Mock(), Mock(), interval_seconds=30)
        result = {"due_count": 0, "failed": [], "reauthorization_required": False}
        with patch.object(renewer, "renew_due", side_effect=[RuntimeError("database unavailable"), result]) as check:
            with patch("sonos_app.subscription_renewer.asyncio.sleep", side_effect=[None, asyncio.CancelledError()]) as sleep:
                with patch("sonos_app.subscription_renewer.logger.exception"):
                    with self.assertRaises(asyncio.CancelledError):
                        await renewer.run_forever()

        self.assertEqual(check.await_count, 2)
        self.assertEqual(sleep.await_args_list, [call(30), call(30)])

    def test_existing_interval_and_renewal_configuration_is_preserved(self):
        with patch.dict(os.environ, {
            "SONOS_SUBSCRIPTION_RENEW_INTERVAL_SECONDS": "60",
            "SONOS_PLAYBACK_METADATA_RENEW_AFTER_SECONDS": "86400",
        }):
            renewer = PlaybackMetadataSubscriptionRenewer(Mock(), Mock())

        self.assertEqual(renewer.interval_seconds, 60)
        self.assertEqual(renewer.renew_after_seconds, 86400)
