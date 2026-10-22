"""Opt-in UI routes; no database or production configuration changes."""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, FileResponse

TRACKER_PATHS = {'/', '/profile', '/profile/my-jobs', '/my-jobs'}

LAYOUT_STYLE = '''<style>
body{display:block;background:#f5fffd;padding:0;min-height:100vh}
.auth-brand{display:flex;align-items:center;gap:10px;max-width:1180px;margin:0 auto;padding:34px 32px;color:#030b32;font-weight:700;text-decoration:none;font-size:21px}
.auth-mark{display:grid;place-items:center;background:#24b7bd;color:white;border-radius:10px;width:32px;height:32px;font-size:20px}
.auth-layout{display:grid;grid-template-columns:minmax(0,480px) minmax(0,1fr);gap:64px;align-items:center;max-width:1180px;margin:24px auto;padding:24px 32px 64px;min-height:calc(100vh - 130px)}
.auth-layout .card{width:100%;padding:40px 42px;border-radius:30px;box-shadow:0 8px 36px #163a3208}
.auth-layout .brand{display:none}
.auth-art{min-width:0;text-align:center;color:#030b32}
.auth-art svg{display:block;width:100%;height:auto;max-height:460px}
.auth-art h2{font-size:28px;letter-spacing:-.6px;margin:20px 0 10px}
.auth-art p{color:#627875;line-height:1.7;margin:0 auto;max-width:340px}
@media(max-width:800px){.auth-layout{grid-template-columns:1fr;max-width:540px;min-height:auto;margin:16px auto;padding:16px 24px 48px}.auth-art{display:none}.auth-brand{padding:24px}.auth-layout .card{padding:32px 26px}}
</style>'''

ARTWORK = '''<aside class="auth-art" aria-label="JobTrail HK introduction">
<svg viewBox="0 0 520 440" role="img" aria-labelledby="jobtrail-art-title">
<title id="jobtrail-art-title">An applicant at a laptop, with job cards and a stylised Hong Kong skyline</title>
<circle cx="274" cy="222" r="182" fill="#e2f8f4"/>
<g fill="#d0eae6" stroke="#a0d2cd" stroke-width="2">
<path d="M24 295V188h40v107m12 0V144h38v151m14 0V170h40v125m184 0V129h40v166m12 0V83l18-26 18 26v212m12 0V160h48v135"/>
<path d="M368 130h18m-18 25h18m-18 25h18M84 170h20m-20 22h20m-20 22h20" fill="none"/>
</g>
<ellipse cx="268" cy="397" rx="217" ry="21" fill="#cfefea"/>
<g stroke="#091333" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">
<path d="M138 269h243m-217 0-15 120m204-120 15 120" fill="none"/>
<path d="M227 264c-39 0-58 25-53 61l14 39h109l15-66c3-19-24-34-44-34" fill="#21b4b9" stroke="#21b4b9"/>
<path d="m225 324-6 61-29 8m80-69 28 59 30 5" fill="none" stroke="#727e92" stroke-width="20"/>
<path d="M171 397h42m86-6 35 5" fill="none" stroke-width="12"/>
<path d="M222 208c-19 10-28 28-27 57h88l-10-41c-5-15-21-22-33-20" fill="#091333"/>
<path d="m209 233 15 27h51m-4-27 23 26h20" fill="none" stroke="#e5b79d" stroke-width="10"/>
<path d="M235 194v16" stroke="#e5b79d" stroke-width="12"/>
<ellipse cx="240" cy="173" rx="22" ry="27" fill="#f2cab2" stroke="none"/>
<path d="M219 173c-10-22 5-39 24-35 18-10 34 10 18 22-9 5-24-5-30-1v17" fill="#091333"/>
<path d="M243 175h5m-20 0h5" stroke-width="3"/>
<path d="m239 193 8-1" stroke-width="2"/>
<path d="m261 218 68-5 10 49h-67z" fill="#fff" stroke="#81969d" stroke-width="3"/>
<path d="M268 265h81" stroke="#81969d" stroke-width="3"/>
</g>
<g fill="white" stroke="#90d3cf" stroke-width="2">
<rect x="54" y="82" width="135" height="94" rx="13"/>
<rect x="337" y="178" width="142" height="91" rx="13"/>
</g>
<g stroke-linecap="round" fill="none">
<path d="M73 109h64m-64 17h89m-89 17h51M356 201h65m-65 17h99m-99 17h48" stroke="#b3c4c9" stroke-width="5"/>
<path d="m151 149 8 8 16-18m252 68 8 8 16-18" stroke="#22b5ba" stroke-width="5"/>
<path d="M104 359v-54m0 29-22-18m22 5 18-23m-18 55 22-19" stroke="#24b7bd" stroke-width="6"/>
</g>
<path d="M85 358h39l-7 35H92z" fill="#24b7bd"/>
</svg>
<h2>Your next opportunity starts here.</h2>
<p>Keep your job search organised, one application at a time.</p>
</aside>'''

MODE_SCRIPT = '''<script>
(() => {
  const toggle = document.getElementById('switch');
  const heading = document.getElementById('heading');
  if (!toggle || !heading) return;
  let syncing = false;
  function syncFromUrl() {
    const wantsRegister = location.pathname === '/register';
    const isRegister = heading.textContent === 'Create account';
    if (wantsRegister !== isRegister) {
      syncing = true; toggle.click(); syncing = false;
    }
  }
  toggle.addEventListener('click', () => {
    if (syncing) return;
    const target = heading.textContent === 'Create account' ? '/register' : '/login';
    if (location.pathname !== target) history.pushState(null, '', target);
  });
  window.addEventListener('popstate', syncFromUrl);
  syncFromUrl();
})();
</script>'''


def render_auth_page(html):
    html = html.replace('</head>', LAYOUT_STYLE + '</head>', 1)
    brand = '<a class="auth-brand" href="/"><span class="auth-mark" aria-hidden="true">J</span>JobTrail HK</a>'
    html = html.replace('<main class="card">', brand + '<div class="auth-layout"><main class="card">', 1)
    html = html.replace('</main>', '</main>' + ARTWORK + '</div>', 1)
    return html.replace('</body>', MODE_SCRIPT + '</body>', 1)


def install_ui(app, web_dir: Path, *, enabled: bool):
    web_dir = Path(web_dir)

    def read_page(name):
        path = web_dir / name
        if not path.is_file():
            raise HTTPException(500, 'Website file missing.')
        return path.read_text(encoding='utf-8')

    @app.get('/login', include_in_schema=False)
    def login_page():
        return HTMLResponse(render_auth_page(read_page('auth.html')), headers={'Cache-Control': 'no-store'})

    @app.get('/register', include_in_schema=False)
    def register_page():
        return HTMLResponse(render_auth_page(read_page('auth.html')), headers={'Cache-Control': 'no-store'})

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
