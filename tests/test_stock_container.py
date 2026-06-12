import os
import unittest
from unittest.mock import patch

from app import MassiveConfig, build_stock_container


class MassiveConfigTests(unittest.TestCase):
    def test_from_env_loads_massive_settings(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MASSIVE_API_KEY": "secret",
                "MASSIVE_BASE_URL": "https://example.test/",
            },
            clear=True,
        ):
            config = MassiveConfig.from_env(load_env=False)

        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.base_url, "https://example.test/")


class StockContainerTests(unittest.TestCase):
    def test_build_stock_container_uses_supplied_board_and_config(self) -> None:
        board = object()
        config = MassiveConfig(
            api_key="secret",
            base_url="https://example.test/",
        )

        container = build_stock_container(board=board, config=config)

        self.assertIs(container.board, board)
        self.assertIs(container.config, config)
        self.assertEqual(container.massive_client.api_key, "secret")
        self.assertEqual(container.massive_client.base_url, "https://example.test")
