(() => {
  'use strict';

  const TOKEN_KEY = 'volunteer_token';
  const $ = (selector, root = document) => root.querySelector(selector);
  const fields = {
    kind: '身份或申请类型', account: '账号', password: '密码', password_hash: '密码摘要',
    name: '姓名', student_id: '学号', admin_id: '管理员编号', role: '管理员角色',
    college: '学院', phone: '联系电话', credit_score: '当前信用分', status: '状态',
    join_time: '加入时间', slot_id: '班次编号', team_name: '分队名称', period_no: '时段编号',
    start_time: '开始时间', end_time: '结束时间', location: '服务地点', need_num: '需求人数',
    service_minutes: '服务时长（分钟）', manager_admin_id: '负责管理员编号',
    schedule_id: '排班编号', schedule_date: '服务日期', create_time: '创建时间',
    active_marker: '有效记录标记', attendance_id: '考勤编号', attendance_status: '考勤结果',
    check_time: '考勤记录时间', remark: '备注', record_id: '服务记录编号', record_status: '记录状态',
    leave_id: '请假申请编号', reason: '原因', apply_time: '申请时间', approved: '审批决定',
    approve_admin_id: '审批管理员编号', approve_status: '审批状态', approve_time: '审批时间',
    transfer_id: '换班申请编号', old_schedule_id: '原排班编号', new_slot_id: '目标班次编号',
    new_date: '目标日期', first_admin_id: '初审管理员编号', first_status: '初审状态',
    first_time: '初审时间', final_admin_id: '终审管理员编号', final_status: '终审状态',
    final_time: '终审时间', new_schedule_id: '新排班编号', withdrawal_id: '退队申请编号',
    stage: '审批阶段', rule_id: '信用规则编号', violation_type: '违规类型', version: '规则版本',
    deduct_score: '规则扣分', create_admin_id: '规则创建人编号', violation_id: '违规编号',
    nominal_deduct: '规则规定扣分', credit_log_id: '信用流水编号', operator_id: '操作人编号',
    change_score: '信用分变化', before_score: '变更前信用分', after_score: '变更后信用分',
    change_reason: '变更原因', change_time: '变更时间', log_id: '操作日志编号',
    operation_type: '操作类型', target_table: '目标数据表', target_id: '目标记录编号',
    before_value: '修改前数据', after_value: '修改后数据', operation_time: '操作时间',
    start: '开始日期（含当天）', end: '结束日期（不含当天）', limit: '最多显示条数',
    records: '服务明细', logs: '信用流水', total_minutes: '累计时长（分钟）',
    total_hours: '累计时长（小时）', cancelled_schedules: '已取消的排班编号',
    replayed: '此前已处理', leave_approved: '已获批请假', access_token: '登录凭据',
    token_type: '凭据类型', expires_in: '有效时长（秒）', detail: '处理说明',
    message: '提示信息', minutes: '服务时长（分钟）', credit_before: '原信用分',
    credit_after: '处理后信用分', date: '日期', id: '编号', type: '类型',
    loc: '字段位置', msg: '校验说明', input: '输入内容', ctx: '校验条件',
    occupied: '已安排人数', remaining: '剩余名额', manager_name: '负责人姓名',
    student_name: '志愿者姓名', admin_name: '管理员姓名', total: '总数', items: '记录', slot_status: '班次状态',
  };
  const enums = {
    admin: '管理员', student: '志愿者', STUDENT: '志愿者', SUPER: '超级管理员',
    ACTIVE: '有效', DISABLED: '已停用', QUIT: '已退队', CANCELLED: '已取消',
    COMPLETED: '已完成', NORMAL: '正常出勤', LATE: '迟到', ABSENT: '缺勤', LEAVE: '请假',
    VALID: '有效', VOID: '已作废', PENDING: '待审批', APPROVED: '已通过', REJECTED: '已拒绝',
    RETIRED: '已停用', REVOKED: '已撤销', leave: '请假', transfer: '换班', withdrawal: '退队',
    first: '初审', final: '终审', ok: '运行正常', bearer: '持有者凭据',
    CREATE_STUDENT: '创建志愿者', CREATE_ADMIN: '创建管理员', CREATE_SLOT: '创建班次',
    CREATE_SCHEDULE: '创建排班', CANCEL_SCHEDULE: '取消排班', APPROVE_LEAVE: '审批请假',
    APPROVE_TRANSFER_FIRST: '换班初审', APPROVE_TRANSFER_FINAL: '换班终审',
    TRANSFER_FIRST: '换班初审', TRANSFER_FINAL: '换班终审',
    APPROVE_WITHDRAWAL: '审批退队', RECORD_ATTENDANCE: '登记考勤', REVISE_HOURS: '修正时长',
    SET_CREDIT_RULE: '更新信用规则', schedule: '排班表', attendance: '考勤表',
    service_slot: '服务班次表', service_record: '服务记录表', credit_rule: '信用规则表',
    credit_log: '信用流水表', leave_application: '请假申请表', transfer_application: '换班申请表',
    withdrawal_application: '退队申请表', operation_log: '操作日志表', violation: '违规表',
  };
  const fallbackTitles = {
    'GET /health': '检查服务状态', 'POST /auth/login': '账号登录', 'GET /auth/me': '查询当前身份',
    'GET /students': '查询志愿者', 'POST /students': '创建志愿者', 'GET /admins': '查询管理员',
    'POST /admins': '创建管理员', 'GET /slots': '查询服务班次', 'POST /slots': '创建服务班次',
    'GET /schedules': '查询排班', 'POST /schedules': '创建排班',
    'POST /schedules/{schedule_id}/cancel': '取消排班',
    'POST /applications/leave': '提交请假申请', 'POST /applications/transfer': '提交换班申请',
    'POST /applications/withdrawal': '提交退队申请', 'GET /applications/{kind}': '查询申请',
    'POST /applications/leave/{leave_id}/decision': '审批请假申请',
    'POST /applications/transfer/{transfer_id}/{stage}': '审批换班申请',
    'POST /applications/withdrawal/{withdrawal_id}/decision': '审批退队申请',
    'POST /attendance': '登记考勤', 'GET /hours': '查询服务时长',
    'PATCH /service-records/{record_id}': '修正服务时长', 'GET /credit': '查询信用记录',
    'GET /credit-rules': '查询信用规则', 'PUT /credit-rules/{violation_type}': '更新信用规则',
    'GET /operation-logs': '查询操作日志',
  };
  const statusNames = {200: '处理成功', 201: '创建成功', 204: '处理成功，无返回内容',
    400: '请求有误', 401: '需要登录', 403: '无操作权限', 404: '记录不存在',
    409: '与现有业务数据冲突', 422: '字段校验未通过', 500: '服务内部异常', 503: '服务暂不可用'};
  let spec = null;
  let idCounter = 0;
  let operations = [];
  let loggedIn = false;
  let sessionGeneration = 0;
  let loginRequestSequence = 0;

  function isDark() {
    return document.documentElement.dataset.theme === 'dark' || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
  }
  function updateThemeLabel() { $('#docs-theme').textContent = isDark() ? '浅色外观' : '深色外观'; }
  try {
    const savedTheme = localStorage.getItem('volunteer_theme');
    if (['light', 'dark'].includes(savedTheme)) document.documentElement.dataset.theme = savedTheme;
  } catch { /* Use the system theme when browser storage is unavailable. */ }
  updateThemeLabel();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', updateThemeLabel);
  $('#docs-theme').addEventListener('click', () => {
    const theme = isDark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('volunteer_theme', theme); } catch { /* Theme still applies to the current page. */ }
    updateThemeLabel();
  });

  function el(tag, className = '', text = '') {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== '') node.textContent = String(text);
    return node;
  }
  function chinese(value) { return typeof value === 'string' && /[\u3400-\u9fff]/.test(value); }
  function token() { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } }
  function invalidateSessionResults() {
    sessionGeneration += 1;
    for (const result of document.querySelectorAll('.docs-result')) { result.replaceChildren(); result.hidden = true; }
    for (const password of document.querySelectorAll('input[type="password"]')) password.value = '';
    message($('#login-feedback'), '');
    document.dispatchEvent(new Event('docs-session-changed'));
  }
  function clearToken() {
    try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* No stored session. */ }
    invalidateSessionResults();
  }
  function storeToken(value) {
    try { sessionStorage.setItem(TOKEN_KEY, value); }
    catch { throw new Error('浏览器未允许保存登录状态，请检查网站存储设置后重试。'); }
    invalidateSessionResults();
  }
  function resolve(schema = {}) {
    if (schema.$ref) {
      let result = spec;
      for (const part of schema.$ref.replace(/^#\//, '').split('/')) result = result?.[part];
      return resolve({...result, ...Object.fromEntries(Object.entries(schema).filter(([key]) => key !== '$ref'))});
    }
    if (schema.anyOf || schema.oneOf) {
      const choice = (schema.anyOf || schema.oneOf).find(item => item.type !== 'null') || {};
      return {...schema, ...resolve(choice)};
    }
    return schema;
  }
  function fieldLabel(key, schema = {}) {
    return chinese(schema.title) ? schema.title : fields[key] || key;
  }
  function enumLabel(value, key) {
    if (key === 'target_table' && value === 'admin') return '管理员表';
    if (key === 'target_table' && value === 'student') return '志愿者表';
    if (key === 'role' && value === 'NORMAL') return '普通管理员';
    if (key === 'approved') return value === true || value === 'true' ? '通过' : '拒绝';
    if (key === 'leave_approved') return value ? '已批准' : '未批准';
    if (value === true) return '是';
    if (value === false) return '否';
    return enums[value] || String(value);
  }
  function plainValue(value, key = '') {
    if (value === null || value === undefined || value === '') return '未填写';
    return enumLabel(value, key);
  }
  function redact(value, key = '') {
    if (/password|token|authorization|secret/i.test(key)) return '已隐藏';
    if (Array.isArray(value)) return value.map(item => redact(item));
    if (value && typeof value === 'object') {
      const sensitiveInput = Array.isArray(value.loc) && value.loc.some(part => /password|token|secret/i.test(String(part)));
      return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, sensitiveInput && k === 'input' ? '已隐藏' : redact(v, k)]));
    }
    if (typeof value === 'string' && ['before_value', 'after_value'].includes(key)) {
      try { return redact(JSON.parse(value)); } catch { return value; }
    }
    return value;
  }
  function apiError(data, status) {
    const detail = data?.detail;
    if (typeof detail === 'string' && chinese(detail)) return detail;
    if (Array.isArray(detail)) {
      return detail.map(item => {
        const key = Array.isArray(item.loc) ? item.loc.at(-1) : '';
        return `${fieldLabel(key)}：${chinese(item.msg) ? item.msg : '格式或取值不符合要求'}`;
      }).join('；');
    }
    return statusNames[status] || '请求未成功，请检查输入或稍后重试。';
  }
  async function request(path, options = {}) {
    const sentToken = token();
    const sentGeneration = sessionGeneration;
    const isLogin = path === '/auth/login';
    const sessionBound = !['/openapi.json', '/health'].includes(path.split('?')[0]);
    const loginSequence = isLogin ? ++loginRequestSequence : null;
    const isCurrent = () => sentToken === token() && sentGeneration === sessionGeneration
      && (!isLogin || loginSequence === loginRequestSequence);
    const staleResult = () => ({ok: false, stale: true, status: 0, data: null});
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    const headers = {'Accept': 'application/json', ...(options.body ? {'Content-Type': 'application/json'} : {})};
    if (sentToken && !isLogin) headers.Authorization = `Bearer ${sentToken}`;
    try {
      const response = await fetch(path, {...options, headers, signal: controller.signal, cache: 'no-store'});
      const text = await response.text();
      // A response belongs to the account that sent it, including failed requests.
      if (sessionBound && !isCurrent()) return staleResult();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = {detail: '服务返回了无法读取的内容，请稍后重试。'}; }
      if (response.status === 401 && !isLogin && sentToken && isCurrent()) { clearToken(); updateSession(null); }
      return {ok: response.ok, status: response.status, data};
    } catch (error) {
      if (sessionBound && !isCurrent()) return staleResult();
      if (error.name === 'AbortError') throw new Error('请求超时。若刚才提交了修改，请先查询记录确认结果，避免重复提交。');
      throw new Error('无法连接本地服务，请检查服务是否启动后重试。');
    } finally { clearTimeout(timer); }
  }
  function updateSession(person) {
    loggedIn = Boolean(token());
    $('#session-status').textContent = loggedIn
      ? person ? `${person.name || person.account || person.student_id || '当前用户'} / ${person.role ? enumLabel(person.role, 'role') : '志愿者'}` : '已保存登录状态'
      : '未登录';
    $('#session-action').textContent = loggedIn ? '退出登录' : '登录';
    $('#docs-auth > summary').textContent = loggedIn ? '切换登录账号' : '登录以调用业务接口';
  }
  async function syncSession() {
    updateSession(null);
    if (!token()) return;
    try {
      const response = await request('/auth/me');
      if (response.ok) updateSession(response.data);
    } catch { /* Reading the public docs remains available without the service. */ }
  }
  function message(target, text, state = '') {
    target.textContent = text;
    target.dataset.state = state;
  }
  function validForm(form) {
    for (const control of form.querySelectorAll('input,select,textarea')) {
      control.setCustomValidity('');
      if (control.required && !control.value.trim()) control.setCustomValidity('请填写或选择此项。');
      else if (control.validity.typeMismatch || control.validity.badInput) control.setCustomValidity('请按字段说明填写有效内容。');
      else if (control.validity.patternMismatch) control.setCustomValidity('格式不正确，请按字段说明填写。');
      else if (control.validity.rangeUnderflow) control.setCustomValidity(`数值不能小于 ${control.min}。`);
      else if (control.validity.rangeOverflow) control.setCustomValidity(`数值不能大于 ${control.max}。`);
      else if (control.validity.stepMismatch) control.setCustomValidity('请填写符合步长要求的数值。');
      else if (control.minLength > 0 && control.value && control.value.length < control.minLength) control.setCustomValidity(`至少需要 ${control.minLength} 个字符。`);
      if (!control.checkValidity()) { control.reportValidity(); return false; }
    }
    return true;
  }
  document.addEventListener('input', event => event.target.setCustomValidity?.(''));
  document.addEventListener('change', event => event.target.setCustomValidity?.(''));
  $('#session-action').addEventListener('click', () => {
    if (loggedIn) {
      clearToken(); updateSession(null);
      message($('#login-feedback'), '已退出登录。', 'success');
    } else {
      $('#docs-auth').open = true;
      $('#login-account').focus();
    }
  });
  $('#docs-login-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $('button', form);
    if (button.disabled || !validForm(form)) return;
    button.disabled = true; button.textContent = '正在登录…';
    message($('#login-feedback'), '正在验证账号…');
    const body = Object.fromEntries(new FormData(form).entries());
    try {
      const result = await request('/auth/login', {method: 'POST', body: JSON.stringify(body)});
      if (result.stale) return;
      if (!result.ok) throw new Error(apiError(result.data, result.status));
      storeToken(result.data.access_token);
      const loggedInGeneration = sessionGeneration;
      const loggedInToken = token();
      $('#login-password').value = '';
      await syncSession();
      if (loggedInGeneration !== sessionGeneration || loggedInToken !== token()) return;
      message($('#login-feedback'), '登录成功，现在可以调用当前身份有权操作的接口。', 'success');
    } catch (error) { message($('#login-feedback'), error.message, 'error'); }
    finally { button.disabled = false; button.textContent = '登录'; }
  });

  function makeField(name, schema, required, location, prefix) {
    schema = resolve(schema);
    const wrapper = el('div', `docs-field${['reason', 'remark'].includes(name) ? ' docs-field-wide' : ''}`);
    const id = `${prefix}-${location}-${name}`;
    const label = el('label', '', fieldLabel(name, schema));
    label.htmlFor = id;
    label.append(el('code', '', name));
    label.append(el('span', 'docs-required', required ? '必填' : '选填'));
    let control;
    const choices = schema.enum || (schema.type === 'boolean' ? [true, false] : null);
    if (choices) {
      control = el('select');
      control.append(new Option(required ? '请选择' : '不指定', ''));
      for (const value of choices) control.append(new Option(`${enumLabel(value, name)}${typeof value === 'boolean' ? '' : ` (${value})`}`, String(value)));
    } else if (['object', 'array'].includes(schema.type) || ['reason', 'remark'].includes(name)) {
      control = el('textarea');
      control.rows = schema.type === 'object' || schema.type === 'array' ? 5 : 2;
      control.placeholder = ['object', 'array'].includes(schema.type) ? '请填写有效的 JSON 数据' : `请输入${fieldLabel(name, schema)}`;
    } else {
      control = el('input');
      control.type = /password/i.test(name) ? 'password'
        : schema.format === 'date' || ['schedule_date', 'new_date', 'start', 'end'].includes(name) ? 'date'
        : ['start_time', 'end_time'].includes(name) ? 'time'
        : ['integer', 'number'].includes(schema.type) ? 'number' : 'text';
      if (control.type === 'password') control.autocomplete = prefix.includes('auth-login') ? 'current-password' : 'new-password';
      if (control.type === 'number') control.step = schema.type === 'integer' ? '1' : 'any';
      if (control.type === 'time') control.step = '60';
      if (schema.minimum !== undefined) control.min = schema.minimum;
      if (schema.exclusiveMinimum !== undefined) control.min = schema.exclusiveMinimum + (schema.type === 'integer' ? 1 : Number.EPSILON);
      if (schema.maximum !== undefined) control.max = schema.maximum;
      if (schema.minLength !== undefined) control.minLength = schema.minLength;
      if (schema.maxLength !== undefined) control.maxLength = schema.maxLength;
      if (schema.pattern && control.type === 'text') control.pattern = schema.pattern;
      control.placeholder = `请输入${fieldLabel(name, schema)}`;
    }
    control.id = id; control.name = `${location}:${name}`; control.required = required;
    control.dataset.location = location; control.dataset.key = name; control.dataset.valueType = schema.type || 'string';
    if (schema.default !== undefined && schema.default !== null) control.value = String(schema.default);
    const help = [];
    if (chinese(schema.description)) help.push(schema.description);
    if (schema.minLength) help.push(`至少 ${schema.minLength} 个字符`);
    if (schema.maxLength) help.push(`最多 ${schema.maxLength} 个字符`);
    if (schema.minimum !== undefined || schema.maximum !== undefined) help.push(`允许范围：${schema.minimum ?? '不限'} 至 ${schema.maximum ?? '不限'}`);
    if (name === 'student_id' && schema.pattern) help.push('仅限英文字母、数字、下划线和短横线');
    wrapper.append(label, control);
    if (help.length) {
      const hint = el('small', '', help.join('；')); hint.id = `${id}-help`;
      control.setAttribute('aria-describedby', hint.id); wrapper.append(hint);
    }
    return wrapper;
  }
  function addFields(form, title, definitions, location, prefix) {
    if (!definitions.length) return;
    const section = el('fieldset', 'docs-form-section');
    section.append(el('legend', '', title));
    const grid = el('div', 'docs-field-grid');
    for (const definition of definitions) grid.append(makeField(definition.name, definition.schema, definition.required, location, prefix));
    section.append(grid); form.append(section);
  }
  function collect(form, route) {
    const body = {}; const values = {}; const query = new URLSearchParams(); let path = route;
    for (const control of form.querySelectorAll('[data-location]')) {
      if (control.value === '' && !control.required) continue;
      let value = control.value;
      const type = control.dataset.valueType;
      if (type === 'integer' || type === 'number') value = Number(value);
      else if (type === 'boolean') value = value === 'true';
      else if (type === 'array' || type === 'object') {
        try { value = JSON.parse(value); } catch { throw new Error(`${fieldLabel(control.dataset.key)}的 JSON 格式不正确。`); }
      }
      const key = control.dataset.key;
      values[key] = /password/i.test(key) ? '已填写（内容隐藏）' : value;
      if (control.dataset.location === 'path') path = path.replace(`{${key}}`, encodeURIComponent(String(value)));
      else if (control.dataset.location === 'query') query.set(key, String(value));
      else body[key] = value;
    }
    return {path: path + (query.size ? `?${query}` : ''), body, values};
  }
  function renderData(value, key = '') {
    if (Array.isArray(value)) {
      if (!value.length) return el('p', 'docs-muted', '暂无记录');
      if (value.every(item => !item || typeof item !== 'object')) return el('span', '', value.map(item => plainValue(item, key)).join('、'));
      const container = el('div', 'docs-data-array');
      let page = 0;
      const pageSize = 10;
      const keys = [...new Set(value.flatMap(item => item && typeof item === 'object' ? Object.keys(item) : []))];
      function draw() {
        container.replaceChildren();
        const wrap = el('div', 'docs-table-wrap');
        const table = el('table', 'docs-table');
        const header = el('thead'); const headerRow = el('tr');
        for (const name of keys) { const th = el('th', '', fieldLabel(name)); th.scope = 'col'; headerRow.append(th); }
        header.append(headerRow); table.append(header);
        const tbody = el('tbody');
        for (const item of value.slice(page * pageSize, (page + 1) * pageSize)) {
          const row = el('tr');
          for (const name of keys) {
            const cell = el('td'); const nested = item?.[name];
            if (nested && typeof nested === 'object') {
              const details = el('details', 'docs-nested'); details.append(el('summary', '', '查看明细'), renderData(nested, name)); cell.append(details);
            } else cell.textContent = plainValue(nested, name);
            row.append(cell);
          }
          tbody.append(row);
        }
        table.append(tbody); wrap.append(table); container.append(wrap);
        const pager = el('div', 'docs-pager');
        pager.append(el('span', '', `共 ${value.length} 条，第 ${page + 1} / ${Math.ceil(value.length / pageSize)} 页`));
        if (value.length > pageSize) {
          for (const [label, step, disabled] of [['上一页', -1, page === 0], ['下一页', 1, (page + 1) * pageSize >= value.length]]) {
            const button = el('button', 'docs-button', label); button.type = 'button'; button.disabled = disabled;
            button.addEventListener('click', () => { page += step; draw(); }); pager.append(button);
          }
        }
        container.append(pager);
      }
      draw(); return container;
    }
    if (value && typeof value === 'object') {
      const list = el('dl', 'docs-data-list');
      if (!Object.keys(value).length) return el('span', 'docs-muted', '无附加内容');
      for (const [name, item] of Object.entries(value)) {
        list.append(el('dt', '', fieldLabel(name)));
        const description = el('dd'); description.append(renderData(item, name)); list.append(description);
      }
      return list;
    }
    return el('span', '', plainValue(value, key));
  }
  function permissionHint(path, method) {
    if (path === '/health' || path === '/auth/login') return '公开接口，可在未登录时调用。';
    if (path === '/attendance' || /leave\/\{leave_id\}/.test(path)) return '仅负责该班次的普通管理员可执行。';
    if (path === '/students' || path === '/admins' || path === '/credit-rules' || path.startsWith('/credit-rules/') || path === '/operation-logs' || path.startsWith('/service-records/') || (path === '/slots' && method === 'POST')) return '仅超级管理员可执行。';
    if (/^\/applications\/(leave|transfer|withdrawal)$/.test(path) && method === 'POST') return '仅在队志愿者可为本人提交申请。';
    if (path.includes('/transfer/{transfer_id}')) return '初审由负责原班次的普通管理员执行；终审由超级管理员执行。';
    if (path.includes('/withdrawal/{withdrawal_id}')) return '仅超级管理员可审批退队。';
    if (path === '/hours' || path === '/credit') return '志愿者可查询本人记录；超级管理员需指定学号。';
    return '需先登录，服务端将根据当前角色和数据归属校验权限。';
  }
  function schemaDescription(schema) {
    schema = resolve(schema);
    const types = {integer: '整数', number: '数值', string: '文本', boolean: '是或否', array: '列表', object: '对象', null: '空值'};
    if (schema.format === 'date') return '日期';
    if (schema.enum) return schema.enum.map(value => `${enums[value] || value} (${value})`).join('、');
    return types[schema.type] || '由业务结果决定';
  }
  function responseDefinitions(operation) {
    const details = el('details', 'docs-schema'); details.append(el('summary', '', '返回状态与数据结构'));
    const wrap = el('div', 'docs-table-wrap'); const table = el('table', 'docs-table');
    const head = el('thead'); const row = el('tr');
    for (const title of ['状态码', '含义', '返回内容']) { const th = el('th', '', title); th.scope = 'col'; row.append(th); }
    head.append(row); table.append(head);
    const body = el('tbody');
    for (const [code, response] of Object.entries(operation.responses || {})) {
      const row = el('tr'); row.append(el('td', '', code), el('td', '', chinese(response.description) ? response.description : statusNames[code] || '由服务端返回'));
      const cell = el('td');
      const schema = resolve(response.content?.['application/json']?.schema || {});
      if (schema.properties) {
        const list = el('dl', 'docs-data-list');
        for (const [key, definition] of Object.entries(schema.properties)) list.append(el('dt', '', fieldLabel(key, resolve(definition))), el('dd', '', schemaDescription(definition)));
        cell.append(list);
      } else cell.textContent = schemaDescription(schema);
      row.append(cell); body.append(row);
    }
    table.append(body); wrap.append(table); details.append(wrap);
    details.append(el('p', 'docs-muted', '其他常见状态：401 需要登录，403 权限不足，409 业务冲突，503 服务暂不可用。具体原因会在调用结果中显示。'));
    return details;
  }
  function operationForm(item) {
    const {operation, path, method, title, id} = item;
    const container = el('div', 'docs-endpoint-body');
    if (operation.description) container.append(el('p', 'docs-description', operation.description));
    container.append(el('p', 'docs-permission', permissionHint(path, method)));
    const form = el('form'); form.noValidate = true;
    const parameters = [...(spec.paths[path].parameters || []), ...(operation.parameters || [])].map(resolve);
    addFields(form, '路径参数', parameters.filter(parameter => parameter.in === 'path'), 'path', id);
    addFields(form, '查询条件', parameters.filter(parameter => parameter.in === 'query'), 'query', id);
    const bodySchema = resolve(operation.requestBody?.content?.['application/json']?.schema || {});
    const bodyFields = Object.entries(bodySchema.properties || {}).map(([name, schema]) => ({name, schema, required: (bodySchema.required || []).includes(name)}));
    addFields(form, '提交内容', bodyFields, 'body', id);
    if (!parameters.length && !bodyFields.length) form.append(el('p', 'docs-muted', '此接口无需填写参数。'));
    const actions = el('div', 'docs-actions');
    const submit = el('button', 'docs-button docs-button-primary', method === 'GET' ? '发送查询' : path === '/auth/login' ? '登录' : '检查并提交'); submit.type = 'submit';
    const isWrite = method !== 'GET' && path !== '/auth/login';
    actions.append(submit, el('p', 'docs-muted', isWrite ? '提交前会显示确认信息。' : '结果将在当前接口下方显示。'));
    const feedback = el('p', 'docs-feedback'); feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
    const confirmation = el('div', 'docs-confirm'); confirmation.hidden = true;
    const resultPanel = el('section', 'docs-result'); resultPanel.hidden = true; resultPanel.setAttribute('aria-label', '接口调用结果');
    form.append(actions, feedback, confirmation); container.append(form, responseDefinitions(operation), resultPanel);
    let busy = false; let waitingConfirmation = false;
    function lock(locked) { for (const control of form.querySelectorAll('[data-location]')) control.disabled = locked; submit.disabled = locked; }
    document.addEventListener('docs-session-changed', () => {
      if (waitingConfirmation) {
        waitingConfirmation = false; confirmation.replaceChildren(); confirmation.hidden = true; lock(false);
        message(feedback, '登录状态已变化，请重新核对内容后提交。', 'error');
      }
    });
    async function execute(payload) {
      if (busy) return;
      if (isWrite && (payload.sessionToken !== token() || payload.sessionGeneration !== sessionGeneration)) {
        waitingConfirmation = false; confirmation.hidden = true; lock(false);
        message(feedback, '登录状态已变化，请重新核对内容后提交。', 'error');
        return;
      }
      busy = true; waitingConfirmation = false; confirmation.hidden = true; lock(true);
      submit.textContent = '正在请求…'; message(feedback, '正在等待服务端处理…');
      resultPanel.hidden = true;
      const started = performance.now();
      try {
        const response = await request(payload.path, {method, ...(operation.requestBody ? {body: JSON.stringify(payload.body)} : {})});
        if (response.stale) {
          message(feedback, '登录状态已变化，本次结果未展示。若已提交修改，请使用原账号查询处理结果。');
          return;
        }
        if (path === '/auth/login' && response.ok && response.data?.access_token) {
          storeToken(response.data.access_token);
          const loggedInGeneration = sessionGeneration;
          const loggedInToken = token();
          for (const control of form.querySelectorAll('input[type="password"]')) control.value = '';
          await syncSession();
          if (loggedInGeneration !== sessionGeneration || loggedInToken !== token()) return;
        }
        const safe = redact(response.data);
        resultPanel.replaceChildren(el('h3', '', '调用结果'));
        const status = el('p', 'docs-result-status', `${response.ok ? '执行成功' : '执行未成功'} · 状态码 ${response.status} · 用时 ${Math.round(performance.now() - started)} 毫秒`);
        status.dataset.state = response.ok ? 'success' : 'error';
        resultPanel.append(status, el('code', 'docs-result-request', `${method} ${payload.path}`));
        if (!response.ok) resultPanel.append(el('p', '', apiError(response.data, response.status)));
        else resultPanel.append(renderData(safe));
        const raw = el('details', 'docs-raw'); raw.append(el('summary', '', '查看原始 JSON（敏感内容已隐藏）'), el('pre', '', JSON.stringify(safe, null, 2)));
        resultPanel.append(raw); resultPanel.hidden = false;
        message(feedback, response.ok ? '请求已完成。' : apiError(response.data, response.status), response.ok ? 'success' : 'error');
      } catch (error) { message(feedback, error.message, 'error'); }
      finally { busy = false; lock(false); submit.textContent = method === 'GET' ? '再次查询' : path === '/auth/login' ? '登录' : '检查并提交'; }
    }
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (busy || waitingConfirmation || !validForm(form)) return;
      if (path !== '/health' && path !== '/auth/login' && !token()) {
        message(feedback, '请先在页面上方登录，再执行此操作。', 'error');
        $('#docs-auth').open = true; $('#login-account').focus(); return;
      }
      let payload;
      try { payload = collect(form, path); } catch (error) { message(feedback, error.message, 'error'); return; }
      payload.sessionToken = token();
      payload.sessionGeneration = sessionGeneration;
      if (!isWrite) { execute(payload); return; }
      waitingConfirmation = true; lock(true); message(feedback, '请核对以下信息后确认。');
      confirmation.replaceChildren(el('h3', '', `确认${title}`), el('p', '', `即将执行「${title}」，这会更改数据库记录。请核对以下信息。`), renderData(payload.values));
      const controls = el('div', 'docs-actions');
      const confirm = el('button', 'docs-button docs-button-primary', '确认提交'); confirm.type = 'button';
      const cancel = el('button', 'docs-button', '返回修改'); cancel.type = 'button';
      confirm.addEventListener('click', () => { confirm.disabled = true; cancel.disabled = true; execute(payload); }, {once: true});
      cancel.addEventListener('click', () => { waitingConfirmation = false; confirmation.hidden = true; lock(false); message(feedback, '已取消提交，可以继续修改。'); submit.focus(); });
      controls.append(confirm, cancel); confirmation.append(controls); confirmation.hidden = false; confirm.focus();
    });
    return container;
  }
  function buildDocs() {
    const content = $('#docs-content'); const nav = $('#docs-nav'); content.replaceChildren(); nav.replaceChildren();
    const groups = new Map();
    for (const [path, methods] of Object.entries(spec.paths || {})) {
      for (const [verb, operation] of Object.entries(methods)) {
        if (!['get', 'post', 'put', 'patch', 'delete', 'head', 'options'].includes(verb)) continue;
        const method = verb.toUpperCase();
        const title = chinese(operation.summary) ? operation.summary : fallbackTitles[`${method} ${path}`] || '业务接口';
        const group = operation.tags?.[0] || '其他接口';
        const id = `endpoint-${method.toLowerCase()}-${path.replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '')}-${++idCounter}`;
        const item = {path, method, title, operation, group, id};
        operations.push(item);
        if (!groups.has(group)) groups.set(group, []);
        groups.get(group).push(item);
      }
    }
    for (const [group, items] of groups) {
      const groupId = `group-${++idCounter}`;
      const section = el('section', 'docs-group'); section.id = groupId;
      const heading = el('div', 'docs-group-heading'); heading.append(el('h2', '', group), el('span', '', `${items.length} 个接口`)); section.append(heading);
      const link = el('a', 'docs-nav-link'); link.href = `#${groupId}`; link.append(el('span', '', group), el('small', '', items.length));
      link.addEventListener('click', () => {
        $('#docs-search').value = ''; filterDocs('');
        for (const navLink of nav.querySelectorAll('a')) navLink.removeAttribute('aria-current');
        link.setAttribute('aria-current', 'true');
      });
      nav.append(link);
      for (const item of items) {
        const details = el('details', 'docs-endpoint'); details.id = item.id;
        const summary = el('summary');
        const badge = el('span', 'docs-method', item.method); badge.dataset.write = String(item.method !== 'GET');
        const texts = el('span'); texts.append(el('span', 'docs-endpoint-title', item.title), el('code', 'docs-path', item.path));
        summary.append(badge, texts); details.append(summary); item.element = details;
        let built = false;
        details.addEventListener('toggle', () => { if (details.open && !built) { built = true; details.append(operationForm(item)); } });
        section.append(details);
      }
      content.append(section);
    }
    const empty = el('div', 'docs-empty', '没有找到匹配的接口，请尝试输入“排班”“考勤”或接口路径。'); empty.id = 'docs-no-match'; empty.hidden = true; content.append(empty);
    filterDocs('');
  }
  function filterDocs(value) {
    const query = value.trim().toLowerCase(); let shown = 0;
    for (const item of operations) {
      const match = `${item.title} ${item.path} ${item.method} ${item.group} ${item.operation.description || ''}`.toLowerCase().includes(query);
      item.element.hidden = !match; if (match) shown += 1;
    }
    for (const group of document.querySelectorAll('.docs-group')) group.hidden = !Array.from(group.querySelectorAll('.docs-endpoint')).some(node => !node.hidden);
    $('#docs-count').textContent = query ? `找到 ${shown} 个接口，共 ${operations.length} 个` : `共 ${operations.length} 个接口，展开后可查看字段并执行调用`;
    $('#docs-no-match').hidden = shown > 0;
  }
  $('#docs-search').addEventListener('input', event => { if (spec) filterDocs(event.target.value); });
  async function loadDocs() {
    $('#docs-count').textContent = '正在读取接口定义…';
    $('#docs-content').replaceChildren(el('div', 'docs-loading', '正在加载接口文档…'));
    try {
      const response = await request('/openapi.json');
      if (!response.ok || !response.data?.paths) throw new Error('暂时无法读取接口定义，请稍后重试。');
      spec = response.data; operations = []; buildDocs();
    } catch (error) {
      $('#docs-count').textContent = '接口定义尚未加载';
      $('#docs-nav').replaceChildren(el('p', 'docs-muted', '目录暂不可用'));
      const notice = el('div', 'docs-notice'); notice.append(el('p', '', error.message));
      const retry = el('button', 'docs-button', '重新加载'); retry.type = 'button'; retry.addEventListener('click', loadDocs); notice.append(retry);
      $('#docs-content').replaceChildren(notice);
    }
  }
  syncSession();
  window.addEventListener('pageshow', event => { if (event.persisted) syncSession(); });
  loadDocs();
})();
