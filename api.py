"""FastAPI wrapper over handlers.py (same contract as serve.py). Not executed in the build sandbox."""
import os
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import engine as E, handlers
app = FastAPI(title="SmartClaim (prototype, synthetic data)")
DB = E.connect(os.getenv("SMARTCLAIM_DB", "smartclaim.db"))
if not DB.execute("SELECT 1 FROM customers").fetchone(): E.seed(DB)

@app.api_route("/api/{rest:path}", methods=["GET", "POST"])
async def api(rest: str, request: Request, x_session: str = Header(None)):
    try: body = await request.json() if request.method == "POST" else {}
    except ValueError: return JSONResponse({"error": "Invalid JSON"}, 400)
    code, obj = handlers.handle(DB, request.method, "/api/" + rest, x_session, body, dict(request.query_params))
    return JSONResponse(obj, code)

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "web"), html=True))
