"""JobTrail HK FastAPI application entrypoint."""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from psycopg import OperationalError
from app.auth_routes import router as auth_router
from app.database import close_pool, open_pool
from app.imports import router as imports_router
from app.jobs import MULTI_USER_ENABLED, router as jobs_router
BASE_DIR = Path(__file__).resolve().parent
WEB_FILE = BASE_DIR / "web" / "index.html"
VERIFY_EMAIL_FILE = BASE_DIR / "web" / "verify-email.html"
FORGOT_PASSWORD_FILE = BASE_DIR / "web" / "forgot-password.html"
RESET_PASSWORD_FILE = BASE_DIR / "web" / "reset-password.html"
MINT_THEME_FILE = BASE_DIR / "web" / "mint-theme.css"
LANDING_FILE = BASE_DIR / "web" / "landing.html"
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        open_pool()
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError("Could not open the database pool. Check DATABASE_URL and that PostgreSQL is running.") from exc
    try:
        yield
    finally:
        close_pool()
app = FastAPI(title="JobTrail HK API", description="Hong Kong-focused job application tracker API. Statuses: saved, applied, interview, offer, rejected, closed.", version="0.2.0", lifespan=lifespan)
@app.exception_handler(OperationalError)
async def handle_db_unavailable(request: Request, exc: OperationalError):
    return JSONResponse(status_code=503, content={"detail": "Could not reach the database. Check that PostgreSQL is running and DATABASE_URL is correct."})
app.include_router(jobs_router)
app.include_router(imports_router)
if MULTI_USER_ENABLED:
    app.include_router(auth_router)
def website_response() -> FileResponse:
    if not WEB_FILE.is_file():
        raise HTTPException(status_code=500, detail="Website file missing: create web/index.html.")
    return FileResponse(WEB_FILE, media_type="text/html")
def page_response(path: Path, missing_message: str, media_type: str = "text/html") -> FileResponse:
    if not path.is_file():
        raise HTTPException(status_code=500, detail=missing_message)
    return FileResponse(path, media_type=media_type)
@app.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse("web/auth.html")
@app.get("/register", include_in_schema=False)
async def register_page():
    return FileResponse("web/auth.html")
@app.get("/", include_in_schema=False)
def home_page():
    if not MULTI_USER_ENABLED:
        return website_response()
    return page_response(LANDING_FILE, "Landing page missing: create web/landing.html.")
@app.get("/profile", include_in_schema=False)
def profile_page():
    return website_response()
@app.get("/profile/my-jobs", include_in_schema=False)
def my_jobs_page():
    return website_response()
@app.get("/my-jobs", include_in_schema=False)
def legacy_my_jobs_page():
    return website_response()
@app.get("/verify-email", include_in_schema=False)
def verify_email_page():
    return page_response(VERIFY_EMAIL_FILE, "Verification page missing: create web/verify-email.html.")
@app.get("/forgot-password", include_in_schema=False)
def forgot_password_page():
    return page_response(FORGOT_PASSWORD_FILE, "Forgot-password page missing: create web/forgot-password.html.")
@app.get("/reset-password", include_in_schema=False)
def reset_password_page():
    return page_response(RESET_PASSWORD_FILE, "Reset-password page missing: create web/reset-password.html.")
@app.get("/mint-theme.css", include_in_schema=False)
def mint_theme_stylesheet():
    return page_response(MINT_THEME_FILE, "Mint theme missing: create web/mint-theme.css.", media_type="text/css")
@app.get("/api-info", tags=["System"])
def api_info():
    return {"message": "JobTrail HK API is running", "home": "/", "profile": "/profile", "my_jobs": "/profile/my-jobs", "verify_email": "/verify-email", "forgot_password": "/forgot-password", "reset_password": "/reset-password", "docs": "/docs", "test_docs": "/test-docs", "jobs": "/jobs", "import_preview": "/imports/preview", "multi_user_enabled": MULTI_USER_ENABLED}
@app.get("/test-docs", include_in_schema=False)
def test_docs():
    page = get_swagger_ui_html(openapi_url=app.openapi_url, title="JobTrail HK - API testing")
    toast_assets = r'''<style>#jt-toasts{position:fixed;top:24px;right:24px;z-index:10000;display:grid;gap:14px;width:min(420px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow-y:auto;pointer-events:none;padding:4px;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}.jt-toast{--accent:#3397df;--tint:#e1f1ff;display:grid;grid-template-columns:42px minmax(0,1fr) 28px;gap:14px;padding:22px;border:1px solid white;border-radius:20px;background:linear-gradient(150deg,var(--tint),white 88%);box-shadow:0 12px 36px #24385b20;pointer-events:auto}.jt-toast.success{--accent:#269e78;--tint:#d7fbed}.jt-toast.warning{--accent:#b87510;--tint:#fff2d9}.jt-toast.error{--accent:#d64848;--tint:#ffe5e8}.jt-icon{display:grid;place-items:center;width:42px;border-radius:50%;color:var(--accent);background:#ffffffd9;font-size:23px;font-weight:700}.jt-title{margin:0 0 6px;color:#202b40;font-size:16px}.jt-message{margin:0;color:#4b5b70;font-size:16px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}.jt-close{width:28px;height:28px;padding:0;border:0;border-radius:7px;background:transparent;color:#66758a;font-size:23px;cursor:pointer}.jt-close:hover{background:#0000000f}.jt-close:focus-visible,.jt-link:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.jt-link{display:inline-block;margin-top:10px;color:#805500;font-size:14px;text-decoration:underline}</style><script>window.showJobTrailToast=function(options){let container=document.getElementById("jt-toasts");if(!container){container=document.createElement("div");container.id="jt-toasts";container.setAttribute("aria-label","Notifications");document.body.appendChild(container);}const type=options.type||"info";const card=document.createElement("section");card.className="jt-toast "+type;card.setAttribute("role",type==="error"?"alert":"status");card.setAttribute("aria-atomic","true");const icon=document.createElement("span");icon.className="jt-icon";icon.textContent={success:"✓",warning:"!",error:"!",info:"i"}[type]||"i";const content=document.createElement("div");const title=document.createElement("h3");title.className="jt-title";title.textContent=options.title;const message=document.createElement("p");message.className="jt-message";message.textContent=options.message;content.append(title,message);if(Number.isInteger(options.existingId)&&options.existingId>0){const link=document.createElement("a");link.className="jt-link";link.textContent="查看已儲存職位 →";link.href="/jobs/"+options.existingId;link.target="_blank";link.rel="noopener noreferrer";content.appendChild(link);}const close=document.createElement("button");close.className="jt-close";close.type="button";close.textContent="×";close.setAttribute("aria-label","關閉通知");card.append(icon,content,close);container.appendChild(card);let timer=null;let remaining=type==="warning"?8000:5000;let started=0;let dismissed=false;function dismiss(){if(dismissed)return;dismissed=true;clearTimeout(timer);card.remove();}function pause(){if(dismissed||type==="error"||timer!==null||card.matches(":hover")||card.contains(document.activeElement)){return;}}close.addEventListener("click",dismiss);card.addEventListener("mouseenter",pause);card.addEventListener("mouseleave",resume);card.addEventListener("focusin",pause);card.addEventListener("focusout",function(){setTimeout(resume,0);});resume();};</script>'''
    interceptors = r'''responseInterceptor: function(response) {let path;try{path=new URL(response.url,window.location.origin).pathname;}catch(error){return response;}if(path!=="/jobs"&&!path.startsWith("/jobs/")){return response;}let body=response.obj;if(body===undefined||body===null){try{body=JSON.parse(response.text);}catch(error){body=null;}}const status=response.status;if(status>=200&&status<300){const messages={"Job saved successfully":["職位已儲存","已加入你的求職清單。"],"Job updated successfully":["職位已更新","你的修改已成功儲存。"],"Job deleted successfully":["職位已刪除","已從求職清單移除。"]};const known=body&&messages[body.message];window.showJobTrailToast({type:known?"success":"info",title:known?known[0]:"資料已讀取",message:known?known[1]:"請求已完成。"});return response;}const detail=body&&body.detail;if(status===409){window.showJobTrailToast({type:"warning",title:"這個職位已存在",message:"這個職位連結已儲存，無需重複新增。",existingId:detail&&detail.existing_id});return response;}let message="請查看下方回應資料，確認錯誤原因。";if(typeof detail==="string"){message=detail;}else if(Array.isArray(detail)){message=detail.map(function(item){return(item.loc||[]).join(" → ")+": "+item.msg;}).join("\n");}else if(detail&&detail.message){message=detail.message;}window.showJobTrailToast({type:"error",title:status===422?"請檢查輸入內容":"操作未完成",message:message+"\nHTTP "+status});return response;},'''
    html = page.body.decode("utf-8")
    html = html.replace("</head>", toast_assets + "\n</head>", 1)
    html = html.replace("const ui = SwaggerUIBundle({", "const ui = SwaggerUIBundle({\n" + interceptors, 1)
    return HTMLResponse(content=html)
