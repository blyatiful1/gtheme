"""Make ``src/gtheme`` importable when the package is not installed.

The tests target the public contracts (color, manifest, paths) and import
those submodules directly, so they stay light and do not require the whole
package to be wired up.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
