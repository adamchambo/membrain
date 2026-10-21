"""The product rename must retain private settings and existing portable bank files."""
import os
import unittest
from unittest.mock import patch
from app.config import setting, config_path
from app.portability.service import TABLES, validate


class BrandCompatibilityTests(unittest.TestCase):
    def test_old_private_settings_and_new_values(self):
        with patch.dict(os.environ, {}, clear=True), patch('app.config.read_config', return_value={'settings': {'ORACLE_CHAT_MODEL': 'existing'}}):
            self.assertEqual(setting('MEMBRAIN_CHAT_MODEL'), 'existing')
        with patch.dict(os.environ, {'ORACLE_CHAT_MODEL': 'old-env', 'MEMBRAIN_CHAT_MODEL': 'new-env'}, clear=True):
            self.assertEqual(setting('MEMBRAIN_CHAT_MODEL'), 'new-env')
            self.assertEqual(setting('ORACLE_CHAT_MODEL'), 'new-env')
        with patch.dict(os.environ, {'ORACLE_CHAT_MODEL': 'old-env'}, clear=True):
            self.assertEqual(setting('MEMBRAIN_CHAT_MODEL'), 'old-env')

    def test_empty_task_prefix_and_legacy_config_location(self):
        with patch.dict(os.environ, {'MEMBRAIN_EMBEDDING_QUERY_PREFIX': '', 'ORACLE_CONFIG_FILE': '/tmp/legacy-config.json'}, clear=True):
            self.assertEqual(setting('MEMBRAIN_EMBEDDING_QUERY_PREFIX', 'fallback', allow_empty=True), '')
            self.assertEqual(str(config_path()), '/tmp/legacy-config.json')

    def test_legacy_portable_format_still_loads(self):
        for name in ('oracle.bank.v1', 'membrain.bank.v1'):
            validate({'format': name, 'tables': {table: [] for table in TABLES}})
