"""Generation options and faithful source extraction without provider calls."""
import io,json,socket,unittest
from unittest.mock import patch
from app.ai.providers.compatible import CompatibleChatClient,post_json
from app.captures.ingestion import source_explanation
from app.errors import Unavailable

class InferenceTests(unittest.TestCase):
    def test_fast_profile_has_bounded_generation_and_model_specific_hint(self):
        response={'choices':[{'message':{'content':'{"ok":true}'}}]}
        with patch('app.ai.providers.compatible.post_json',return_value=response) as send:
            self.assertEqual(CompatibleChatClient('http://local','qwen',profile='qwen3_fast',max_tokens=512).generate('task','input'),'{"ok":true}')
            payload=send.call_args.args[1]
            self.assertEqual(payload['max_tokens'],512)
            self.assertIn('/no_think',payload['messages'][0]['content'])
        with patch('app.ai.providers.compatible.post_json',return_value=response) as send:
            CompatibleChatClient('http://local','other').generate('task','input')
            self.assertNotIn('/no_think',send.call_args.args[1]['messages'][0]['content'])

    def test_provider_timeout_is_not_reported_as_an_invalid_json_response(self):
        with patch('app.ai.providers.compatible.urlopen',side_effect=socket.timeout()):
            with self.assertRaisesRegex(Unavailable,'time limit'):post_json('http://localhost',{})

    def test_source_wording_preserves_qualifiers_and_negation(self):
        raw="I think binary uses two symbols, but I am not sure. I do not understand encoding."
        result=source_explanation(raw,['binary uses two symbols','I do not understand encoding'])
        self.assertIn('I think',result)
        self.assertIn('I am not sure',result)
        self.assertIn('I do not understand encoding',result)

    def test_additions_preserve_previous_wording(self):
        self.assertEqual(source_explanation('Those symbols are zero and one.',['Those symbols are zero and one.'],'I think binary uses two symbols.'),'I think binary uses two symbols.\n\nThose symbols are zero and one.')
