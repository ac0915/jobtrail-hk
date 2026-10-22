(() => {
  'use strict';
  const nativeFetch = window.fetch.bind(window);
  let redirecting = false;
  function csrf() {
    const part = document.cookie.split('; ').find(x => x.startsWith('jt_csrf='));
    return part ? decodeURIComponent(part.slice(8)) : '';
  }
  function login() {
    if (!redirecting) { redirecting = true; window.location.assign('/login'); }
  }
  window.fetch = async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    const isJob = url.origin === location.origin && (url.pathname === '/jobs' || url.pathname.startsWith('/jobs/'));
    const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (isJob && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      const token = csrf(); if (token) headers.set('X-CSRF-Token', token);
      init = {...init, headers};
    }
    const response = await nativeFetch(input, init);
    if (isJob && response.status === 401) login();
    return response;
  };
  async function start() {
    const nav = document.querySelector('.sidebar .nav');
    if (!nav) return;
    const account = document.createElement('section');
    account.setAttribute('aria-label', 'Account');
    account.style.cssText = 'margin-top:24px;padding:12px;border-top:1px solid #cbd5e4;overflow-wrap:anywhere';
    const status = document.createElement('p');
    status.setAttribute('role', 'status');status.textContent = 'Checking sign-in…';
    const signIn = document.createElement('a');signIn.href = '/login';signIn.textContent = 'Login';signIn.hidden = true;
    const register = document.createElement('a');register.href = '/register';register.textContent = 'Register';register.hidden = true;
    const logout = document.createElement('button');logout.type = 'button';logout.textContent = 'Logout';logout.hidden = true;
    account.append(status, signIn, register, logout);nav.after(account);
    try {
      const response = await nativeFetch('/auth/me', {credentials:'same-origin', cache:'no-store'});
      if (response.status === 401) {
        status.textContent = 'Sign in to manage your jobs.';signIn.hidden = register.hidden = false;
        if (['/profile', '/profile/my-jobs', '/my-jobs'].includes(location.pathname)) login();
        return;
      }
      if (!response.ok) throw new Error('Unable to check your session. Please reload.');
      const data = await response.json();status.textContent = data.user.email;logout.hidden = false;
    } catch (error) {status.textContent = error.message;}
    logout.addEventListener('click', async () => {
      logout.disabled = true;
      try {
        const response = await nativeFetch('/auth/logout', {method:'POST', credentials:'same-origin', headers:{'X-CSRF-Token':csrf()}});
        if (!response.ok && response.status !== 401) throw new Error('Logout failed. Please try again.');
        login();
      } catch(error) {status.textContent = error.message;logout.disabled = false;}
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});else start();
})();
