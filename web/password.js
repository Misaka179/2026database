/* 找回密码页：主题切换、旧链接兼容与重置申请提交（v2.6） */
(function () {
  'use strict';

  var THEME_KEY = 'volunteer_theme';
  var THEME_MODES = ['light', 'dark', 'system'];

  function themeMode() {
    try {
      var value = localStorage.getItem(THEME_KEY);
      return THEME_MODES.indexOf(value) >= 0 ? value : 'system';
    } catch (error) { return 'system'; }
  }

  function currentTheme() {
    var mode = themeMode();
    return mode === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : mode;
  }

  function applyTheme() {
    var dark = currentTheme() === 'dark';
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    var button = document.querySelector('[data-theme-toggle]');
    if (!button) return;
    button.setAttribute('aria-label', '切换主题，当前为' + (dark ? '深色' : '浅色'));
    var use = button.querySelector('use');
    if (use) use.setAttribute('href', dark ? '#i-sun' : '#i-moon');
  }

  function cycleTheme() {
    var index = THEME_MODES.indexOf(themeMode());
    try { localStorage.setItem(THEME_KEY, THEME_MODES[(index + 1) % THEME_MODES.length]); }
    catch (error) { /* 隐私模式下仅当前页面生效 */ }
    applyTheme();
  }

  function showFeedback(message, type) {
    var box = document.getElementById('reset-feedback');
    if (!box) return;
    box.hidden = false;
    box.className = 'notice' + (type === 'error' ? ' error' : type === 'success' ? ' success' : ' warning');
    box.textContent = message;
  }

  function hideFeedback() {
    var box = document.getElementById('reset-feedback');
    if (!box) return;
    box.hidden = true;
    box.textContent = '';
  }

  function detailMessage(data, fallback) {
    if (data && typeof data.detail === 'string') return data.detail;
    if (data && Array.isArray(data.detail)) {
      var messages = data.detail.map(function (item) { return item.msg || ''; }).filter(Boolean);
      if (messages.length) return messages.join('；');
    }
    return fallback;
  }

  async function postJson(path, body) {
    var response;
    try {
      response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
    } catch (error) {
      throw new Error('连接暂时中断，请检查本机服务后重试。');
    }
    var data = await response.json().catch(function () {
      return { detail: '服务器未返回有效结果，请稍后重试。' };
    });
    if (!response.ok) throw new Error(detailMessage(data, '操作未完成，请稍后重试。'));
    return data;
  }

  var themeButton = document.querySelector('[data-theme-toggle]');
  if (themeButton) themeButton.addEventListener('click', cycleTheme);
  try {
    var media = window.matchMedia('(prefers-color-scheme: dark)');
    if (media.addEventListener) media.addEventListener('change', function () {
      if (themeMode() === 'system') applyTheme();
    });
  } catch (error) { /* 忽略旧浏览器 */ }
  applyTheme();

  if (window.location.hash === '#change') {
    showFeedback('请登录后在工作台修改密码。', 'warning');
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, '', window.location.pathname + '#reset');
    }
  }

  var resetForm = document.getElementById('reset-form');
  if (!resetForm) return;
  resetForm.addEventListener('submit', async function (event) {
    event.preventDefault();
    var button = resetForm.querySelector('[type="submit"]');
    if (!button || button.disabled) return;
    hideFeedback();
    var data = new FormData(resetForm);
    var body = {
      kind: data.get('kind'),
      account: String(data.get('account') || '').trim(),
      name: String(data.get('name') || '').trim(),
      phone: String(data.get('phone') || '').trim(),
      reason: String(data.get('reason') || '').trim()
    };
    if (!body.account || !body.name) {
      showFeedback('请填写学号或管理员账号与姓名。', 'error');
      return;
    }
    var original = button.innerHTML;
    button.disabled = true;
    button.textContent = '正在提交…';
    try {
      await postJson('/auth/password/reset-request', body);
      resetForm.reset();
      showFeedback('重置申请已提交。管理员处理后会通过其他方式告知你。', 'success');
    } catch (error) {
      showFeedback((error && error.message) || '提交失败，请稍后重试。', 'error');
    } finally {
      button.disabled = false;
      button.innerHTML = original;
    }
  });
})();
