# Vendored KaTeX

Lattice vendors the browser distribution from `katex@0.18.4` so Study Lab can
render mathematics without a network request.

- Package: <https://www.npmjs.com/package/katex/v/0.18.4>
- Registry archive: <https://registry.npmjs.org/katex/-/katex-0.18.4.tgz>
- Archive SHA-256: `0090b1ebccc77d1402ec95e85ee539e1da514d6cd6934156c00baf39dcb0e3aa`
- Included: `dist/katex.min.css`, `dist/katex.min.js`, and `dist/fonts/`
- License: MIT; retained in [`LICENSE`](LICENSE)

The Lattice UI calls KaTeX with `trust: false`. No KaTeX auto-render or plugin
scripts are bundled.
