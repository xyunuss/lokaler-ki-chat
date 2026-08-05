# Vendored libraries

Checked in on purpose. The whole point of this project is that it runs without
a network connection, and loading these from a CDN meant an offline machine got
no markdown rendering and no syntax highlighting.

| File | Version | License | Source |
| --- | --- | --- | --- |
| `marked.min.js` | 4.3.0 | MIT | https://github.com/markedjs/marked |
| `highlight.min.js` | 11.9.0 | BSD-3-Clause | https://github.com/highlightjs/highlight.js |

marked is pinned to the 4.x line because 5.0 removed the `highlight` option
this app uses.

Syntax colours are not vendored: they live in `static/css/app.css` and are
built from the app's own theme variables, so highlighting follows the light
and dark theme instead of shipping two more stylesheets.

To update, replace the file and adjust the version above.
