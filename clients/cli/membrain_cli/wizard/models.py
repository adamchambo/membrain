"""Provider-first prompts; keys are submitted to the server, never stored locally."""
import membrain_sdk as sdk
from ..terminal import select


class Cancelled(Exception):
    """Return to setup without submitting an unfinished configuration."""


def choose(read, title, options, write=print):
    """Use read/write IO to select one of the label/value options under title."""
    while True:
        choices = [(str(index), label) for index, (label, _) in enumerate(options, 1)]
        value = select(title, choices + [('0', 'Back')], read, write).strip()
        if value in ('0', '/back', '/menu', '/quit'):
            raise Cancelled
        if value.isascii() and value.isdecimal() and 1 <= int(value) <= len(options):
            return options[int(value) - 1][1]


def endpoint(read, secret, capability, write=print):
    """Collect provider URL/model/key using visible read, hidden secret, capability name and write output."""
    source = choose(read, 'Where will the model run?', (
        ('Local model', 'local'), ('Cloud provider', 'cloud'), ('Custom endpoint', 'custom')), write)
    path = 'chat/completions' if capability == 'chat' else 'embeddings'
    if source == 'local':
        base = choose(read, 'Local runtime (start it and load your model first)', (
            ('Ollama', 'http://localhost:11434/v1'),
            ('LM Studio', 'http://localhost:1234/v1')), write)
        base = read(f'Server address [{base}] (Enter to keep): ').strip() or base
        url = base.rstrip('/') + '/' + path
        key = None
    elif source == 'cloud':
        provider = choose(read, 'Cloud provider', (('OpenAI', 'openai'), ('Other OpenAI-compatible provider', 'other')), write)
        url = ('https://api.openai.com/v1/' + path if provider == 'openai' else
               read(f'Provider OpenAI-compatible {capability} endpoint URL (full URL): ').strip())
        key = None
    else:
        url = read(f'OpenAI-compatible {capability} endpoint URL (full URL): ').strip()
        key = None
    model = read('Model name (as installed or listed by your provider): ').strip()
    if source != 'local':
        key = secret('Provider API key' + (' (blank if not required)' if source == 'custom' else '') + ': ').strip() or None
        if source == 'cloud' and not key:
            raise ValueError('A cloud provider key is required')
    return url, model, key


def chat(read, secret, write=print):
    """Collect chat settings with visible read, hidden secret and write output."""
    url, model, key = endpoint(read, secret, 'chat', write)
    return sdk.Endpoint(url=url, model=model, api_key=key)


def embeddings(read, secret, write=print):
    """Collect embedding settings and vector profile using visible read, hidden secret and write output."""
    url, model, key = endpoint(read, secret, 'embeddings', write)
    revision = read('Pinned weights/deployment revision: ').strip()
    dimensions = int(read('Vector dimensions [768]: ').strip() or '768')
    preset = read('Use Nomic task prefixes? [y/N]: ').strip().lower() == 'y'
    document_prefix = 'search_document: ' if preset else read('Document task prefix (empty allowed): ')
    query_prefix = 'search_query: ' if preset else read('Query task prefix (empty allowed): ')
    profile = sdk.Profile(model=model, revision=revision, dimensions=dimensions,
                          document_prefix=document_prefix, query_prefix=query_prefix)
    return sdk.EmbeddingEndpoint(url=url, model=model, api_key=key, profile=profile)
