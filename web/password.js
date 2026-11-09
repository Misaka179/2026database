/* 找回密码页：主题切换与重置申请提交（v2.5） */
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

  function showFeedback(id, message, type) {
    var box = document.getElementById(id);
    if (!box) return;
    box.hidden = false;
    box.className = 'notice' + (type === 'error' ? ' error'
      : type === 'success' ? ' success'
      : type === 'warning' ? ' warning' : '');
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
    if (!response.ok) {
      throw new Error(detailMessage(data, '操作未完成，请稍后重试。'));
    }
    return data;
  }

  var resetForm = document.getElementById('reset-form');
  if (resetForm) {
    resetForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      var button = resetForm.querySelector('[type="submit"]');
      if (button.disabled) return;
      hideFeedback('reset-feedback');
      var data = new FormData(resetForm);
      var body = {
        kind: data.get('kind'),
        account: String(data.get('account') || '').trim(),
        name: String(data.get('name') || '').trim(),
        reason: String(data.get('reason') || '').trim()
      };
      if (!body.account || !body.name) {
        showFeedback('reset-feedback', '请填写学号/账号与姓名。', 'error');
        return;
      }
      var original = button.innerHTML;
      button.disabled = true;
      try {
        await postJson('/auth/password/reset-request', body);
        resetForm.reset();
        showFeedback('reset-feedback', '重置申请已提交，管理员核实后会通过通知告知新密码。', 'success');
      } catch (error) {
        showFeedback('reset-feedback', (error && error.message) || '提交失败，请稍后重试。', 'error');
      } finally {
        button.disabled = false;
        button.innerHTML = original;
      }
    });
  }
})();
