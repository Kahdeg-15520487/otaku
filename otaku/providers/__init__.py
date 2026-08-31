"""Model servers behind the OpenAI wire protocol.

`ProviderConfig` lives in `settings.providers` (provider settings are
settings) and is re-exported here as part of this package's own
signatures; the request log arrives as a sink protocol, and no file is
ever read or written by this package.
"""

from otaku.providers.base import (
    Chunk,
    CloudClient,
    DeclinedError,
    LocalSingleClient,
    ManagedClient,
    ModelInfo,
    OpenAIClient,
    Provider,
    RequestSink,
    Stats,
    Text,
    Thinking,
    WireMessage,
)
from otaku.providers.registry import CLIENTS, Registry, autoconfigure_providers
from otaku.settings.providers import ProviderConfig

__all__ = [
    "CLIENTS",
    "Chunk",
    "CloudClient",
    "DeclinedError",
    "LocalSingleClient",
    "ManagedClient",
    "ModelInfo",
    "OpenAIClient",
    "Provider",
    "ProviderConfig",
    "Registry",
    "RequestSink",
    "Stats",
    "Text",
    "Thinking",
    "WireMessage",
    "autoconfigure_providers",
]
