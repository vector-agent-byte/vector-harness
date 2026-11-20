"""Compatibility alias for :mod:`vector_harness.agent.assembly`."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("vector_harness.agent.assembly")
