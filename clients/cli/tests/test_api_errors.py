"""Transport failures are safe and actionable; secret validation input stays hidden."""
import json
import unittest
from oracle_cli.api import SDKBackend
from oracle_cli.types import ClientError
from oracle_sdk.exceptions import ApiException
from urllib3.exceptions import MaxRetryError


class ApiErrorTests(unittest.TestCase):
    def setUp(self): self.backend=SDKBackend('http://127.0.0.1:8000')
    def tearDown(self): self.backend.close()
    def test_validation_error_hides_rejected_secret(self):
        def fail(**kwargs):
            raise ApiException(status=422, body=json.dumps({'detail':[{'loc':['body','api_key'],'msg':'invalid value','input':'secret-do-not-print'}]}))
        with self.assertRaises(ClientError) as raised:
            self.backend.execute(fail)
        self.assertIn('body.api_key',str(raised.exception))
        self.assertNotIn('secret-do-not-print',str(raised.exception))
    def test_network_failure_has_connection_guidance(self):
        def fail(**kwargs): raise MaxRetryError(None,'/health')
        with self.assertRaises(ClientError) as raised: self.backend.execute(fail)
        self.assertIn('Start the local API',str(raised.exception))
