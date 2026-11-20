"""Compatibility import for the transport-independent run coordinator."""

import sys

from vector_harness.agent.application import runs as _implementation

sys.modules[__name__] = _implementation
