# Cirquento — GitHub Pages site

This folder is published by the `pages` job in `.github/workflows/ci.yml`
(or via **Settings → Pages → Deploy from a branch → `main` / `/docs`**).

`index.html` is a fully self-contained, dependency-free build of the Cirquento
console running against a frozen demo dataset (812 BOM lines, product
`CM-4470-B`). No API key, no backend, no network calls — so the public demo can
never break because a service is down or a key expired.

- Light/dark theme follows the visitor's system preference.
- Responsive down to 360px.
- Every figure shown is the output of the offline pipeline run in `make demo`,
  so the marketing page and the product cannot drift apart.
