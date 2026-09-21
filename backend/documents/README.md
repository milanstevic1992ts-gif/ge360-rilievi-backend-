# GE360 document conditions policy

All backend-generated customer-facing PDF reports must end with the mandatory
"NOTE E CONDIZIONI D'USO DEL PRESENTE ELABORATO" page.

The canonical wording lives in `backend/documents/usage_terms.py`.
Do not duplicate or silently shorten it in individual exporters. Future PDF or
document renderers must reuse the canonical terms (or a format-equivalent
renderer based on the same `USAGE_TERMS` source).

Current terms revision: 2026-09-21.
