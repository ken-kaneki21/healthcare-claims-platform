import unittest
from unittest.mock import Mock

from healthcare.agent import provider_router


class ModelRoutingTests(unittest.TestCase):
    def test_model_selects_tool_and_application_selects_period(self):
        client = Mock()
        client.post.return_value.json.return_value = {
            "choices": [{"message": {"content": '{"operation":"pmpm"}'}}],
            "usage": {"total_tokens": 14},
        }
        route, usage = provider_router(
            client, "http://localhost:18765/v1/chat/completions", "", "local"
        )
        self.assertEqual(
            route("How much per member per month in 2025-12?"),
            {"operation": "pmpm", "month": "2025-12-01"},
        )
        self.assertEqual(usage["tokens"], 14)
        self.assertEqual(client.post.call_args.kwargs["headers"], {})

    def test_extra_model_arguments_fail_closed(self):
        client = Mock()
        route, usage = provider_router(
            client, "http://localhost:18765/v1/chat/completions", "", "local"
        )
        for forbidden in ('"tenant_id":2', '"paid_cents":999', '"month":"2024-05-01"'):
            client.post.return_value.json.return_value = {
                "choices": [
                    {"message": {"content": '{"operation":"close",' + forbidden + "}"}}
                ],
            }
            self.assertEqual(route("Paid for 2025-12?"), {"operation": "unsupported"})
        self.assertEqual(usage["invalid_responses"], 3)
