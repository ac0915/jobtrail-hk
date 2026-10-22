"""Opt-in UI routes; no database or production configuration changes."""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, FileResponse

TRACKER_PATHS = {'/', '/profile', '/profile/my-jobs', '/my-jobs'}


def install_ui(app, web_dir: Path, *, enabled: bool):
    web_dir = Path(web_dir)

    def read_page(name):
        path = web_dir / name
        if not path.is_file():
            raise HTTPException(500, 'Website file missing.')
        return path.read_text(encoding='utf-8')

    @app.get('/login', include_in_schema=False)
    def login_page():
        return HTMLResponse(read_page('auth.html'), headers={'Cache-Control': 'no-store'})

    @app.get('/register', include_in_schema=False)
    def register_page():
        html = read_page('auth.html')
        html = html.replace('</body>', '<script>document.getElementById("switch").click();</script></body>', 1)
        return HTMLResponse(html, headers={'Cache-Control': 'no-store'})

    @app.get('/ui/auth-nav.js', include_in_schema=False)
    def navigation_script():
        path = web_dir / 'auth-nav.js'
        if not path.is_file():
            raise HTTPException(500, 'Navigation asset missing.')
        return FileResponse(path, media_type='text/javascript', headers={'Cache-Control': 'no-store'})

    @app.middleware('http')
    async def tracker_navigation(request, call_next):
        if enabled and request.method == 'GET' and request.url.path in TRACKER_PATHS:
            path = web_dir / 'index.html'
            if not path.is_file():
                return HTMLResponse('Website file missing.', status_code=500)
            html = path.read_text(encoding='utf-8')
            html = html.replace('</head>', '<script src="/ui/auth-nav.js"></script></head>', 1)
            return HTMLResponse(html, headers={'Cache-Control': 'no-store'})
        return await call_next(request)
