/**
 * 业务管理三级导航扩展
 * 实现：业务列表 → 班次/小组 → 队员
 */
'use strict';

// 顶栏面包屑跟着当前层级走，避免停在第三级仍显示「业务管理」
function businessTrail(){
  const tab = state.tab || 'list';
  const biz = state.data.businesses || [];
  const businessOf = id => biz.find(b => b.business_id == id);
  let parts = ['业务管理'];
  if(tab === 'slots' || tab === 'groups'){
    const b = businessOf(state.businessId);
    if(b) parts.push(b.name);
  }else if(tab === 'slot-members'){
    const slot = (state.data.slots||[]).find(s => s.slot_id == state.slotId);
    const b = slot ? businessOf(slot.business_id) : null;
    if(b) parts.push(b.name);
    if(slot) parts.push(slotName(slot.slot_id));
  }else if(tab === 'group-members'){
    const g = (state.data.groups||[]).find(x => x.group_id == state.groupId);
    const b = g ? businessOf(g.business_id) : null;
    if(b) parts.push(b.name);
    if(g) parts.push(g.name);
  }
  return parts.join(' · ');
}

// 业务管理三级页路由：list / slots / groups / slot-members / group-members
function businessesPage(){
  const tab = state.tab || 'list';
  if($('#breadcrumb-title')) $('#breadcrumb-title').textContent = businessTrail();

  // 第3层：班次队员列表
  if(tab === 'slot-members' && state.slotId){
    renderSlotMembers(state.slotId);
    return;
  }

  // 第3层：小组成员列表
  if(tab === 'group-members' && state.groupId){
    renderGroupMembers(state.groupId);
    return;
  }

  // 第2层：服务班次列表
  if(tab === 'slots' && state.businessId){
    renderBusinessSlots(state.businessId);
    return;
  }

  // 第2层：小组列表
  if(tab === 'groups' && state.businessId){
    renderBusinessGroups(state.businessId);
    return;
  }

  // 第1层：业务列表
  renderBusinessListEnhanced();
}
window.businessesPage = businessesPage;

// 页内面包屑：items = [[文字, 动作, id], ...]，最后一项为当前页
function crumbs(items){
  return `<nav class="page-crumbs" aria-label="面包屑">${items.map(([text, action, id], i) =>
    i === items.length - 1
      ? `<span class="crumb-current" aria-current="page">${esc(text)}</span>`
      : `<button class="link" type="button" data-action="${action}"${id !== undefined ? ` data-id="${id}"` : ''}>${esc(text)}</button>`
  ).join('<span class="crumb-sep" aria-hidden="true">/</span>')}</nav>`;
}

// 第1层：业务列表（增强版，添加"查看班次/小组"按钮）
async function renderBusinessListEnhanced(){
  const seq = ++state.sequence;
  const editable = state.role === 'SUPER';
  const biz = state.data.businesses || [];

  $('#main').innerHTML = heading('业务管理','管理业务、服务班次和小组。',
    editable ? '<button class="btn primary" data-action="business-create">新增业务</button>' : '') +
    `<section class="panel">${table(
      ['业务名称','类型','状态','操作'],
      biz.filter(b => editable || b.status === 'ACTIVE').map(b => `<tr>
        <td><strong>${esc(b.name)}</strong></td>
        <td>${b.kind==='FIXED'?'固定时段':b.kind==='WEEKLY'?'按周统计':'非固定业务'}</td>
        <td>${badge(b.status||'ACTIVE')}</td>
        <td>
          ${['FIXED','WEEKLY'].includes(b.kind) ?
            `<button class="text-button" data-action="view-business-slots" data-id="${b.business_id}">查看班次</button>` :
            `<button class="text-button" data-action="view-business-groups" data-id="${b.business_id}">查看小组</button>`}
          ${editable ?
            (b.status === 'ARCHIVED' ?
              `<button class="text-button" data-action="business-restore" data-id="${b.business_id}">恢复业务</button>` :
              `<button class="text-button" data-action="business-archive" data-id="${b.business_id}">归档</button>` +
              `<button class="text-button" data-action="business-rename" data-id="${b.business_id}">改名</button>`) : ''}
        </td>
      </tr>`)
    )}</section>`;
}

// 业务总负责人本地没有全局管理员列表，只按本业务拉候选管理员
async function ensureBusinessAdmins(business){
  state.businessAdmins = [];
  if(!business || !business.can_manage) return;
  try{
    const list = await request(`/businesses/${business.business_id}/admins`);
    state.businessAdmins = list || [];
  }catch(e){ /* 候选管理员读不到时只是选择列表为空，不影响列表页 */ }
}

// 第2层：服务班次列表（按星期折叠；分队负责人、时段负责人、总负责人三层各自独立）
async function renderBusinessSlots(businessId){
  const seq = ++state.sequence;
  const business = (state.data.businesses||[]).find(b => b.business_id == businessId);
  if(!business){
    $('#main').innerHTML = `<section class="panel">${empty('业务不存在','')}</section>`;
    return;
  }

  // 获取该业务的班次；时段不再支持停用，页面只展示当前目录
  const slots = (state.data.slots||[]).filter(s => s.business_id == businessId);

  // 现人数按 slot_member 归属统计，与「查看成员」页的名单来源保持一致
  const stats = {};
  for(const slot of slots){
    stats[slot.slot_id] = (state.data.students||[])
      .filter(st => (st.slots||[]).some(t => String(t.slot_id) === String(slot.slot_id))).length;
  }

  if(seq !== state.sequence) return;

  await ensureBusinessAdmins(business);

  const editable = (state.role === 'SUPER' || (business.can_write === undefined ? business.can_manage : business.can_write)) && business.status === 'ACTIVE';
  const dayName = d => '周' + '一二三四五六日'[Number(d) - 1];
  const head = ['时段','服务时间','现人数/建议人数','认定时长','操作'];
  const rowHtml = slot => `<tr>
      <td><strong>${esc(slotLabel(slot))}</strong>${slot.weekday?'':`<small>第 ${slot.period_no} 时段</small>`}</td>
      <td>${esc(slot.start_time)} 至 ${esc(slot.end_time)}</td>
      <td>${stats[slot.slot_id] || 0} / ${slot.need_num ? slot.need_num + ' 人' : '—'}</td>
      <td>${hourText(slot.service_minutes)}</td>
      <td><button class="text-button" data-action="view-slot-members" data-id="${slot.slot_id}">查看成员</button>${editable ? `<button class="text-button" data-action="edit-slot-config" data-id="${slot.slot_id}">修改设置</button>` : ''}</td>
    </tr>`;

  // 分队负责人：业务 × 星期一条，独立于时段负责人与总负责人
  const teamLeaders = {};
  (business.leaders||[]).forEach(l => {
    if(Number(l.weekday) >= 1 && Number(l.weekday) <= 7) teamLeaders[Number(l.weekday)] = l;
  });

  const days = [...new Set(slots.filter(s => s.weekday).map(s => Number(s.weekday)))].sort((a, b) => a - b);
  const weekly = slots.filter(s => !s.weekday);

  let body = '';
  for(const day of days){
    const rows = slots.filter(s => Number(s.weekday) === day);
    const leader = teamLeaders[day];
    const leaderName = leader && leader.admin_name;
    body += `<details class="slot-week">
      <summary>
        <span class="slot-week-name">${dayName(day)}</span>
        <span class="slot-week-side">
          ${leaderName ? `<span class="slot-week-manager">分队负责人：${esc(leaderName)}</span>` : ''}
          ${editable ? `<button class="text-button" data-action="team-leader" data-id="${businessId}" data-kind="${day}">${leaderName ? '修改负责人' : '设置负责人'}</button>` : ''}
        </span>
      </summary>
      <div class="slot-week-body">${table(head, rows.map(rowHtml), '暂无时段')}</div>
    </details>`;
  }
  if(weekly.length) body += `<div class="slot-week-body">${table(head, weekly.map(rowHtml), '暂无时段')}</div>`;
  if(!slots.length) body = empty('暂无班次','');

  // 总负责人是业务级独立字段，不参与分队负责人与时段负责人的计算
  const owner = business.total_manager_name;
  const ownerButton = state.role === 'SUPER'
    ? `<button class="btn" data-action="business-owner" data-id="${businessId}">${owner ? '总负责人：' + esc(owner) : '设置总负责人'}</button>`
    : (owner ? `<span class="muted">总负责人：${esc(owner)}</span>` : '');
  const importButtons = editable
    ? `<button class="btn" data-action="excel-import" data-kind="BUSINESS" data-id="${businessId}">Excel 导入</button>
       <button class="btn" data-action="import-records" data-id="${businessId}">导入记录</button>` : '';
  const buttons = editable
    ? (business.kind === 'FIXED'
      ? `${importButtons}<button class="btn primary" data-action="business-slot" data-id="${businessId}">添加时段</button>${ownerButton}`
      : importButtons + ownerButton)
    : '';

  $('#main').innerHTML =
    crumbs([['业务管理','back-to-business-list'], [business.name]]) +
    heading(`${business.name} · 服务班次`, '', buttons, 'compact') +
    (body ? `<section class="panel slot-week-list">${body}</section>` : '');
}

// 第2层：小组列表
async function renderBusinessGroups(businessId){
  const seq = ++state.sequence;
  const business = (state.data.businesses||[]).find(b => b.business_id == businessId);
  if(!business){
    $('#main').innerHTML = `<section class="panel">${empty('业务不存在','')}</section>`;
    return;
  }

  const groups = (state.data.groups||[]).filter(g => g.business_id == businessId);

  if(seq !== state.sequence) return;

  await ensureBusinessAdmins(business);
  if(seq !== state.sequence) return;

  const owner = business.total_manager_name;
  const canManage = state.role === 'SUPER' || business.can_manage;
  const canWrite = state.role === 'SUPER' || business.can_write;
  const ownerButton = state.role === 'SUPER'
    ? `<button class="btn" data-action="business-owner" data-id="${businessId}">${owner ? '总负责人：' + esc(owner) : '设置总负责人'}</button>`
    : (owner ? `<span class="muted">总负责人：${esc(owner)}</span>` : '');
  const groupButtons = canWrite && business.status === 'ACTIVE'
    ? (business.kind === 'EVENT' ? `<button class="btn" data-action="excel-import" data-kind="BUSINESS" data-id="${businessId}">Excel 导入</button>
        <button class="btn" data-action="import-records" data-id="${businessId}">导入记录</button>
        <button class="btn primary" data-action="create-group" data-id="${businessId}">添加小组</button>` : '') + ownerButton
    : '';
  $('#main').innerHTML =
    crumbs([['业务管理','back-to-business-list'], [business.name]]) +
    heading(`${business.name} · 小组管理`, '', groupButtons, 'compact') +
    `<section class="panel">${groups.length ? table(
      ['小组名称','成员数','操作'],
      groups.map(g => `<tr>
        <td><strong>${esc(g.name)}</strong></td>
        <td>${g.member_count || 0} 人</td>
        <td>
          <button class="text-button" data-action="view-group-members" data-id="${g.group_id}">查看成员</button>
        </td>
      </tr>`)
    ) : empty('暂无小组','')}</section>`;
}

// 第3层：班次队员列表
function slotMemberButtons(slot, business){
  const canManage = state.role === 'SUPER' || (business.can_write === undefined ? business.can_manage : business.can_write);
  if(!canManage || business.status !== 'ACTIVE' || business.kind !== 'FIXED') return '';
  return `<div class="button-row">
    <button class="btn" data-action="excel-import" data-kind="SLOT" data-id="${slot.slot_id}">导入本班次</button>
    <button class="btn primary" data-action="add-slot-member" data-id="${slot.slot_id}">新增队员</button>
  </div>`;
}

function renderSlotMembers(slotId){
  const slot = (state.data.slots||[]).find(s => s.slot_id == slotId);
  if(!slot){
    $('#main').innerHTML = `<section class="panel">${empty('班次不存在','')}</section>`;
    return;
  }

  const business = (state.data.businesses||[]).find(b => b.business_id == slot.business_id) ||
    {business_id:slot.business_id, name:'该业务', kind:'', status:''};

  // 名单来源改为 slot_member（state.data.students 的 slots），导入/新增写入后本页即时可见。
  const students = (state.data.students||[]).filter(st => (st.slots||[]).some(t => String(t.slot_id) === String(slot.slot_id)));
  const meScope = state.me?.scope || {};
  const mySlotIds = new Set((meScope.slot_ids || []).map(String));
  const myBusinessIds = new Set((meScope.total_business_ids || []).map(String));
  const canAffiliate = state.role === 'SUPER' || (state.role === 'NORMAL' &&
    (slot.manager_admin_id === state.me.admin_id || mySlotIds.has(String(slot.slot_id)) || myBusinessIds.has(String(slot.business_id))));

  $('#main').innerHTML =
    crumbs([['业务管理','back-to-business-list'], [business.name,'back-to-business-slots',business.business_id], [slotName(slot.slot_id)]]) +
    heading(`${business.name} · ${slotName(slot.slot_id)} · 队员名单`, '',
      slotMemberButtons(slot, business), 'compact') +
    '<p class="page-note">名单须含「姓名」「学号」两列。</p>' +
    `<section class="panel">${students.length ? table(
      ['学号','姓名','学院','状态','操作'],
      students.map(st => `<tr>
        <td><strong>${esc(st.student_id)}</strong></td>
        <td>${esc(st.name)}</td>
        <td>${esc(st.college||'未填写')}</td>
        <td>${badge(st.status||'UNKNOWN')}</td>
        <td>
          <button class="text-button" data-action="view-student-profile-quick" data-id="${esc(st.student_id)}">查看资料</button>
          ${canAffiliate ? `<button class="text-button" data-action="change-affiliation" data-id="${esc(st.student_id)}">更改归属</button>` : ''}
        </td>
      </tr>`)
    ) : empty('暂无队员','')}</section>`;
}

// 第3层：小组成员列表
async function renderGroupMembers(groupId){
  const seq = ++state.sequence;
  const group = (state.data.groups||[]).find(g => g.group_id == groupId);
  if(!group){
    $('#main').innerHTML = `<section class="panel">${empty('小组不存在','')}</section>`;
    return;
  }

  const business = (state.data.businesses||[]).find(b => b.business_id == group.business_id) ||
    {business_id:group.business_id, name:'该业务', kind:'', status:''};
  const canImport = (state.role === 'SUPER' || (business.can_write === undefined ? business.can_manage : business.can_write)) && business.status === 'ACTIVE' && business.kind === 'EVENT';
  const canAffiliateGroup = state.role === 'SUPER' || (state.role === 'NORMAL' && new Set(((state.me?.scope?.total_business_ids) || []).map(String)).has(String(group.business_id)));
  const buttons = canImport ? `<div class="button-row">
      <button class="btn" data-action="excel-import" data-kind="GROUP" data-id="${group.group_id}">导入本小组成员</button>
      <button class="btn primary" data-action="add-group-member" data-id="${group.group_id}">新增成员</button>
    </div>` : '';

  try {
    const members = await request(`/business-groups/${groupId}/members`);
    if(seq !== state.sequence) return;

    $('#main').innerHTML =
      crumbs([['业务管理','back-to-business-list'], [business.name,'back-to-business-groups',business.business_id], [group.name]]) +
      heading(`${business.name} · ${group.name} · 成员名单`, '', buttons, 'compact') +
      '<p class="page-note">名单须含「姓名」「学号」两列。</p>' +
      `<section class="panel">${members.length ? table(
        ['学号','姓名','状态','操作'],
        members.map(m => `<tr>
          <td><strong>${esc(m.student_id)}</strong></td>
          <td>${esc(m.name)}</td>
          <td>${badge(m.status)}</td>
          <td>
            <button class="text-button" data-action="view-student-profile-quick" data-id="${esc(m.student_id)}">查看资料</button>
            ${canAffiliateGroup ? `<button class="text-button" data-action="change-affiliation" data-id="${esc(m.student_id)}">更改归属</button>` : ''}
          </td>
        </tr>`)
      ) : empty('暂无成员','')}</section>`;
  } catch(e) {
    if(seq === state.sequence) $('#main').innerHTML = `<section class="panel">${empty('读取失败', e.message)}</section>`;
  }
}

// 快速查看学生资料（弹窗）
function viewStudentProfileQuick(studentId){
  const student = (state.data.students||[]).find(s => s.student_id === studentId);
  if(!student){
    notify('未找到该队员信息', true);
    return;
  }

  previousFocus = document.activeElement;
  modalSubmit = null;
  modalVersion++;

  dialog.innerHTML = `
    <header class="dialog-header">
      <h2 id="dialog-title">队员资料 · ${esc(student.name)}</h2>
      <button class="close-button" data-action="close">关闭</button>
    </header>
    <div class="dialog-body">
      <div class="data-list">
        <div class="field-row">
          <label>学号</label>
          <span>${esc(student.student_id)}</span>
        </div>
        <div class="field-row">
          <label>姓名</label>
          <span>${esc(student.name)}</span>
        </div>
        <div class="field-row">
          <label>学院</label>
          <span>${esc(student.college||'未填写')}</span>
        </div>
        <div class="field-row">
          <label>联系电话</label>
          <span>${esc(student.phone||'未填写')}</span>
        </div>
        <div class="field-row">
          <label>状态</label>
          <span>${badge(student.status)}</span>
        </div>
        <div class="field-row">
          <label>信用分</label>
          <span>${student.credit_score||100} 分</span>
        </div>
      </div>
    </div>`;

  dialog.showModal();
}

// 新增队员／成员弹窗共用的账号字段
function newAccountFields(){
  return field('student_id','学号',{maxLength:32}) +
    field('name','姓名',{maxLength:100}) +
    field('college','学院（选填）',{required:false,maxLength:100}) +
    field('phone','联系电话（选填）',{required:false,maxLength:32}) +
    field('password','初始密码',{type:'password',full:true,maxLength:128});
}

async function createStudentAccount(values){
  const password = values.password || '';
  if(password.length < 8 || password.length > 128) throw new Error('初始密码需要 8 至 128 个字符。');
  const sid = String(values.student_id || '').trim();
  if(!sid) throw new Error('请填写学号。');
  const created = await send('/students',
    {student_id: sid, name: values.name, college: values.college || '', phone: values.phone || '', password});
  return {sid, created};
}

// 扩展businessAction函数
let _originalBusinessAction = null;
if(typeof businessAction === 'function'){
  _originalBusinessAction = businessAction;
}

window.businessAction = function businessAction(name, id, kind, studentId){
  // 第1层 → 第2层：查看班次
  if(name === 'view-business-slots'){
    state.businessId = id;
    state.tab = 'slots';
    window.businessesPage();
    return true;
  }

  // 第1层 → 第2层：查看小组
  if(name === 'view-business-groups'){
    state.businessId = id;
    state.tab = 'groups';
    window.businessesPage();
    return true;
  }

  // 第2层 → 第3层：查看班次队员
  if(name === 'view-slot-members'){
    const slot = (state.data.slots||[]).find(s => s.slot_id == id);
    if(slot) state.businessId = slot.business_id;
    state.slotId = id;
    state.tab = 'slot-members';
    window.businessesPage();
    return true;
  }

  // 第2层 → 第3层：查看小组成员
  if(name === 'view-group-members'){
    const group = (state.data.groups||[]).find(g => g.group_id == id);
    if(group) state.businessId = group.business_id;
    state.groupId = id;
    state.tab = 'group-members';
    window.businessesPage();
    return true;
  }

  // 面包屑导航：返回业务列表
  if(name === 'back-to-business-list'){
    state.tab = 'list';
    state.businessId = null;
    state.slotId = null;
    state.groupId = null;
    window.businessesPage();
    return true;
  }

  // 面包屑导航：返回班次列表
  if(name === 'back-to-business-slots'){
    state.businessId = id;
    state.tab = 'slots';
    state.slotId = null;
    window.businessesPage();
    return true;
  }

  // 面包屑导航：返回小组列表
  if(name === 'back-to-business-groups'){
    state.businessId = id;
    state.tab = 'groups';
    state.groupId = null;
    window.businessesPage();
    return true;
  }

  // 快速查看队员资料
  if(name === 'view-student-profile-quick'){
    viewStudentProfileQuick(id);
    return true;
  }

  // 分队负责人：业务 × 星期一条范围，独立于时段负责人和总负责人
  if(name === 'team-leader'){
    const business = (state.data.businesses||[]).find(b => b.business_id == id);
    if(!business) return true;
    const day = Number(kind) || 0;
    if(!day) return true;
    const dayName = d => '周' + '一二三四五六日'[d - 1];
    const leader = (business.leaders||[]).find(l => Number(l.weekday) === day) || {};
    const options = [['', '不设置'], ...(state.businessAdmins||[]).filter(a => a.role === 'NORMAL' && a.status === 'ACTIVE').map(a => [a.admin_id, `${a.name}（${a.account}）`])];
    if(leader.admin_id && !options.some(o => String(o[0]) === String(leader.admin_id))) options.splice(1, 0, [leader.admin_id, leader.admin_name || `管理员 ${leader.admin_id}`]);
    openDialog(`${business.name} · ${dayName(day)}分队负责人`, '',
      field('admin_id', '分队负责人', {
        options,
        value: leader.admin_id || '', required: false, full: true
      }) + reasonField(),
      v => send(`/businesses/${business.business_id}/leaders/${day}`, {admin_id: v.admin_id ? Number(v.admin_id) : null, reason: v.reason}, 'PUT').then(() => {
        state.tab = 'slots';
        window.businessesPage();
      }),
      '保存负责人');
    return true;
  }

  // 业务总负责人：独立字段，不覆盖时段负责人
  if(name === 'business-owner'){
    const business = (state.data.businesses||[]).find(b => b.business_id == id);
    if(!business) return true;
    const options = [['', '不设置'], ...(state.businessAdmins||[]).filter(a => a.role === 'NORMAL' && a.status === 'ACTIVE').map(a => [a.admin_id, `${a.name}（${a.account}）`])];
    if(business.total_manager_admin_id && !options.some(o => String(o[0]) === String(business.total_manager_admin_id))) options.splice(1, 0, [business.total_manager_admin_id, business.total_manager_name || `管理员 ${business.total_manager_admin_id}`]);
    openDialog(`${business.name} · 总负责人`, '',
      field('owner_admin_id', '总负责人', {
        options,
        value: business.total_manager_admin_id || '', required: false, full: true
      }) + reasonField(),
      v => send(`/businesses/${business.business_id}/owner`, {owner_admin_id: v.owner_admin_id ? Number(v.owner_admin_id) : null, reason: v.reason}, 'PUT').then(() => {
        window.businessesPage();
      }),
      '保存总负责人');
    return true;
  }

  // 修改班次设置（负责人和建议人数）
  if(name === 'edit-slot-config'){
    const slot = (state.data.slots||[]).find(s => s.slot_id == id);
    if(!slot) return true;

    const slotAdmins = [['', '待分配'], ...(state.businessAdmins||[]).filter(a => a.role === 'NORMAL' && a.status === 'ACTIVE').map(a => [a.admin_id, `${a.name}（${a.account}）`])];
    if(slot.manager_admin_id && !slotAdmins.some(o => String(o[0]) === String(slot.manager_admin_id))) slotAdmins.splice(1, 0, [slot.manager_admin_id, slot.manager_name || `管理员 ${slot.manager_admin_id}`]);
    openDialog(
      '修改班次设置',
      `${slotName(slot.slot_id)} · 设置班次负责人和建议人数。`,
      field('manager_admin_id', '班次负责人', {
        options: slotAdmins,
        value: slot.manager_admin_id || '',
        required: false,
        full: true
      }) +
      field('need_num', '建议人数', {
        type: 'number',
        min: 1,
        max: 10000,
        step: 1,
        value: slot.need_num || '',
        required: false,
        full: true,
        help: '可留空；仅作建议人数，不影响名单导入。'
      }),
      v => send(`/slots/${id}`, {
        manager_admin_id: v.manager_admin_id ? Number(v.manager_admin_id) : null,
        need_num: v.need_num ? Number(v.need_num) : null
      }, 'PATCH').then(() => {
        // 更新成功后刷新页面
        state.tab = 'slots';
        window.businessesPage();
      })
    );
    return true;
  }

  // 前往完整资料页面
  if(name === 'go-to-student-detail'){
    dialog.close();
    state.page = 'basics';
    state.tab = 'students';
    state.searchStudent = id; // 标记要搜索的学生
    navigate();
    return true;
  }

  // 班次队员名单：Excel 导入（业务锁定为当前班次所属业务）
  if(name === 'import-roster'){
    const slot = (state.data.slots||[]).find(s => s.slot_id == id);
    rosterAction('import-roster', slot ? slot.business_id : null);
    return true;
  }

  // 班次队员名单：新增队员（只建新账号，再并入本班次）
  if(name === 'add-slot-member'){
    const slot = (state.data.slots||[]).find(s => s.slot_id == id);
    if(!slot) return true;
    openDialog('新增队员', '',
      newAccountFields() + reasonField(),
      async v => {
        const {sid, created} = await createStudentAccount(v);
        const real = created.student_id || sid;
        try {
          // 归属接口是整体替换，必须先取回该生已有归属再合并，读不到就中止，避免误删其他归属。
          const list = await request('/students?student_id=' + encodeURIComponent(real));
          const current = (list || []).find(s => s.student_id === real);
          if(!current) throw new Error('读取该生已有归属失败');
          const slotIds = [...new Set([...(current.slots || []).map(t => Number(t.slot_id)), Number(slot.slot_id)])];
          await send('/students/' + encodeURIComponent(real) + '/slots',
            {slot_ids: slotIds, effective_date: getDate(), reason: v.reason}, 'PUT');
        } catch (e) {
          throw new Error(`账号 ${real} 已创建，但加入本班次失败：${e.message} 请到「队员资料」用「设置归属时段」补上。`);
        }
        return {changed: false};
      }, '创建并加入');
    return true;
  }

  // 成员名单：移出本班次（只动这个班次，未来该班次排班取消，历史保留）
  if(name === 'remove-slot-member'){
    const slot = (state.data.slots||[]).find(s => s.slot_id == id);
    if(!slot || !studentId) return true;
    const st = (state.data.students||[]).find(s => s.student_id === studentId);
    openDialog('移出本班次队员',
      `将「${st ? st.name : studentId}」移出「${slotName(slot.slot_id)}」。未来已生成的该班次排班会被取消，历史考勤与时长保留。`,
      reasonField(),
      v => send('/slots/' + encodeURIComponent(slot.slot_id) + '/members/' + encodeURIComponent(studentId),
        {reason: v.reason}, 'DELETE'),
      '确认移出');
    return true;
  }

  // 成员名单：改为统一设置归属，可同时调整固定时段、专项业务和小组，也可设为无归属
  if(name === 'change-affiliation'){
    const st = (state.data.students||[]).find(s => s.student_id === id);
    if(!st){ notify('队员资料已变化，请刷新页面。', true); return true; }
    openAffiliationDialog(st);
    return true;
  }

  if(name === 'remove-group-member'){
    const group = (state.data.groups||[]).find(g => g.group_id == id);
    if(!group || !studentId) return true;
    const st = (state.data.students||[]).find(s => s.student_id === studentId);
    openDialog('移出本小组成员',
      `将「${st ? st.name : studentId}」移出「${group.name}」。其他小组、业务归属与历史时长不受影响。`,
      reasonField(),
      v => send('/business-groups/' + encodeURIComponent(group.group_id) + '/members/' + encodeURIComponent(studentId),
        {active: false, effective_date: getDate(), reason: v.reason}, 'PUT'),
      '确认移出');
    return true;
  }

  // 成员名单：新增成员（只建新账号，再登记小组归属）
  if(name === 'add-group-member'){
    const group = (state.data.groups||[]).find(g => g.group_id == id);
    if(!group) return true;
    openDialog('新增成员', '',
      newAccountFields() + reasonField(),
      async v => {
        const {sid, created} = await createStudentAccount(v);
        const real = created.student_id || sid;
        try {
          await send('/business-groups/' + encodeURIComponent(group.group_id) + '/members/' + encodeURIComponent(real),
            {active: true, effective_date: getDate(), reason: v.reason}, 'PUT');
        } catch (e) {
          throw new Error(`账号 ${real} 已创建，但加入本小组失败：${e.message}`);
        }
        return {changed: false};
      }, '创建并加入');
    return true;
  }

  // 小组管理：新增小组（非固定业务下按需建组）
  if(name === 'create-group'){
    const business = (state.data.businesses||[]).find(b => b.business_id == id);
    if(!business) return true;
    openDialog('添加 ' + business.name + ' 的小组', '',
      field('name', '小组名称', {maxLength: 100, full: true}) + reasonField(),
      v => send('/business-groups', {business_id: Number(business.business_id), name: v.name, reason: v.reason}, 'POST'),
      '添加小组');
    return true;
  }

  // 其他操作：调用原始函数
  if(_originalBusinessAction) return _originalBusinessAction(name, id, kind);
  return false;
};
