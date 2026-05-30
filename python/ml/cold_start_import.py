from __future__ import annotations

import sys

from python.ml.cold_start import main


if __name__ == "__main__":
    print(
        "[cold-start] python.ml.cold_start_import is deprecated; "
        "delegating to python.ml.cold_start to keep event_id format consistent.",
        file=sys.stderr,
    )
    main()
