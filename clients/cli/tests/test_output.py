"""Normal learning screens present content instead of transport/provenance internals."""
import unittest
from membrain_cli.output import show
from membrain_cli.types import Context, Result


class OutputTests(unittest.TestCase):
    def test_learning_content_hides_sdk_metadata(self):
        lines=[]
        show(Result('Generated result',Context(),payload={'inputs':{'internal':'hidden'},'output':{'content':'A readable explanation.','verification':'not_verified'},'model_key':'hidden-model','prompt_version':'hidden-version'}),lines.append)
        output='\n'.join(lines)
        self.assertIn('A readable explanation.',output)
        self.assertIn('not factually verified',output)
        self.assertNotIn('hidden',output)
