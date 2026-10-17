# SmartClaim core (prototype, synthetic data)

## Status
| Part | State |
|---|---|
| `engine.py`: classifier (LLM hook + fallback), rules engine, mock adapters, idempotent dispatch/claims, audit log, metrics, seed | Built and tested (12 tests pass) |
| `api.py`: FastAPI routes for analyze, dispatch, claims draft/submit, metrics | Written and syntax-checked only. Not run, because fastapi could not be installed in the build sandbox |
| React/TypeScript widget, staff dashboard UI, review-queue UI, Docker, PostgreSQL/Alembic, photo upload, full RBAC and login, Plotly charts | Not built |

## Run
    python3 -m unittest discover -s tests          # engine tests, no dependencies
    pip install fastapi uvicorn                    # for the API layer
    uvicorn api:app --reload                       # docs at /docs
    curl -X POST localhost:8000/api/incidents/analyze -H "X-Session: demo-customer" \
         -H "Content-Type: application/json" -d '{"text":"Water is leaking from behind my dishwasher"}'

## Design points
- Customer identity comes from the server session, never from the request body.
- The LLM hook (`classify(text, provider)`) is schema-validated; invalid output or an error falls back to rules; the emergency rule can never be downgraded by a model.
- Outcomes: A emergency, B notify property manager, C draft claim, D human review or clarification. No code path decides coverage.
- Dispatch needs consent, is idempotent (one notification per incident), and a notification-routed incident never creates a claim.
- Metrics are SQL over stored rows. "routed_without_claim_prototype" counts delivered simulated notifications with no claim; it is not a savings figure.
- Adapters (`MockNotifier`, `MockClaims`) are the replacement points for real integrations.

## Web UI (added)
    python3 serve.py          # API + UI at http://127.0.0.1:8000, no dependencies except internet for React from cdnjs
    uvicorn api:app           # same contract through FastAPI (unverified here)
Customer widget (water-leak flow first) and staff dashboard live in `web/` (React 18 UMD, plain CSS, no build step). Embed: `SmartClaim.mount(el)`.
Demo sessions: `demo-customer`, `demo-handler`, `demo-admin` via the `X-Session` header (replace with real auth).

### API contract
| Endpoint | Role | Notes |
|---|---|---|
| POST /api/incidents/analyze `{text}` | customer | outcome A/B/C/D, safety text, rule IDs |
| POST /api/notifications/prepare `{incident_id}` | customer | editable draft message |
| POST /api/notifications/dispatch `{incident_id, consent, body?}` | customer | needs consent, idempotent, status from adapter |
| POST /api/claims/draft, /api/claims/submit `{incident_id, edits?}` | customer | submit never decides coverage |
| GET /api/incidents/{id} | customer (own) or staff | |
| GET /api/dashboard/metrics, /api/staff/incidents?status=&category=&urgency=&outcome= | staff | computed from stored rows |
| GET /api/staff/incidents/{id}; POST .../override `{outcome, reason}`; POST .../resolve | staff | audit trail on every change |
