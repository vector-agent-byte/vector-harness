"""Compatibility import for persisted child-agent traces."""

import sys

from vector_harness.agent.infrastructure import children as _implementation

sys.modules[__name__] = _implementation
