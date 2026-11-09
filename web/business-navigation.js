/**
 * 业务管理三级导航扩展
 * 实现：业务列表 → 班次/小组 → 队员
 */
'use strict';

// 保存原有的 businessesPage 引用（延迟保存）
let _originalBusinessesPage = null;

// 扩展的 businessesPage 函数
const _newBusinessesPage = function businessesPage(){
  const tab = state.tab || 'list';

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
  if(tab === 'list' || !tab){
    renderBusinessListEnhanced();
    return;
  }

  // 其他情况：调用原函数
  if(_originalBusinessesPage) _originalBusinessesPage();
};

// 在第一次调用时保存原函数
if(typeof businessesPage === 'function'){
  _originalBusinessesPage = businessesPage;
}
// 替换为新函数
window.businessesPage = _newBusinessesPage;

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
            `<button class="text-button" data-action="view-business-slots" data-id="${b.business_id}">查看班次 →</button>` :
            `<button class="text-button" data-action="view-business-groups" data-id="${b.business_id}">查看小组 →</button>`}
          ${editable ?
            (b.status === 'ARCHIVED' ?
              `<button class="text-button" data-action="business-restore" data-id="${b.business_id}">恢复业务</button>` :
              `<button class="text-button" data-action="business-archive" data-id="${b.business_id}">归档</button>`) : ''}
        </td>
      </tr>`)
    )}</section>`;
}

// 第2层：服务班次列表
async function renderBusinessSlots(businessId){
  const seq = ++state.sequence;
  const business = (state.data.businesses||[]).find(b => b.business_id == businessId);
  if(!business){
    $('#main').innerHTML = empty('业务不存在','');
    return;
  }

  // 获取该业务的班次
  const slots = (state.data.slots||[]).filter(s => s.business_id == businessId);

  // 为每个班次查询当前人数
  const slotStats = {};
  try {
    for(const slot of slots){
      const schedules = await request(`/schedules?slot_id=${slot.slot_id}&status=active`);
      slotStats[slot.slot_id] = schedules.length;
    }
  } catch(e) {
    // 忽略错误，继续显示
  }

  if(seq !== state.sequence) return;

  const editable = state.role === 'SUPER' && business.status === 'ACTIVE';

  // 临时过滤出该业务的班次
  const originalSlots = state.data.slots;
  state.data.slots = slots;

  $('#main').innerHTML =
    `<div class="breadcrumb">
      <button class="link" data-action="back-to-business-list">业务管理</button> / ${esc(business.name)}
    </div>` +
    heading(`${business.name} · 服务班次`, '查看该业务的服务时段和队员。',
      editable ? `<button class="btn primary" data-action="business-slot" data-id="${businessId}">添加时段</button>` : '') +
    `<section class="panel">${fixedSlotTable()}</section>`;

  // 恢复原数据
  state.data.slots = originalSlots;

  // 修改表头：将"人数上限"改为"现人数/上限"
  const thead = document.querySelector('.panel table thead');
  if(thead){
    const headers = thead.querySelectorAll('th');
    headers.forEach(th => {
      if(th.textContent.trim() === '人数上限'){
        th.textContent = '现人数/上限';
      }
    });
  }

  // 修改表格内容和按钮
  if(document.querySelector('.panel table tbody')){
    const businessSlots = slots;
    document.querySelectorAll('.panel table tbody tr').forEach((row, index) => {
      const slot = businessSlots[index];
      if(!slot) return;

      // 修改"人数上限"列，显示为"现人数/上限"
      const cells = row.querySelectorAll('td');
      if(cells.length >= 3){
        const capacityCell = cells[2]; // 第3列是人数上限
        const currentCount = slotStats[slot.slot_id] || 0;
        const capacity = slot.need_num || '—';
        capacityCell.textContent = `${currentCount} / ${capacity}${capacity !== '—' ? ' 人' : ''}`;
      }

      // 修改操作列
      const lastCell = row.querySelector('td:last-child');
      if(lastCell){
        // 清空原有按钮
        lastCell.innerHTML = '';

        // 添加"查看队员"按钮
        const viewBtn = document.createElement('button');
        viewBtn.className = 'text-button';
        viewBtn.dataset.action = 'view-slot-members';
        viewBtn.dataset.id = slot.slot_id;
        viewBtn.textContent = '查看队员 →';
        lastCell.appendChild(viewBtn);

        // 超管且业务有效：添加"修改设置"按钮
        if(editable){
          const editBtn = document.createElement('button');
          editBtn.className = 'text-button';
          editBtn.dataset.action = 'edit-slot-config';
          editBtn.dataset.id = slot.slot_id;
          editBtn.textContent = '修改设置';
          lastCell.appendChild(editBtn);
        }
      }
    });
  }
}

// 第2层：小组列表
async function renderBusinessGroups(businessId){
  const seq = ++state.sequence;
  const business = (state.data.businesses||[]).find(b => b.business_id == businessId);
  if(!business){
    $('#main').innerHTML = empty('业务不存在','');
    return;
  }

  const groups = (state.data.groups||[]).filter(g => g.business_id == businessId);

  if(seq !== state.sequence) return;

  $('#main').innerHTML =
    `<div class="breadcrumb">
      <button class="link" data-action="back-to-business-list">业务管理</button> / ${esc(business.name)}
    </div>` +
    heading(`${business.name} · 小组管理`, '查看该业务的小组和成员。') +
    `<section class="panel">${groups.length ? table(
      ['小组名称','成员数','操作'],
      groups.map(g => `<tr>
        <td><strong>${esc(g.name)}</strong></td>
        <td>${g.member_count || 0} 人</td>
        <td>
          <button class="text-button" data-action="view-group-members" data-id="${g.group_id}">查看成员 →</button>
        </td>
      </tr>`)
    ) : empty('暂无小组','该业务尚未配置小组。')}</section>`;
}

// 第3层：班次队员列表
async function renderSlotMembers(slotId){
  const seq = ++state.sequence;
  const slot = (state.data.slots||[]).find(s => s.slot_id == slotId);
  if(!slot){
    $('#main').innerHTML = empty('班次不存在','');
    return;
  }

  const business = (state.data.businesses||[]).find(b => b.business_id == slot.business_id);

  try {
    const schedules = await request(`/schedules?slot_id=${slotId}&status=active`);
    if(seq !== state.sequence) return;

    // 获取队员详细信息
    const studentIds = [...new Set(schedules.map(s => s.student_id))];
    const students = studentIds.map(id => {
      const student = (state.data.students||[]).find(st => st.student_id === id);
      return student || { student_id: id, name: '未知', status: 'UNKNOWN' };
    });

    $('#main').innerHTML =
      `<div class="breadcrumb">
        <button class="link" data-action="back-to-business-list">业务管理</button> /
        <button class="link" data-action="back-to-business-slots" data-id="${business.business_id}">${esc(business.name)}</button> /
        ${esc(slotName(slot.slot_id))}
      </div>` +
      heading(`${business.name} · ${slotName(slot.slot_id)} · 队员名单`, '') +
      `<section class="panel">${students.length ? table(
        ['学号','姓名','状态','操作'],
        students.map(st => `<tr>
          <td>${esc(st.student_id)}</td>
          <td><strong>${esc(st.name)}</strong></td>
          <td>${badge(st.status)}</td>
          <td>
            <button class="text-button" data-action="view-student-profile-quick" data-id="${st.student_id}">查看资料</button>
          </td>
        </tr>`)
      ) : empty('暂无队员','该班次尚未安排队员。')}</section>`;
  } catch(e) {
    if(seq === state.sequence) $('#main').innerHTML = empty('读取失败', e.message);
  }
}

// 第3层：小组成员列表
async function renderGroupMembers(groupId){
  const seq = ++state.sequence;
  const group = (state.data.groups||[]).find(g => g.group_id == groupId);
  if(!group){
    $('#main').innerHTML = empty('小组不存在','');
    return;
  }

  const business = (state.data.businesses||[]).find(b => b.business_id == group.business_id);

  try {
    const members = await request(`/business-groups/${groupId}/members`);
    if(seq !== state.sequence) return;

    $('#main').innerHTML =
      `<div class="breadcrumb">
        <button class="link" data-action="back-to-business-list">业务管理</button> /
        <button class="link" data-action="back-to-business-groups" data-id="${business.business_id}">${esc(business.name)}</button> /
        ${esc(group.name)}
      </div>` +
      heading(`${business.name} · ${group.name} · 成员名单`, '') +
      `<section class="panel">${members.length ? table(
        ['学号','姓名','状态','操作'],
        members.map(m => `<tr>
          <td>${esc(m.student_id)}</td>
          <td><strong>${esc(m.name)}</strong></td>
          <td>${badge(m.status)}</td>
          <td>
            <button class="text-button" data-action="view-student-profile-quick" data-id="${m.student_id}">查看资料</button>
          </td>
        </tr>`)
      ) : empty('暂无成员','该小组尚未添加成员。')}</section>`;
  } catch(e) {
    if(seq === state.sequence) $('#main').innerHTML = empty('读取失败', e.message);
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

// 扩展businessAction函数
let _originalBusinessAction = null;
if(typeof businessAction === 'function'){
  _originalBusinessAction = businessAction;
}

window.businessAction = function businessAction(name, id, kind){
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
    state.slotId = id;
    state.tab = 'slot-members';
    window.businessesPage();
    return true;
  }

  // 第2层 → 第3层：查看小组成员
  if(name === 'view-group-members'){
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

  // 修改班次设置（负责人和人数上限）
  if(name === 'edit-slot-config'){
    const slot = (state.data.slots||[]).find(s => s.slot_id == id);
    if(!slot) return true;

    openDialog(
      '修改班次设置',
      `${slotName(slot.slot_id)} · 设置负责人和人数上限。`,
      field('manager_admin_id', '负责人', {
        options: [
          ['', '待分配'],
          ...(state.data.admins||[])
            .filter(a => a.role === 'NORMAL' && a.status === 'ACTIVE')
            .map(a => [a.admin_id, a.name])
        ],
        value: slot.manager_admin_id || '',
        required: false,
        full: true
      }) +
      field('need_num', '人数上限', {
        type: 'number',
        min: 1,
        max: 50,
        step: 1,
        value: slot.need_num || '',
        required: true,
        full: true
      }),
      v => send(`/service-slots/${id}`, {
        manager_admin_id: v.manager_admin_id ? Number(v.manager_admin_id) : null,
        need_num: Number(v.need_num)
      }, 'PUT').then(() => {
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

  // 其他操作：调用原始函数
  if(_originalBusinessAction) return _originalBusinessAction(name, id, kind);
  return false;
};
