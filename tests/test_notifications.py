import os
import unittest
from unittest.mock import Mock, patch

import requests

from app import notifications


class NotificationTests(unittest.TestCase):
    def test_failure_policy_skips_successful_run(self):
        with patch.dict(os.environ, {'ANAPLAN_NOTIFICATION_POLICY': 'failure',
                                    'ANAPLAN_NOTIFICATION_WEBHOOK': 'https://example.invalid'},
                        clear=True), patch.object(notifications.requests, 'post') as post:
            self.assertEqual(notifications.notify([{'status': 'SUCCESS'}]), [])
            post.assert_not_called()

    def test_failure_message_contains_target_and_report(self):
        response = Mock()
        response.raise_for_status.return_value = None
        results = [{'status': 'FAILED', 'workspace': 'Feed', 'model': 'Plan',
                    'error': 'verification timed out'}]
        with patch.dict(os.environ, {
                'ANAPLAN_NOTIFICATION_POLICY': 'failure',
                'ANAPLAN_NOTIFICATION_WEBHOOK': 'https://example.invalid'}, clear=True), \
                patch.object(notifications.requests, 'post', return_value=response) as post:
            deliveries = notifications.notify(results, report_path='logs/result.json')
        payload = post.call_args.kwargs['json']
        self.assertIn('Feed / Plan: verification timed out', payload['text'])
        self.assertIn('logs/result.json', payload['text'])
        self.assertEqual(payload['counts']['failed'], 1)
        self.assertTrue(deliveries[0]['delivered'])

    def test_webhook_retries_then_succeeds(self):
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.dict(os.environ, {
                'ANAPLAN_NOTIFICATION_WEBHOOK': 'https://example.invalid',
                'ANAPLAN_NOTIFICATION_RETRY_ATTEMPTS': '3',
                'ANAPLAN_NOTIFICATION_RETRY_DELAY_SECONDS': '0'}, clear=True), \
                patch.object(notifications.requests, 'post', side_effect=[
                    requests.ConnectionError('temporary'), response]) as post:
            deliveries = notifications.notify([{'status': 'SUCCESS'}])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(deliveries[0]['attempts'], 2)

    def test_forced_health_notification_ignores_off_policy(self):
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.dict(os.environ, {
                'ANAPLAN_NOTIFICATION_POLICY': 'off',
                'ANAPLAN_NOTIFICATION_WEBHOOK': 'https://example.invalid'}, clear=True), \
                patch.object(notifications.requests, 'post', return_value=response) as post:
            notifications.notify([], message_override='test', force=True)
        post.assert_called_once()


if __name__ == '__main__':
    unittest.main()
