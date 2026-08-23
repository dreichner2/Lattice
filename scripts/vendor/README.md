# Vendored Python dependencies

`pypdf` 6.15.0 is vendored here so Lattice can extract searchable PDF text in
the macOS app, the standalone Windows service, and source checkouts without
changing the user's Python installation.

- Project: <https://pypi.org/project/pypdf/6.15.0/>
- License: BSD-3-Clause (see `pypdf-LICENSE`)
- Wheel SHA-256: `14e001d6504822cb1ca9c7ed9a69bccb320f59b320730f55af804361abe4d5ee`

Only the `pypdf/` package from the universal wheel is retained; build metadata
is intentionally omitted.
