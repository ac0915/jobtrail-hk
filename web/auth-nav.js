(() => {
  'use strict';

  const nativeFetch = window.fetch.bind(window);
  let redirecting = false;

  const PROTECTED_PATHS = ['/profile', '/profile/my-jobs', '/my-jobs'];

  function getCookie(name) {
    const cookie = document.cookie
      .split('; ')
      .find((item) => item.startsWith(`${name}=`));

    return cookie ? decodeURIComponent(cookie.slice(name.length + 1)) : '';
  }

  function redirectToLogin() {
    if (redirecting) return;
    redirecting = true;
    window.location.assign('/login');
  }

  function isJobRequest(url, method) {
    const isJobPath =
      url.origin === location.origin &&
      (url.pathname === '/jobs' || url.pathname.startsWith('/jobs/'));

    return isJobPath && !['GET', 'HEAD', 'OPTIONS'].includes(method);
  }

  function createHiddenLink(href, text) {
    const link = document.createElement('a');
    link.href = href;
    link.textContent = text;
    link.hidden = true;
    return link;
  }

  function createStatusElement() {
    const status = document.createElement('p');
    status.setAttribute('role', 'status');
    status.textContent = 'Checking sign-in…';
    return status;
  }

  function createAccountSection() {
    const account = document.createElement('section');
    account.setAttribute('aria-label', 'Account');
    account.style.cssText =
      'margin-top:24px;padding:12px;border-top:1px solid #cbd5e4;overflow-wrap:anywhere';

    const status = createStatusElement();
    const signIn = createHiddenLink('/login', 'Login');
    const register = createHiddenLink('/register', 'Register');

    const logout = document.createElement('button');
    logout.type = 'button';
    logout.textContent = 'Logout';
    logout.hidden = true;

    account.append(status, signIn, register, logout);
    return { account, status, signIn, register, logout };
  }

  async function checkSession(status, signIn, register, logout) {
    try {
      const response = await nativeFetch('/auth/me', {
        credentials: 'same-origin',
        cache: 'no-store'
      });

      if (response.status === 401) {
        status.textContent = 'Sign in to manage your jobs.';
        signIn.hidden = false;
        register.hidden = false;

        if (PROTECTED_PATHS.includes(location.pathname)) {
          redirectToLogin();
        }

        return;
      }

      if (!response.ok) {
        throw new Error('Unable to check your session. Please reload.');
      }

      const data = await response.json();
      status.textContent = data.user.email;
      logout.hidden = false;
    } catch (error) {
      status.textContent = error.message;
    }
  }

  async function logoutUser(status, logout) {
    logout.disabled = true;

    try {
      const response = await nativeFetch('/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRF-Token': getCookie('jt_csrf') }
      });

      if (!response.ok && response.status !== 401) {
        throw new Error('Logout failed. Please try again.');
      }

      redirectToLogin();
    } catch (error) {
      status.textContent = error.message;
      logout.disabled = false;
    }
  }

  async function start() {
    const nav = document.querySelector('.sidebar .nav');
    if (!nav) return;

    const { account, status, signIn, register, logout } = createAccountSection();
    nav.after(account);

    await checkSession(status, signIn, register, logout);

    logout.addEventListener('click', () => logoutUser(status, logout));
  }

  window.fetch = async (input, init = {}) => {
    const url = new URL(
      input instanceof Request ? input.url : input,
      location.href
    );

    const method = (
      init.method ||
      (input instanceof Request ? input.method : 'GET')
    ).toUpperCase();

    if (isJobRequest(url, method)) {
      const headers = new Headers(
        init.headers ||
        (input instanceof Request ? input.headers : undefined)
      );

      const csrfToken = getCookie('jt_csrf');
      if (csrfToken) headers.set('X-CSRF-Token', csrfToken);

      init = { ...init, headers };
    }

    const response = await nativeFetch(input, init);

    if (isJobRequest(url, method) && response.status === 401) {
      redirectToLogin();
    }

    return response;
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
