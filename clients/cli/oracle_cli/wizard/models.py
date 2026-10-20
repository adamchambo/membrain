"""Collect provider settings. Keys are submitted to the server, never stored locally."""
import oracle_sdk as sdk


def chat(read, secret):
    """Use read for visible prompts and secret for the provider key."""
    url = read('Chat-completions endpoint URL: ').strip()
    model = read('Served model name: ').strip()
    key = secret('LLM provider API key (blank for local model): ') or None
    return sdk.Endpoint(url=url, model=model, api_key=key)


def embeddings(read, secret):
    """Collect endpoint, key and explicit vector-profile parameters through supplied IO."""
    url = read('Embedding endpoint URL: ').strip()
    model = read('Served embedding model name: ').strip()
    revision = read('Pinned weights/deployment revision: ').strip()
    dimensions = int(read('Vector dimensions [768]: ').strip() or '768')
    preset = read('Use Nomic task prefixes? [y/N]: ').strip().lower() == 'y'
    document_prefix = 'search_document: ' if preset else read('Document task prefix (empty allowed): ')
    query_prefix = 'search_query: ' if preset else read('Query task prefix (empty allowed): ')
    key = secret('Embedding provider API key (blank for local model): ') or None
    profile = sdk.Profile(model=model, revision=revision, dimensions=dimensions,
                          document_prefix=document_prefix, query_prefix=query_prefix)
    return sdk.EmbeddingEndpoint(url=url, model=model, api_key=key, profile=profile)
