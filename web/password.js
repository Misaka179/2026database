/* 找回 / 修改密码页：主题、hash 路由与表单提交（v2.5） */
(function () {
  'use strict';

  var THEME_KEY = 'volunteer_theme';
  var THEME_MODES = ['light', 'dark', 'system'];
  var THEME_LABELS = { light: '浅色', dark: '深色', system: '跟随系统' };

  function themeMode() {
    try {
      var value = localStorage.getItem(THEME_KEY);
      return THEME_MODES.indexOf(value) >= 0 ? value : 'system';
    } catch (error) {
      return 'system';
    }
  }

  function systemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function currentTheme() {
    var mode = themeMode();
    return mode === 'system' ? systemTheme() : mode;
  }

  function syncThemeButtons() {
    var dark = currentTheme() === 'dark';
    var buttons = document.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < buttons.length; i++) {
      var label = buttons[i].querySelector('[data-theme-label]');
      if (label) label.textContent = '外观：' + THEME_LABELS[themeMode()];
      var use = buttons[i].querySelector('use');
      if (use) use.setAttribute('href', dark ? '#i-sun' : '#i-moon');
    }
  }

  function applyTheme() {
    document.documentElement.setAttribute('data-theme', currentTheme());
    syncThemeButtons();
  }

  function cycleTheme() {
    var next = THEME_MODES[(THEME_MODES.indexOf(themeMode()) + 1) % THEME_MODES.length];
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (error) {
      /* 隐私模式下仅当前页面生效 */
    }
    applyTheme();
  }

  var themeButton = document.querySelector('[data-theme-toggle]');
  if (themeButton) themeButton.addEventListener('click', cycleTheme);
  try {
    var media = window.matchMedia('(prefers-color-scheme: dark)');
    if (media.addEventListener) {
      media.addEventListener('change', function () {
        if (themeMode() === 'system') applyTheme();
      });
    }
  } catch (error) {
    /* 忽略旧浏览器 */
  }
  applyTheme();

  /* 标签页与 hash 路由：#reset 忘记密码 / #change 修改密码 */
  var tabs = document.querySelectorAll('[data-auth-tab]');
  var changeTab = document.querySelector('[data-auth-tab="change"]');
  var resetTab = document.querySelector('[data-auth-tab="reset"]');
  var token = null;
  try {
    token = sessionStorage.getItem('volunteer_token');
  } catch (error) {
    token = null;
  }

  // 未登录时隐藏"修改密码"标签，登录后隐藏"忘记密码"标签
  if (!token && changeTab) {
    changeTab.style.display = 'none';
  }
  if (token && resetTab) {
    resetTab.style.display = 'none';
  }

  function syncTabs() {
    var route = window.location.hash === '#change' ? 'change' : 'reset';
    // 未登录时强制跳转到 reset
    if (!token && route === 'change') {
      window.location.hash = '#reset';
      route = 'reset';
    }
    // 登录后强制跳转到 change
    if (token && route === 'reset') {
      window.location.hash = '#change';
      route = 'change';
    }
    for (var i = 0; i < tabs.length; i++) {
      var tab = tabs[i];
      var selected = tab.getAttribute('data-auth-tab') === route;
      tab.setAttribute('aria-selected', String(selected));
      var panel = document.getElementById(tab.getAttribute('aria-controls'));
      if (panel) panel.hidden = !selected;
    }
  }

  for (var i = 0; i < tabs.length; i++) {
    tabs[i].addEventListener('click', function () {
      var target = this.getAttribute('data-target');
      if (target) window.location.hash = target;
      syncTabs();
    });
  }
  window.addEventListener('hashchange', syncTabs);
  syncTabs();

  function showFeedback(id, message, type) {
    var box = document.getElementById(id);
    if (!box) return;
    box.hidden = false;
    box.className = 'notice' + (type === 'error' ? ' error' : type === 'success' ? ' success' : type === 'warning' ? ' warning' : '');
    box.textContent = message;
  }

  function hideFeedback(id) {
    var box = document.getElementById(id);
    if (box) {
      box.hidden = true;
      box.textContent = '';
    }
  }

  function detailMessage(data, fallback) {
    if (data && typeof data.detail === 'string') return data.detail;
    if (data && Array.isArray(data.detail) && data.detail.length) {
      return data.detail.map(function (item) {
        return item.msg || '';
      }).filter(Boolean).join('；') || fallback;
    }
    return fallback;
  }

  async function postJson(path, body, token) {
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    var response;
    try {
      response = await fetch(path, { method: 'POST', headers: headers, body: JSON.stringify(body) });
    } catch (error) {
      throw new Error('连接暂时中断，请检查本机服务后重试。');
    }
    var data = await response.json().catch(function () {
      return { detail: '服务器未返回有效结果，请稍后重试。' };
    });
    if (!response.ok) {
      throw new Error(detailMessage(data, '操作未完成，请稍后重试。'));
    }
    return data;
  }

  async function getJson(path, token) {
    var response;
    try {
      response = await fetch(path, { headers: { Authorization: 'Bearer ' + token } });
    } catch (error) {
      throw new Error('连接暂时中断，请检查本机服务后重试。');
    }
    var data = await response.json().catch(function () {
      return {};
    });
    if (!response.ok) {
      throw new Error(detailMessage(data, '登录状态已失效，请重新登录。'));
    }
    return data;
  }

  function identityOf(me) {
    if (me && me.account) return { kind: 'admin', label: '管理员', account: me.account };
    if (me && me.student_id) return { kind: 'student', label: '志愿者', account: me.student_id };
    return { kind: 'admin', label: '管理员', account: '' };
  }

  var passwordDialog = document.getElementById('password-dialog');
  function showChangeDone(identity) {
    if (!passwordDialog || !passwordDialog.showModal) return false;
    var kindText = document.getElementById('password-dialog-kind');
    var accountText = document.getElementById('password-dialog-account');
    if (kindText) kindText.textContent = identity.label;
    if (accountText) accountText.textContent = identity.account || '—';
    passwordDialog.showModal();
    var login = document.getElementById('password-dialog-login');
    if (login && login.focus) login.focus();
    return true;
  }

  function submitOnce(form, handler) {
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var button = form.querySelector('[type="submit"]');
      if (button.disabled) return;
      var original = button.innerHTML;
      button.disabled = true;
      try {
        await handler(button);
      } catch (error) {
        showFeedback(form.id === 'change-form' ? 'change-feedback' : 'reset-feedback',
          (error && error.message) || '操作未完成，请稍后重试。', 'error');
      } finally {
        button.disabled = false;
        button.innerHTML = original;
      }
    });
  }

  var resetForm = document.getElementById('reset-form');
  if (resetForm) {
    submitOnce(resetForm, async function () {
      hideFeedback('reset-feedback');
      var data = new FormData(resetForm);
      var body = {
        kind: data.get('kind'),
        account: String(data.get('account') || '').trim(),
        name: String(data.get('name') || '').trim(),
        phone: String(data.get('phone') || '').trim(),
        reason: String(data.get('reason') || '').trim()
      };
      if (!body.account || !body.name) {
        showFeedback('reset-feedback', '请填写学号/账号与姓名。', 'error');
        return;
      }
      await postJson('/auth/password/reset-request', body);
      resetForm.reset();
      showFeedback('reset-feedback', '重置申请已提交，管理员核实后会通过通知告知新密码。', 'success');
    });
  }

  var changeForm = document.getElementById('change-form');
  if (changeForm) {
    submitOnce(changeForm, async function () {
      hideFeedback('change-feedback');
      var token = null;
      try {
        token = sessionStorage.getItem('volunteer_token');
      } catch (error) {
        token = null;
      }
      if (!token) {
        showFeedback('change-feedback', '请先返回登录页登录，登录后再修改密码。', 'warning');
        return;
      }
      var me = null;
      try {
        me = await getJson('/auth/me', token);
      } catch (error) {
        showFeedback('change-feedback', '登录状态已失效，请返回登录页重新登录后再修改密码。', 'warning');
        return;
      }
      var identity = identityOf(me);
      var data = new FormData(changeForm);
      var body = {
        current_password: String(data.get('current_password') || ''),
        new_password: String(data.get('new_password') || '')
      };
      if (String(data.get('confirm_password') || '') !== body.new_password) {
        showFeedback('change-feedback', '两次输入的新密码不一致。', 'error');
        return;
      }
      if (body.new_password.length < 8 || body.new_password.length > 128) {
        showFeedback('change-feedback', '新密码长度必须为 8 至 128 个字符。', 'error');
        return;
      }
      // postJson 失败会由 submitOnce 兜底显示中文错误（如“当前密码不正确”）。
      await postJson('/auth/password/change', body, token);
      changeForm.reset();
      try {
        sessionStorage.removeItem('volunteer_token');
        // 登录页据此自动带出身份与账号，并提示使用新密码。
        sessionStorage.setItem('password_changed', JSON.stringify({
          kind: identity.kind,
          account: identity.account
        }));
      } catch (error) {
        /* 隐私模式下忽略存储失败 */
      }
      hideFeedback('change-feedback');
      if (!showChangeDone(identity)) {
        window.location.href = '/';
      }
    });
  }
})();
