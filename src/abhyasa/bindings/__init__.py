# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport bindings. A2A is shipped; MCP travels via the mcp_server package."""

from abhyasa.bindings.a2a import (
    ABHYASA_EXTENSION_URI,
    A2AEndpoint,
    AbhyasaServiceRef,
    KindProfile,
    build_agent_card_extension,
    parse_agent_card_extension,
)

__all__ = [
    "ABHYASA_EXTENSION_URI",
    "A2AEndpoint",
    "AbhyasaServiceRef",
    "KindProfile",
    "build_agent_card_extension",
    "parse_agent_card_extension",
]
