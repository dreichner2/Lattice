# Bundled PDF.js distribution

Lattice vendors selected runtime files from Mozilla PDF.js distribution
`pdfjs-dist` 6.2.108.

- Source package: `https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.2.108.tgz`
- npm integrity: `sha512-YxFb+SQcodN2rnX9Tn3dHYlqfb7NjlzzfONPpJd+AKoKtUjEdevTfbC07d5TcczzOK6261auRkP/M8OBHs9vFQ==`
- License: Apache-2.0; see `LICENSE` and the notices inside the asset folders.

The bundle retains the minified display API and worker, viewer primitives and
styles, CMaps, ICC profiles, standard fonts, and the OpenJPEG, JBIG2, and QCMS
Wasm decoders. QuickJS is intentionally excluded. Lattice does not construct a
PDF scripting manager, disables XFA, and serves the reader with a restrictive
same-origin Content Security Policy that does not allow `unsafe-eval`.
