# SPDX-License-Identifier: Apache-2.0
"""Shared pytest configuration for the ChaCha20 test suite.

Adds the test/ directory to sys.path so tests in subfolders (e.g. unit/)
can `import chacha20_ref` (the reference).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
