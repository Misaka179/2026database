'use strict';
function fixedSlotTable(){
 const rows=state.data.slots.filter(s=>s.weekday||s.schedule_kind==='WEEKLY').sort((a,b)=>a.weekday-b.weekday||a.period_no-b.period_no);
 return table(['固定时段','服务时间','人数上限','认定时长','班次负责人',...(['SUPER','LEAD'].includes(state.role)?['设置']:[])],rows.map(r=>`<tr><td><strong>${esc(r.team_name)}</strong></td><td>${r.schedule_kind==='WEEKLY'?'每周一次，无固定时间':esc(r.start_time)+' 至 '+esc(r.end_time)}</td><td>${r.need_num===null?'待设置':r.need_num+' 人'}</td><td>${hourText(r.service_minutes)}</td><td>${esc(adminName(r.manager_admin_id))}</td>${['SUPER','LEAD'].includes(state.role)?`<td>${['GARDEN','PUBLICITY'].includes(r.business_code)?`<button class="text-button" data-page="businesses">设置业务管理员</button><button class="text-button" data-action="configure-slot" data-id="${r.slot_id}">设置容量</button>`:`<button class="text-button" data-action="configure-slot" data-id="${r.slot_id}">设置班次负责人和容量</button>`}</td>`:''}</tr>`));
}
function rosterStudentTable(rows){
 const editable=state.role==='SUPER';
 return table(['学号','姓名','学院（选填）','归属时段','状态',...(editable?['管理身份','操作']:[])],rows.map(s=>{
  const admin=(state.data.admins||[]).find(a=>a.student_id===s.student_id);
  const grant=s.status==='ACTIVE'&&(!admin||(admin.role==='NORMAL'&&admin.status==='DISABLED'));
  return `<tr><td><strong>${esc(s.student_id)}</strong></td><td>${esc(s.name)}</td><td>${esc(s.college||'未填写')}</td><td class="wrap">${(s.slots||[]).map(t=>esc(t.name)).join('、')||'尚未分配'}</td><td>${badge(s.status)}</td>${editable?`<td>${admin?esc(roleName(admin.role))+(admin.status==='DISABLED'?'（已停用）':s.status!=='ACTIVE'?'（权限暂停）':''):'志愿者'}</td><td><button class="text-button" data-action="membership" data-id="${esc(s.student_id)}">设置归属时段</button><button class="text-button" data-action="reset-student-password" data-id="${esc(s.student_id)}">重置密码</button>${grant?`<button class="text-button" data-action="promote-student" data-id="${esc(s.student_id)}">${admin?'重新启用管理员':'设为普通管理员'}</button>`:''}</td>`:''}</tr>`;
 }),'未找到队员','可按完整学号查询。');
}
function rosterAdminTable(){
 const editable=state.role==='SUPER';
 return table(['姓名','登录账号','关联队员','管理角色','负责时段','状态',...(editable?['操作']:[])],(state.data.admins||[]).map(a=>`<tr><td><strong>${esc(a.name)}</strong></td><td>${esc(a.account)}</td><td>${esc(a.student_id||'独立管理员')}</td><td>${roleName(a.role)}</td><td class="wrap">${a.role==='SUPER'?'全队管理':state.data.slots.filter(s=>s.weekday&&s.manager_admin_id===a.admin_id).map(s=>esc(s.team_name)).join('、')||'尚未分配'}</td><td>${badge(a.status,a.status==='ACTIVE'?'已启用':'已停用')}</td>${editable?`<td><button class="text-button" data-action="reset-admin-password" data-id="${a.admin_id}">重置密码</button></td>`:''}</tr>`),'暂无管理员','超级管理员可以新增管理员并分配负责时段。');
}
function rosterBasicsPage(){
 const kind=state.tab||'students';
 const buttons=kind==='students'?'':(state.role==='SUPER'?'<button class="btn primary" data-action="create-admins">新增管理员</button>':'');
 $('#main').innerHTML=heading('队员资料','维护志愿者和管理员信息。',buttons)+`<div class="panel-tabs">${tabs([['students','志愿者'],['admins','管理员']],kind)}</div>`+(kind==='students'?'<form id="student-search-form" class="query-form"><div class="field"><label for="student-id-search">学号</label><input id="student-id-search" name="student_id" placeholder="输入完整学号，留空显示全部" maxlength="32"></div><button class="btn primary" type="submit">查询队员</button></form><section class="panel" id="student-results">'+rosterStudentTable(state.data.students||[])+'</section>':'<section class="panel" id="admin-results">'+rosterAdminTable()+'</section>');
}
function membersPage(){
 $('#main').innerHTML=heading('本时段队员','仅展示你负责时段的队员，以学号精确查询。')+'<form id="student-search-form" class="query-form"><div class="field"><label for="student-id-search">学号</label><input id="student-id-search" name="student_id" maxlength="32" placeholder="完整学号，留空显示全部"></div><button class="btn primary">查询队员</button></form><section class="panel" id="student-results">'+rosterStudentTable(state.data.students||[])+'</section>';
}
function rosterAction(name,id){
 if(name==='increase-fixed-hours'){
  const row=rowsOf(state.data.schedules,'schedule_id',id);
  if(!row)return true;
  openDialog('上调本次服务时长',`${studentName(row.student_id)} · ${row.schedule_date} · ${slotName(row.slot_id)}。当前 ${row.current_minutes} 分钟。上调后通知班次负责人；未结算的记录仍在周结算时入账。考勤改判会恢复班次标准时长。`,
   field('service_minutes','上调后的时长（分钟）',{type:'number',min:Number(row.current_minutes)+1,max:1440,step:1,full:true})+reasonField(),
   v=>send(`/schedules/${id}/increase-hours`,{service_minutes:Number(v.service_minutes),expected_minutes:Number(row.current_minutes),reason:v.reason}),'确认上调');return true;
 }
 if(name==='reset-student-password'||name==='reset-admin-password'){
  if(!['SUPER','LEAD'].includes(state.role)){notify('仅超级管理员或范围负责人可以重置密码。',true);return true;}
  const isStudent=name==='reset-student-password';
  const person=rowsOf(isStudent?state.data.students:state.data.admins,isStudent?'student_id':'admin_id',id);
  if(!person){notify('账号信息已变化，请刷新页面。',true);return true;}
  const account=isStudent?person.student_id:person.account;
  const linked=isStudent?(state.data.admins||[]).some(a=>a.student_id===person.student_id):!!person.student_id;
  openDialog('重置密码',`${person.name}（${account}）。${linked?'该队员的志愿者和关联管理员身份会同步使用新密码。':''}请将新密码告知账号本人。`,
   field('new_password','新密码',{type:'password',full:true,maxLength:128,help:'设置 8 至 128 个字符。'})+
   field('confirm_password','再次输入新密码',{type:'password',full:true,maxLength:128})+reasonField(),v=>{
    if(v.new_password.length<8||v.new_password.length>128)throw new Error('新密码需要 8 至 128 个字符。');
    if(v.new_password!==v.confirm_password)throw new Error('两次输入的密码不一致。');
    return send(`/${isStudent?'students':'admins'}/${encodeURIComponent(id)}/reset-password`,{new_password:v.new_password,reason:v.reason});
   },'确认重置');return true;
 }
 if(name==='promote-student'){
  const person=rowsOf(state.data.students,'student_id',id);
  const choices='<div class="field full"><p>负责时段（可不选；勾选会替换该时段现有的班次负责人）</p><div class="membership-options">'+state.data.slots.filter(s=>s.weekday&&s.business_code!=='PUBLICITY'&&s.status==='ACTIVE').map(s=>`<label><input type="checkbox" name="manage_${s.slot_id}" value="${s.slot_id}"> ${esc(s.team_name)} · ${esc(adminName(s.manager_admin_id))}</label>`).join('')+'</div></div>';
  openDialog('将队员设为普通管理员',`${person.name}（${person.student_id}）。保留志愿者身份、归属和历史；登录时选择“管理员”，使用学号和现有志愿者密码。只管理分配的时段，其他班次的负责人保持不变。`,choices+reasonField(),v=>send('/students/'+encodeURIComponent(id)+'/administrator',{slot_ids:Object.entries(v).filter(([k])=>k.startsWith('manage_')).map(([,v])=>Number(v)),reason:v.reason}),'设为普通管理员');return true;
 }
 if(name==='fixed-transfer'){openFixedTransfer(id);return true;}
 if(name==='configure-slot'){
  const s=rowsOf(state.data.slots,'slot_id',id);
  openDialog(s.team_name,'班次负责人只能管理本时段队员及本时段排班。',field('manager_admin_id','班次负责人',{options:['GARDEN','PUBLICITY'].includes(s.business_code)?[[s.manager_admin_id||'',adminName(s.manager_admin_id)]]:[['','待分配'],...state.data.admins.filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE').map(a=>[a.admin_id,a.name])],value:s.manager_admin_id||'',required:false,full:true})+field('need_num','人数上限',{type:'number',value:s.need_num??'',min:1,max:10000,step:1,full:true,required:false,help:'可留空待设置；手动新增排班和换入前须填写。'}),v=>send('/slots/'+id,{manager_admin_id:v.manager_admin_id?Number(v.manager_admin_id):null,need_num:v.need_num?Number(v.need_num):null},'PATCH'),'保存设置');return true;
 }
 if(name==='membership'){
  const person=rowsOf(state.data.students,'student_id',id);
  const selected=(person.slots||[]).map(s=>s.slot_id);
  const fields='<div class="field full"><p>勾选该队员的固定归属时段，可多选。已设置学期时，将同步更新尚未开始的日期排班。</p><div class="membership-options">'+state.data.slots.filter(s=>(s.weekday||s.schedule_kind==='WEEKLY')&&(s.business_status!=='ARCHIVED'||selected.includes(s.slot_id))).map(s=>`<label><input type="checkbox" name="member_${s.slot_id}" value="${s.slot_id}" ${selected.includes(s.slot_id)?'checked':''}> ${esc(s.team_name)}</label>`).join('')+'</div></div>';
  openDialog('设置队员归属',`${person.student_id} ${person.name}`,fields+field('effective_date','生效日期',{type:'date',value:getDate(),min:getDate(),full:true})+reasonField(),v=>send('/students/'+encodeURIComponent(id)+'/slots',{slot_ids:Object.entries(v).filter(([k])=>k.startsWith('member_')).map(([,v])=>Number(v)),effective_date:v.effective_date,reason:v.reason},'PUT'),'保存归属');return true;
 }
 if(name==='import-roster'){openRosterImport(id?Number(id):null);return true;}
 return false;
}

function myFixedSlotsPanel(){
 if(state.role!=='STUDENT')return '';
 const rows=state.data.memberships||[];
 const pending=new Set((state.data.transfer||[]).filter(a=>a.old_slot_id&&a.first_status!=='REJECTED'&&a.final_status==='PENDING').map(a=>a.old_slot_id));
 return '<section class="panel"><header class="panel-header"><div><h2>我的固定班次</h2></div></header>'+table(['固定班次','服务时间','班次负责人','操作'],rows.map(s=>`<tr><td><strong>${esc(s.team_name)}</strong><small>${esc(s.location)}</small></td><td>${s.schedule_kind==='WEEKLY'?'每周一次，无固定时间':esc(s.start_time)+' 至 '+esc(s.end_time)}</td><td>${esc(s.manager_name||'待分配')}</td><td>${state.me.status==='ACTIVE'&&s.status==='ACTIVE'?(pending.has(s.slot_id)?'<span class="muted">换班审批中</span>':`<button class="text-button" data-action="fixed-transfer" data-id="${s.slot_id}">申请换班</button>`):'<span class="muted">暂停服务</span>'}</td></tr>`),'尚未分配固定班次','请联系管理员核对学号与归属时段。')+'</section>';
}

function applicationContent(a,kind,old){
 if(kind==='withdrawal')return '退出志愿服务队';
 if(kind==='transfer'&&a.old_slot_id)return `每周固定班次：${esc(a.old_slot_name||slotName(a.old_slot_id))}<small>长期换至 ${esc(a.new_slot_name||slotName(a.new_slot_id))}</small>`;
 return `${esc(old?.schedule_date||'')} ${esc(slotName(old?.slot_id||''))}${kind==='transfer'?`<small>换至 ${esc(a.new_date)} ${esc(a.new_slot_name||slotName(a.new_slot_id))}</small>`:''}`;
}
function openRosterImport(businessId){
 openImportDialog('BUSINESS', Number(businessId));
}

document.addEventListener('submit',async e=>{
 if(e.target.id!=='student-search-form')return;
 e.preventDefault();const session=state.sessionVersion,sequence=state.sequence;
 const sid=$('#student-id-search').value.trim();
 try{const rows=await request('/students'+(sid?'?student_id='+encodeURIComponent(sid):''));if(session===state.sessionVersion&&sequence===state.sequence&&$('#student-results'))$('#student-results').innerHTML=rosterStudentTable(rows);}catch(e){if(session===state.sessionVersion)notify(e.message,true);}
});

async function openFixedTransfer(id){
 const pending=new Set((state.data.transfer||[]).filter(a=>a.old_slot_id&&a.first_status!=='REJECTED'&&a.final_status==='PENDING').map(a=>a.old_slot_id));
 const originals=(state.data.memberships||[]).filter(s=>s.status==='ACTIVE'&&(!id||String(s.slot_id)===String(id))&&!pending.has(s.slot_id));
 if(!originals.length){notify(pending.size?'该固定班次已有待处理申请，请查看申请进度。':'尚未分配可调整的固定班次，请联系管理员。',true);return;}
 openDialog('申请更换固定班次','初审和终审通过后，长期更换每周固定时段。审批前仍按原固定班次服务。',
  field('old_slot_id','原固定班次',{options:originals.map(s=>[s.slot_id,s.team_name]),full:true})+
  field('new_slot_id','目标固定班次',{options:[['','正在加载…']],full:true})+reasonField(),v=>send('/applications/fixed-transfer',{old_slot_id:Number(v.old_slot_id),new_slot_id:Number(v.new_slot_id),reason:v.reason}));
 const version=modalVersion,session=state.sessionVersion;let seq=0;
 const current=()=>version===modalVersion&&session===state.sessionVersion&&dialog.open;
 const load=async()=>{const n=++seq;const select=$('#f-new_slot_id');select.disabled=true;select.innerHTML='<option value="">正在加载…</option>';
  try{const rows=await request('/my-transfer-options?old_slot_id='+encodeURIComponent($('#f-old_slot_id').value));if(!current()||n!==seq)return;
   select.innerHTML=rows.length?rows.map(s=>`<option value="${s.slot_id}">${esc(s.team_name)}（${s.schedule_kind==='WEEKLY'?'每周岗位':esc(s.start_time)+' 至 '+esc(s.end_time)}）</option>`).join(''):'<option value="">暂无其他可选班次</option>';select.disabled=!rows.length;
  }catch(e){if(current()&&n===seq){select.innerHTML='<option value="">读取失败，请重新选择原班次</option>';notify(e.message,true);}}
 };
 $('#f-old_slot_id').addEventListener('change',load);await load();
}
