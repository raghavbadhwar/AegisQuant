# v6 Dependency and Licence Review

## Evidence basis

- Lockfile: `uv.lock` revision `3`, SHA-256 `3b3ab44c5dd0753c7e7d4f15e2b5f1063fa966ca259ef3ea92d1e47dfd202718`.
- Locked inventory: `101` packages, including the project, all declared extras, and the dev group.
- Source/version evidence comes directly from `uv.lock`; registry artifact URLs and hashes remain in that file.
- Licence values are local installed-distribution metadata (`License-Expression`, then licence classifiers, then a short `License` field). They are evidence signals, not legal advice or an upstream licence-file audit.
- The two metadata gaps and the qtype upstream-review gap were checked against the exact licence files retained at the locked version or revision: [`colorama 0.4.6`](https://github.com/tartley/colorama/blob/0.4.6/LICENSE.txt), [`watchdog 6.0.0`](https://github.com/gorakhargosh/watchdog/blob/v6.0.0/LICENSE), and [`qtype 5277e43`](https://github.com/VernonOY/qtype/blob/5277e433a524742c80889af8982377f2bbf8d8f3/LICENSE).

## Decision and obligations

- v6 added no dependency and changed neither `pyproject.toml` nor `uv.lock`.
- Every row is approved only for the inherited local engineering/test baseline. Distribution or production release approval is `pending`.
- The locked inventory has no unresolved licence identifier after the pinned upstream-file review. Release remains gated until an accountable reviewer checks the complete upstream licence/NOTICE set and records distribution approval.
- Attribution text below is the minimum review obligation inferred from the metadata signal; the upstream licence controls.

| Package | Version | Locked source/revision | Licence metadata | Release decision | Attribution review |
| --- | --- | --- | --- | --- | --- |
| `aegisquant` | `0.1.0` | editable `.` | MIT | pending | Retain upstream copyright and licence notices |
| `altair` | `6.2.2` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `annotated-doc` | `0.0.5` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `annotated-types` | `0.8.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `anyio` | `4.14.2` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `attrs` | `26.1.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `blinker` | `1.9.0` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `certifi` | `2026.7.22` | https://pypi.org/simple | Mozilla Public License 2.0 (MPL 2.0) | pending | Retain MPL notices; review source-form obligations |
| `cfgv` | `3.5.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `charset-normalizer` | `3.4.9` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `click` | `8.4.2` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `colorama` | `0.4.6` | https://pypi.org/simple | BSD-3-Clause (upstream `0.4.6` licence) | pending | Retain the copyright notice, conditions, disclaimer, and non-endorsement restriction |
| `coverage` | `7.15.4` | https://pypi.org/simple | Apache-2.0 | pending | Retain licence and any applicable NOTICE |
| `distlib` | `0.4.3` | https://pypi.org/simple | Python Software Foundation License | pending | Retain upstream copyright and licence notices |
| `distro` | `1.9.0` | https://pypi.org/simple | Apache Software License | pending | Retain licence and any applicable NOTICE |
| `filelock` | `3.32.2` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `h11` | `0.16.0` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `httpcore` | `1.0.9` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `httptools` | `0.8.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `httpx` | `0.28.1` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `identify` | `2.6.19` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `idna` | `3.18` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `iniconfig` | `2.3.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `itsdangerous` | `2.2.0` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `jinja2` | `3.1.6` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `joblib` | `1.5.3` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `jsonpatch` | `1.33` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `jsonpointer` | `3.1.1` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `jsonschema` | `4.26.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `jsonschema-specifications` | `2025.9.1` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `langchain-core` | `1.5.3` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `langchain-protocol` | `0.0.18` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `langgraph` | `1.2.10` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `langgraph-checkpoint` | `4.2.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `langgraph-prebuilt` | `1.1.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `langgraph-sdk` | `0.4.2` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `langsmith` | `0.10.17` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `librt` | `0.15.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `markdown-it-py` | `4.2.0` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `markupsafe` | `3.0.3` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `mdurl` | `0.1.2` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `mypy` | `1.20.2` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `mypy-extensions` | `1.1.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `narwhals` | `2.24.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `nodeenv` | `1.10.0` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `numpy` | `2.5.1` | https://pypi.org/simple | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | pending | Retain notices for every applicable component licence |
| `orjson` | `3.11.9` | https://pypi.org/simple | MPL-2.0 AND (Apache-2.0 OR MIT) | pending | Retain MPL notices; review source-form obligations |
| `ormsgpack` | `1.12.2` | https://pypi.org/simple | Apache-2.0 OR MIT | pending | Retain licence and any applicable NOTICE |
| `packaging` | `26.3` | https://pypi.org/simple | Apache-2.0 OR BSD-2-Clause | pending | Retain licence and any applicable NOTICE |
| `pandas` | `2.3.3` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `pandas-stubs` | `2.3.3.260113` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `pathspec` | `1.1.1` | https://pypi.org/simple | Mozilla Public License 2.0 (MPL 2.0) | pending | Retain MPL notices; review source-form obligations |
| `pillow` | `12.3.0` | https://pypi.org/simple | MIT-CMU | pending | Retain upstream copyright and licence notices |
| `platformdirs` | `4.11.1` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `pluggy` | `1.6.0` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `pre-commit` | `4.6.1` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `protobuf` | `6.33.6` | https://pypi.org/simple | 3-Clause BSD License | pending | Retain upstream copyright and licence notices |
| `purgedcv` | `0.1.3` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `pyarrow` | `23.0.1` | https://pypi.org/simple | Apache-2.0 | pending | Retain licence and any applicable NOTICE |
| `pydantic` | `2.13.4` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `pydantic-core` | `2.46.4` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `pydeck` | `0.9.3` | https://pypi.org/simple | Apache License 2.0 | pending | Retain licence and any applicable NOTICE |
| `pygments` | `2.20.0` | https://pypi.org/simple | BSD-2-Clause | pending | Retain upstream copyright and licence notices |
| `pytest` | `9.1.1` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `pytest-cov` | `7.1.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `python-dateutil` | `2.9.0.post0` | https://pypi.org/simple | BSD License / Apache Software License | pending | Retain licence and any applicable NOTICE |
| `python-discovery` | `1.5.1` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `python-multipart` | `0.0.32` | https://pypi.org/simple | Apache-2.0 | pending | Retain licence and any applicable NOTICE |
| `pytz` | `2026.3.post1` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `pyyaml` | `6.0.3` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `qtype` | `0.1.2` | https://github.com/VernonOY/qtype.git?rev=5277e433a524742c80889af8982377f2bbf8d8f3#5277e433a524742c80889af8982377f2bbf8d8f3 | MIT (upstream `5277e43` licence) | pending | Retain the 2026 VernonOY copyright and MIT permission notice |
| `referencing` | `0.37.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `requests` | `2.34.2` | https://pypi.org/simple | Apache Software License | pending | Retain licence and any applicable NOTICE |
| `requests-toolbelt` | `1.0.0` | https://pypi.org/simple | Apache Software License | pending | Retain licence and any applicable NOTICE |
| `rich` | `14.3.4` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `rpds-py` | `2026.6.3` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `ruff` | `0.16.2` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `scikit-learn` | `1.9.0` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `scipy` | `1.18.0` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `shellingham` | `1.5.4` | https://pypi.org/simple | ISC License (ISCL) | pending | Retain upstream copyright and licence notices |
| `six` | `1.17.0` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `sniffio` | `1.3.1` | https://pypi.org/simple | MIT License / Apache Software License | pending | Retain licence and any applicable NOTICE |
| `starlette` | `1.3.1` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `streamlit` | `1.61.1` | https://pypi.org/simple | Apache-2.0 | pending | Retain licence and any applicable NOTICE |
| `tenacity` | `9.1.4` | https://pypi.org/simple | Apache Software License | pending | Retain licence and any applicable NOTICE |
| `threadpoolctl` | `3.6.0` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `toml` | `0.10.2` | https://pypi.org/simple | MIT License | pending | Retain upstream copyright and licence notices |
| `typer` | `0.27.1` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `types-pytz` | `2026.3.1.20260727` | https://pypi.org/simple | Apache-2.0 | pending | Retain licence and any applicable NOTICE |
| `types-pyyaml` | `6.0.12.20260724` | https://pypi.org/simple | Apache-2.0 | pending | Retain licence and any applicable NOTICE |
| `typing-extensions` | `4.16.0` | https://pypi.org/simple | PSF-2.0 | pending | Retain upstream copyright and licence notices |
| `typing-inspection` | `0.4.2` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `tzdata` | `2026.3` | https://pypi.org/simple | Apache-2.0 | pending | Retain licence and any applicable NOTICE |
| `urllib3` | `2.7.0` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `uuid-utils` | `0.17.0` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `uvicorn` | `0.52.1` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |
| `virtualenv` | `21.7.3` | https://pypi.org/simple | MIT | pending | Retain upstream copyright and licence notices |
| `watchdog` | `6.0.0` | https://pypi.org/simple | Apache-2.0 (upstream `v6.0.0` licence) | pending | Include Apache-2.0; preserve applicable notices and review any upstream NOTICE file |
| `websockets` | `15.0.1` | https://pypi.org/simple | BSD License | pending | Retain upstream copyright and licence notices |
| `xxhash` | `3.8.1` | https://pypi.org/simple | BSD-2-Clause | pending | Retain upstream copyright and licence notices |
| `zstandard` | `0.25.0` | https://pypi.org/simple | BSD-3-Clause | pending | Retain upstream copyright and licence notices |

## Remaining release items

- The `colorama 0.4.6`, `watchdog 6.0.0`, and `qtype 5277e43` identifiers and minimum notice obligations are now bound to their pinned upstream licence files; there are no remaining `UNKNOWN` licence rows.
- An accountable distribution reviewer must still inspect the complete upstream licence and NOTICE set for all 101 locked packages and record approval. This engineering review is not legal advice or release authority.
- No package in this inventory is approved by this document for empirical, investment, governance, or production use.
