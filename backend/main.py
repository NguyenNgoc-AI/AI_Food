from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import auth, households, catalog, inventory, receipts, monitoring, dietary_recipes, recommendation, meal_grocery, waste_reports
from .db import migrate


@asynccontextmanager
async def lifespan(app):
    migrate()
    yield


app = FastAPI(title="SmartFood AI", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
app.include_router(auth.router)
app.include_router(households.router)
for module in (catalog, inventory, receipts, monitoring, dietary_recipes, recommendation, meal_grocery, waste_reports):
    app.include_router(module.router)
index = Path(__file__).resolve().parents[1] / "web" / "index.html"
app.mount("/assets", StaticFiles(directory=index.parent / "assets"), name="assets")


@app.middleware("http")
async def api_policy(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        started = perf_counter()
        request_id = uuid4().hex
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("X-SmartFood") != "1":
            response = JSONResponse({"detail": "Thiếu xác nhận yêu cầu từ ứng dụng."}, status_code=403)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("uvicorn.error").info(json.dumps({
            "request_id": request_id, "method": request.method,
            "route": getattr(request.scope.get("route"), "path", None),
            "status": response.status_code, "elapsed_ms": round((perf_counter() - started) * 1000),
        }))
        return response
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def invalid_input(request, exc):
    return JSONResponse({"detail": "Thông tin nhập vào không hợp lệ. Kiểm tra lại định dạng và độ dài."}, status_code=422)


@app.get("/household", include_in_schema=False)
def household_page() -> FileResponse:
    return FileResponse(index.with_name("household.html"), media_type="text/html")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(index, media_type="text/html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
