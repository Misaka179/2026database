/* ============================================================================
   前端设计规范 2.5.0 · 静态预览脚本
   只做三件事：内联 SVG 图标、主题切换、导航/抽屉的演示交互。
   预览使用假数据，不请求任何接口。
   ========================================================================== */
(function () {
  'use strict';

  /* 1. 内联 SVG 图标（替代字符符号；零请求、随文字着色） */
  var SPRITE = [
    '<svg id="icon-sprite" aria-hidden="true" style="position:absolute;width:0;height:0;overflow:hidden">',
    '<symbol id="i-book" viewBox="0 0 24 24"><path d="M4 19.5V6a2 2 0 0 1 2-2h13v15.5"/><path d="M6 19.5h13"/><path d="M8 7h7"/></symbol>',
    '<symbol id="i-home" viewBox="0 0 24 24"><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z"/></symbol>',
    '<symbol id="i-inbox" viewBox="0 0 24 24"><path d="M4 13h3.5l1.5 2.5h6l1.5-2.5H20"/><path d="M4 13l2.2-6.3A2 2 0 0 1 8.1 5.4h7.8a2 2 0 0 1 1.9 1.3L20 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/></symbol>',
    '<symbol id="i-users" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><path d="M15.5 5.2a3 3 0 0 1 0 5.6"/><path d="M17.4 14.2A5.5 5.5 0 0 1 20.5 19"/></symbol>',
    '<symbol id="i-calendar" viewBox="0 0 24 24"><rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10h16M8 3.5V7M16 3.5V7"/></symbol>',
    '<symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 8v4.2l2.8 1.7"/></symbol>',
    '<symbol id="i-check" viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="m8 12.2 2.7 2.8L16.3 9"/></symbol>',
    '<symbol id="i-settings" viewBox="0 0 24 24"><path d="M4 7h9M18 7h2M4 17h4M13 17h7"/><circle cx="15.5" cy="7" r="2"/><circle cx="10.5" cy="17" r="2"/></symbol>',
    '<symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></symbol>',
    '<symbol id="i-refresh" viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4.5V9h-4.5"/></symbol>',
    '<symbol id="i-download" viewBox="0 0 24 24"><path d="M12 4v9"/><path d="m8 10.5 4 4 4-4"/><path d="M4 17v2.5h16V17"/></symbol>',
    '<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>',
    '<symbol id="i-menu" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></symbol>',
    '<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></symbol>',
    '<symbol id="i-chevron-down" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>',
    '<symbol id="i-chevron-right" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></symbol>',
    '<symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/></symbol>',
    '<symbol id="i-moon" viewBox="0 0 24 24"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/></symbol>',
    '<symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 4.5 21 19.5H3z"/><path d="M12 10v4M12 17h.01"/></symbol>',
    '<symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/></symbol>',
    '<symbol id="i-check-circle" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.2 2.4 2.4 4.6-4.9"/></symbol>',
    '<symbol id="i-file" viewBox="0 0 24 24"><path d="M6 3.5h7.5L19 9v11.5H6z"/><path d="M13.5 3.5V9H19"/></symbol>',
    '<symbol id="i-image" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m5 17 4.5-4 3.5 3 2.5-2.2L20 17"/></symbol>',
    '<symbol id="i-arrow-right" viewBox="0 0 24 24"><path d="M5 12h13M13 6l6 6-6 6"/></symbol>',
    '<symbol id="i-logout" viewBox="0 0 24 24"><path d="M14 8V5.5A1.5 1.5 0 0 0 12.5 4H6a1.5 1.5 0 0 0-1.5 1.5v13A1.5 1.5 0 0 0 6 20h6.5A1.5 1.5 0 0 0 14 18.5V16"/><path d="M10 12h10M17 8.5l3.5 3.5-3.5 3.5"/></symbol>',
    '<symbol id="i-filter" viewBox="0 0 24 24"><path d="M4 6h16M7 12h10M10 18h4"/></symbol>',
    '<symbol id="i-external" viewBox="0 0 24 24"><path d="M14 5h5v5M19 5l-8 8"/><path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></symbol>',
    '<symbol id="i-user" viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.6"/><path d="M5 20a7 7 0 0 1 14 0"/></symbol>',
    '<symbol id="i-lock" viewBox="0 0 24 24"><rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/><path d="M12 14.5v2"/></symbol>',
    '<symbol id="i-eye" viewBox="0 0 24 24"><path d="M3 12s3.4-6 9-6 9 6 9 6-3.4 6-9 6-9-6-9-6z"/><circle cx="12" cy="12" r="2.6"/></symbol>',
    '<symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3.5 19.5 6v5.5c0 4.3-3 7.2-7.5 9-4.5-1.8-7.5-4.7-7.5-9V6z"/><path d="m9 12 2.2 2.2 3.8-4"/></symbol>',
    '<symbol id="i-key" viewBox="0 0 24 24"><circle cx="8.5" cy="11.5" r="4"/><path d="m11.5 14.5 8 8M16 18l2-2M18.5 20.5l2-2"/></symbol>',
    '<symbol id="i-help" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.8.4-1 .9-1 1.8"/><path d="M12 16.5h.01"/></symbol>',
    '<symbol id="i-arrow-left" viewBox="0 0 24 24"><path d="M19 12H6M12 6l-6 6 6 6"/></symbol>',
    '</svg>'
  ].join('');

  if (!document.getElementById('icon-sprite')) {
    document.body.insertAdjacentHTML('afterbegin', SPRITE);
  }

  /* 2. 主题：浅色 → 深色 → 跟随系统，循环切换，记忆在 localStorage */
  var media = window.matchMedia('(prefers-color-scheme: dark)');
  var order = ['light', 'dark', 'system'];
  var labels = { light: '浅色', dark: '深色', system: '跟随系统' };
  var icons = { light: 'i-sun', dark: 'i-moon', system: 'i-settings' };
  var mode = 'system';
  try {
    mode = localStorage.getItem('preview-theme') || 'system';
  } catch (error) {
    mode = 'system';
  }
  if (order.indexOf(mode) < 0) {
    mode = 'system';
  }

  // 便于截图与评审：允许用 ?theme=light|dark|system 临时覆盖
  try {
    var forced = new URLSearchParams(window.location.search).get('theme');
    if (forced && order.indexOf(forced) >= 0) {
      mode = forced;
    }
  } catch (error) {
    /* 忽略 */
  }

  function resolved() {
    if (mode === 'system') {
      return media.matches ? 'dark' : 'light';
    }
    return mode;
  }

  function paint() {
    document.documentElement.setAttribute('data-theme', resolved());
    var buttons = document.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < buttons.length; i++) {
      var button = buttons[i];
      var icon = button.querySelector('use');
      var text = button.querySelector('span');
      if (icon) {
        icon.setAttribute('href', '#' + icons[mode]);
      }
      if (text) {
        text.textContent = '外观：' + labels[mode];
      }
      button.setAttribute('aria-label', '切换外观，当前' + labels[mode] + '，点击切换到下一个模式');
    }
  }

  function setMode(next) {
    mode = next;
    try {
      localStorage.setItem('preview-theme', mode);
    } catch (error) {
      /* 忽略隐私模式下的存储失败 */
    }
    paint();
  }

  paint();
  if (media.addEventListener) {
    media.addEventListener('change', function () {
      if (mode === 'system') {
        paint();
      }
    });
  }

  document.addEventListener('click', function (event) {
    var themeButton = event.target.closest('[data-theme-toggle]');
    if (themeButton) {
      setMode(order[(order.indexOf(mode) + 1) % order.length]);
      return;
    }

    var groupButton = event.target.closest('[data-nav-toggle]');
    if (groupButton) {
      var expanded = groupButton.getAttribute('aria-expanded') === 'true';
      groupButton.setAttribute('aria-expanded', String(!expanded));
      var children = document.getElementById(groupButton.getAttribute('aria-controls'));
      if (children) {
        children.hidden = expanded;
      }
      return;
    }

    var menuButton = event.target.closest('[data-menu-toggle]');
    if (menuButton) {
      var workspace = document.querySelector('.workspace');
      workspace.classList.toggle('menu-open');
      var menuBackdrop = document.querySelector('[data-menu-backdrop]');
      if (menuBackdrop) {
        menuBackdrop.hidden = !workspace.classList.contains('menu-open');
      }
      return;
    }

    var menuClose = event.target.closest('[data-menu-close]');
    if (menuClose) {
      var workspaceClose = document.querySelector('.workspace');
      if (workspaceClose) {
        workspaceClose.classList.remove('menu-open');
      }
      var menuBackdropClose = document.querySelector('[data-menu-backdrop]');
      if (menuBackdropClose) {
        menuBackdropClose.hidden = true;
      }
      return;
    }

    var tab = event.target.closest('[data-tab]');
    if (tab) {
      var group = tab.parentElement.querySelectorAll('[data-tab]');
      for (var j = 0; j < group.length; j++) {
        group[j].setAttribute('aria-selected', String(group[j] === tab));
      }
      return;
    }

    var authTab = event.target.closest('[data-auth-tab]');
    if (authTab) {
      var target = authTab.getAttribute('data-target');
      if (target) {
        window.location.hash = target;
      }
      syncAuth();
      return;
    }

    var reveal = event.target.closest('[data-reveal]');
    if (reveal) {
      var input = document.getElementById(reveal.getAttribute('data-reveal'));
      if (input) {
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        reveal.setAttribute('aria-label', show ? '隐藏密码' : '显示密码');
        var label = reveal.querySelector('span');
        if (label) {
          label.textContent = show ? '隐藏' : '显示';
        }
        var use = reveal.querySelector('use');
        if (use) {
          use.setAttribute('href', show ? '#i-lock' : '#i-eye');
        }
      }
      return;
    }

    var open = event.target.closest('[data-drawer-open]');
    if (open) {
      var drawer = document.querySelector('[data-drawer]');
      var backdrop = document.querySelector('[data-drawer-backdrop]');
      if (drawer) {
        drawer.hidden = false;
      }
      if (backdrop) {
        backdrop.hidden = false;
      }
      document.body.style.overflow = 'hidden';
      return;
    }

    var close = event.target.closest('[data-drawer-close]');
    if (close) {
      closeDrawer();
    }
  });

  function closeDrawer() {
    var drawer = document.querySelector('[data-drawer]');
    var backdrop = document.querySelector('[data-drawer-backdrop]');
    if (drawer) {
      drawer.hidden = true;
    }
    if (backdrop) {
      backdrop.hidden = true;
    }
    document.body.style.overflow = '';
  }

  /* 密码页：用地址栏 hash 做“路由”（#reset 忘记密码 / #change 修改密码） */
  function syncAuth() {
    var tabs = document.querySelectorAll('[data-auth-tab]');
    if (!tabs.length) {
      return;
    }
    var route = window.location.hash === '#change' ? 'change' : 'reset';
    for (var i = 0; i < tabs.length; i++) {
      var tab = tabs[i];
      var selected = tab.getAttribute('data-auth-tab') === route;
      tab.setAttribute('aria-selected', String(selected));
      var panel = document.getElementById(tab.getAttribute('aria-controls'));
      if (panel) {
        panel.hidden = !selected;
      }
    }
  }

  syncAuth();
  window.addEventListener('hashchange', syncAuth);

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') {
      return;
    }
    closeDrawer();
    var workspace = document.querySelector('.workspace');
    if (workspace) {
      workspace.classList.remove('menu-open');
    }
    var backdrop = document.querySelector('[data-menu-backdrop]');
    if (backdrop) {
      backdrop.hidden = true;
    }
  });
})();
