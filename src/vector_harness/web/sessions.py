"""Compatibility import for the agent session repository."""

import sys

from vector_harness.agent.infrastructure import sessions as _implementation

sys.modules[__name__] = _implementation
