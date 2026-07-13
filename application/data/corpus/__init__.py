"""League Corpus (Session 0.5) — discovery crawl, selection/registry, and the gate.

Discovery is free (classification off the /user/.../leagues payload); harvest is what costs.
So: crawl broadly (discover.py) · select narrowly (select.py) · gate it (check_corpus.py).
This package SELECTS; it does not harvest game data (that is Session 4, which reads the manifest).
All network I/O routes through fetchers/_http.py; all parquet I/O through data_layer.
"""
