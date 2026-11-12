'use strict';
function fixedSlotTable(){
 const rows=state.data.slots.filter(s=>s.weekday||s.schedule_kind==='WEEKLY').sort((a,b)=>a.weekday-b.weekday||a.period_no-b.period_no);
 return table(['固定时段','服务时间','建议人数','认定时长','班次负责人',...(['SUPER'].includes(state.role)?['设置']:[])],rows.map(r=>`<tr><td><strong>${esc(slotLabel(r))}</strong></td><td>${r.schedule_kind==='WEEKLY'?'每周一次，无固定时间':esc(r.start_time)+' 至 '+esc(r.end_time)}</td><td>${r.need_num===null?'待设置':r.need_num+' 人'}</td><td>${hourText(r.service_minutes)}</td><td>${esc(adminName(r.manager_admin_id))}</td>${['SUPER'].includes(state.role)?`<td>${['GARDEN','PUBLICITY'].includes(r.business_code)?`<button class="text-button" data-page="businesses">设置业务管理员</button><button class="text-button" data-action="configure-slot" data-id="${r.slot_id}">设置建议人数</button>`:`<button class="text-button" data-action="configure-slot" data-id="${r.slot_id}">设置班次负责人和建议人数</button>`}</td>`:''}</tr>`));
}
function rosterBusinessName(id){
 const b=(state.data.businesses||[]).find(x=>String(x.business_id)===String(id));
 return b?b.name:'';
}
function studentStatusText(status){
 return status==='ACTIVE'?'在队':status==='QUIT'?'已退队':status==='DISABLED'?'已停用':'状态未知';
}
function rosterAffiliations(s){
 const parts=[],seen=new Set();
 const add=(business,unit,kind)=>{
  const label=[business,unit].filter(Boolean).join(' · ');
  if(!label||seen.has(label))return;
  seen.add(label);parts.push({business,unit,kind,label});
 };
 (s.slots||[]).forEach(t=>{
  const slot=rowsOf(state.data.slots||[],'slot_id',t.slot_id);
  add(slot?rosterBusinessName(slot.business_id):'',slot?slotLabel(slot):(t.name||''),'固定时段');
 });
 (s.groups||[]).forEach(g=>add(rosterBusinessName(g.business_id),g.name,'小组'));
 (s.business_ids||[]).forEach(id=>{
  const name=rosterBusinessName(id);
  if(name&&!parts.some(p=>p.business===name))add(name,'','业务');
 });
 return parts;
}
function rosterAffiliationSummary(s){
 const parts=rosterAffiliations(s);
 if(!parts.length)return '未归属';
 return parts[0].label+(parts.length>1?` +${parts.length-1}`:'');
}
function rosterStudentTable(rows){
 return table(['队员','归属','操作'],rows.map(s=>{
  const parts=rosterAffiliations(s),status=s.status==='ACTIVE'?'':` ${badge(s.status,studentStatusText(s.status))}`;
  return `<tr><td><strong>${esc(s.name)}</strong>${status}<small>${esc(s.student_id)}</small></td><td class="wrap" title="${esc(parts.map(p=>p.label).join('；'))}">${esc(rosterAffiliationSummary(s))}</td><td><button class="text-button" data-action="student-profile" data-id="${esc(s.student_id)}">查看档案</button></td></tr>`;
 }),'未找到队员','可按姓名或学号查询。',{aligns:['center','center','center'],widths:['26%',null,'88px']});
}
function rosterFilteredStudents(){
 const q=(state.rosterQuery||'').trim().toLocaleLowerCase();
 return (state.data.students||[]).filter(s=>!q||String(s.student_id).toLocaleLowerCase().includes(q)||String(s.name||'').toLocaleLowerCase().includes(q));
}
function rosterFilteredAdmins(){
 const q=(state.adminQuery||'').trim().toLocaleLowerCase();
 return (state.data.admins||[]).filter(a=>{const text=[a.name,a.account,roleName(a.role),a.status].join(' ').toLocaleLowerCase();return !q||text.includes(q);});
}
function renderRosterSearch(){const el=$('#student-results');if(el)el.innerHTML=rosterStudentTable(rosterFilteredStudents());}
function renderAdminSearch(){const el=$('#admin-results');if(el)el.innerHTML=rosterAdminTable(rosterFilteredAdmins());}
function openStudentProfile(id){
 const s=rowsOf(state.data.students,'student_id',id);
 if(!s){notify('队员信息已变化，请刷新页面。',true);return;}
 const parts=rosterAffiliations(s),basic=[];
 if(s.college)basic.push(['学院',s.college]);
 if(s.phone)basic.push(['手机号',s.phone]);
 basic.push(['加入时间',fmtDate(s.join_time)]);
 basic.push(['信用分',`${s.credit_score} 分`]);
 const admin=(state.data.admins||[]).find(a=>String(a.student_id)===String(s.student_id));
 if(admin)basic.push(['管理员账号',`${admin.account} · ${roleName(admin.role)}`]);
 const basicHtml=`<div class="profile-fields">${basic.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}</div>`;
 const meScope=state.me?.scope||{};
 const mySlotIds=new Set((meScope.slot_ids||[]).map(String));
 const myBusinessIds=new Set((meScope.total_business_ids||[]).map(String));
 const canAffiliate=state.role==='SUPER'||(state.role==='NORMAL'&&(
  (s.slots||[]).some(t=>mySlotIds.has(String(t.slot_id)))||
  (s.business_ids||[]).some(id=>myBusinessIds.has(String(id)))||
  (s.groups||[]).some(g=>myBusinessIds.has(String(g.business_id)))));
 const affHtml=parts.length?`<div class="profile-affiliations">${parts.map(p=>`<div class="profile-affiliation"><span>${esc(p.label)}</span><span class="profile-affiliation-side">${esc(p.kind)}</span></div>`).join('')}</div>`:'<p class="muted">没有业务、小组或固定时段归属。</p>';
 const footer=canAffiliate||state.role==='SUPER'?`<div class="profile-footer">${canAffiliate?`<button class="text-button" type="button" data-action="membership" data-id="${esc(s.student_id)}">设置归属</button>`:''}${state.role==='SUPER'?`<button class="text-button" type="button" data-action="reset-student-password" data-id="${esc(s.student_id)}">重置密码</button>`:''}</div>`:'';
 openReadOnlyDialog(`队员档案 · ${s.name}`,`<h3 class="profile-section">基本信息</h3>${basicHtml}<h3 class="profile-section">归属</h3>${affHtml}${footer}`,`${s.student_id} · ${studentStatusText(s.status)}`);
}
function adminScopeItems(a){
 if(a.role==='SUPER')return[{label:'全站管理',kind:'超级管理员'}];
 const weekday='一二三四五六日',items=[];
 (state.data.businesses||[]).forEach(b=>{
  if(String(b.total_manager_admin_id)===String(a.admin_id))items.push({label:b.name,kind:'业务总负责人'});
  (b.leaders||[]).forEach(l=>{if(String(l.admin_id)===String(a.admin_id))items.push({label:`${b.name} · 周${weekday[Number(l.weekday)-1]||l.weekday}`,kind:'分队负责人'});});
 });
 (state.data.slots||[]).forEach(s=>{
  if(String(s.manager_admin_id)===String(a.admin_id))items.push({label:[s.business_name,slotLabel(s)].filter(Boolean).join(' · '),kind:'时段负责人'});
 });
 return [...new Map(items.map(i=>[i.kind+i.label,i])).values()];
}
function openAdminProfile(id){
 const a=rowsOf(state.data.admins,'admin_id',id);if(!a)return;
 const scope=adminScopeItems(a);
 const student=a.student_id?rowsOf(state.data.students,'student_id',a.student_id):null;
 const basic=[['登录账号',a.account],['管理角色',roleName(a.role)],['状态',a.status==='ACTIVE'?'已启用':'已停用']];
 if(student)basic.push(['关联志愿者',`${student.name}（${student.student_id}）`]);
 const basicHtml=`<div class="profile-fields">${basic.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}</div>`;
 const scopeHtml=scope.length?`<div class="profile-affiliations">${scope.map(p=>`<div class="profile-affiliation"><span>${esc(p.label)}</span><span class="profile-affiliation-side">${esc(p.kind)}</span></div>`).join('')}</div>`:'<p class="muted">未分配管理范围。</p>';
 const footer=state.role==='SUPER'?`<div class="profile-footer"><button class="text-button" type="button" data-action="reset-admin-password" data-id="${esc(a.admin_id)}">重置密码</button></div>`:'';
 openReadOnlyDialog(`管理员档案 · ${a.name}`,`<h3 class="profile-section">基本信息</h3>${basicHtml}<h3 class="profile-section">管理范围</h3>${scopeHtml}${footer}`,`${roleName(a.role)} · ${a.status==='ACTIVE'?'已启用':'已停用'}`);
}
function adminScopeSummary(a){
 const items=adminScopeItems(a);if(!items.length)return '未分配';
 return `${items[0].kind} · ${items[0].label}${items.length>1?` +${items.length-1}`:''}`;
}
function rosterAdminTable(rows=state.data.admins||[]){
 return table(['管理员','管理范围','操作'],rows.map(a=>`<tr><td><strong>${esc(a.name)}</strong>${a.status==='ACTIVE'?'':` ${badge(a.status,'已停用')}`}<small>${esc(a.account)}</small></td><td class="wrap" title="${esc(adminScopeItems(a).map(i=>`${i.kind}：${i.label}`).join('；'))}">${esc(adminScopeSummary(a))}</td><td><button class="text-button" data-action="admin-profile" data-id="${a.admin_id}">查看档案</button></td></tr>`),'暂无管理员','超级管理员可以新增管理员并分配负责时段。',{aligns:['center','center','center'],widths:['26%',null,'88px']});
}
function rosterBasicsPage(){
 const kind=state.tab||'students';
 const buttons=kind==='students'?'':(state.role==='SUPER'?'<button class="btn primary" data-action="create-admins">新增管理员</button>':'');
 const body=kind==='students'?searchBar('student-search-form',state.rosterQuery,'查询队员','query','输入姓名或学号，留空显示全部')+'<section class="panel" id="student-results">'+rosterStudentTable(rosterFilteredStudents())+'</section>':searchBar('admin-search-form',state.adminQuery,'查询管理员','query','输入姓名或登录账号，留空显示全部')+'<section class="panel" id="admin-results">'+rosterAdminTable(rosterFilteredAdmins())+'</section>';
 $('#main').innerHTML=heading('队员资料','维护志愿者和管理员信息。',buttons)+`<div class="panel-tabs">${tabs([['students','志愿者'],['admins','管理员']],kind)}</div>`+body;
}
function membersPage(){
 $('#main').innerHTML=heading('本时段队员','仅展示你负责时段的队员。')+searchBar('student-search-form',state.rosterQuery,'查询队员','query','输入姓名或学号，留空显示全部')+'<section class="panel" id="student-results">'+rosterStudentTable(rosterFilteredStudents())+'</section>';
}
function openAffiliationDialog(person){
 const selectedSlots=new Set((person.slots||[]).map(s=>Number(s.slot_id)));
 const selectedBusinesses=new Set((person.business_member_ids||[]).map(Number));
 const selectedGroups=new Set((person.groups||[]).map(g=>Number(g.group_id)));
 const catalog=state.data.affiliationCatalog||{};
 const slots=((catalog.slots&&catalog.slots.length?catalog.slots:state.data.slots)||[]).filter(s=>(s.weekday||s.schedule_kind==='WEEKLY')&&(s.business_status!=='ARCHIVED'||selectedSlots.has(Number(s.slot_id))));
 const events=((catalog.businesses&&catalog.businesses.length?catalog.businesses:state.data.businesses)||[]).filter(b=>b.kind==='EVENT'&&b.status==='ACTIVE');
 const groups=((catalog.groups&&catalog.groups.length?catalog.groups:state.data.groups)||[]).filter(g=>events.some(b=>String(b.business_id)===String(g.business_id)));
 const optionRow=(prefix,item,label,checked)=>`<label><input type="checkbox" name="${prefix}_${item}" value="${item}" ${checked?'checked':''}> ${esc(label)}</label>`;
 const block=(title,hint,content,extra='')=>`<div class="field full affiliation-block ${extra}"><label>${esc(title)}</label>${hint?`<small>${esc(hint)}</small>`:''}<div class="membership-options">${content||'<p class="muted">当前没有可选项。</p>'}</div></div>`;
 const slotGroups=new Map();
 slots.forEach(s=>{const key=String(s.business_id);if(!slotGroups.has(key))slotGroups.set(key,[]);slotGroups.get(key).push(s);});
 const slotOptions=[...slotGroups.values()].map(items=>{
  const name=items[0].business_name||rosterBusinessName(items[0].business_id);
  const picked=items.filter(s=>selectedSlots.has(Number(s.slot_id))).length;
  return `<details class="affiliation-slot-group"><summary>${esc(name)}（${items.length}）${picked?` · 已选 ${picked}`:''}</summary><div class="membership-options">${items.map(s=>optionRow('member_slot',s.slot_id,slotLabel(s),selectedSlots.has(Number(s.slot_id)))).join('')}</div></details>`;
 }).join('');
 const businessOptions=events.map(b=>optionRow('member_business',b.business_id,b.name,selectedBusinesses.has(Number(b.business_id)))).join('');
 const groupOptions=groups.map(g=>`<label data-business="${g.business_id}"><input type="checkbox" name="member_group_${g.group_id}" value="${g.group_id}" ${selectedGroups.has(Number(g.group_id))?'checked':''}> ${esc((g.business_name||rosterBusinessName(g.business_id))+' · '+g.name)}</label>`).join('');
 const noneLabel='无归属（清空全部固定时段、专项业务和小组）';
 const fields=`<div class="field full affiliation-none"><label><input type="checkbox" id="affiliation-none"> ${noneLabel}</label></div>`+
  block('固定时段','按业务时段归属，可多选；可跨业务调整。',slotOptions,'affiliation-slots')+
  block('专项业务','仅非固定业务；可同时选择多个。',businessOptions)+
  block('小组','小组必须挂在已选中的专项业务下。',groupOptions)+
  field('effective_date','生效日期',{type:'date',value:getDate(),min:getDate(),full:true})+reasonField();
 openDialog('设置归属',`${person.student_id} ${person.name}；固定时段、专项业务和小组可同时调整。`,fields,v=>{
  const none=dialog.querySelector('#affiliation-none').checked;
  const checked=prefix=>none?[]:[...dialog.querySelectorAll(`input[name^="${prefix}"]:checked`)].map(el=>Number(el.value));
  return send(`/students/${encodeURIComponent(person.student_id)}/affiliations`,{
   slot_ids:checked('member_slot_'),business_ids:checked('member_business_'),
   group_ids:checked('member_group_'),effective_date:v.effective_date,reason:v.reason
  },'PUT');
 },'保存归属');
 const noneBox=dialog.querySelector('#affiliation-none'),affInputs=[...dialog.querySelectorAll('#action-form input[name^="member_"]')];
 const syncGroups=()=>{
  const picked=new Set([...dialog.querySelectorAll('input[name^="member_business_"]')].filter(el=>el.checked).map(el=>Number(el.value)));
  dialog.querySelectorAll('#action-form [data-business]').forEach(label=>{
   const on=picked.has(Number(label.dataset.business)),input=label.querySelector('input');
   label.hidden=!on;input.disabled=!on||noneBox.checked;if(!on)input.checked=false;
  });
 };
 const syncNone=()=>{
  affInputs.forEach(input=>{input.disabled=noneBox.checked;if(noneBox.checked)input.checked=false;});
  syncGroups();
 };
 dialog.querySelectorAll('input[name^="member_business_"]').forEach(el=>el.addEventListener('change',()=>{if(el.checked)noneBox.checked=false;syncGroups();}));
 affInputs.filter(el=>!el.name.startsWith('member_business_')).forEach(el=>el.addEventListener('change',()=>{if(el.checked)noneBox.checked=false;syncGroups();}));
 noneBox.addEventListener('change',syncNone);
 syncNone();
}
function rosterAction(name,id){
 if(name==='student-profile'){openStudentProfile(id);return true;}
 if(name==='admin-profile'){openAdminProfile(id);return true;}
 if(name==='increase-fixed-hours'){
  const row=rowsOf(state.data.schedules,'schedule_id',id);
  if(!row)return true;
  openDialog('上调本次服务时长',`${studentName(row.student_id)} · ${row.schedule_date} · ${slotName(row.slot_id)}。当前 ${row.current_minutes} 分钟。上调后通知班次负责人；未结算的记录仍在周结算时入账。考勤改判会恢复班次标准时长。`,
   field('service_minutes','上调后的时长（分钟）',{type:'number',min:Number(row.current_minutes)+1,max:1440,step:1,full:true})+reasonField(),
   v=>send(`/schedules/${id}/increase-hours`,{service_minutes:Number(v.service_minutes),expected_minutes:Number(row.current_minutes),reason:v.reason}),'确认上调');return true;
 }
 if(name==='reset-student-password'||name==='reset-admin-password'){
  if(!['SUPER','NORMAL'].includes(state.role)){notify('仅超级管理员或本范围负责人可以重置密码。',true);return true;}
  const isStudent=name==='reset-student-password';
  const person=rowsOf(isStudent?state.data.students:state.data.admins,isStudent?'student_id':'admin_id',id);
  if(!person){notify('账号信息已变化，请刷新页面。',true);return true;}
  const account=isStudent?person.student_id:person.account;
  openDialog('重置密码',`${person.name}（${account}）。管理员账号与志愿者账号密码相互独立，请将新密码告知账号本人。`,
   field('new_password','新密码',{type:'password',full:true,maxLength:128,help:'设置 8 至 128 个字符。'})+
   field('confirm_password','再次输入新密码',{type:'password',full:true,maxLength:128})+reasonField(),v=>{
    if(v.new_password.length<8||v.new_password.length>128)throw new Error('新密码需要 8 至 128 个字符。');
    if(v.new_password!==v.confirm_password)throw new Error('两次输入的密码不一致。');
    return send(`/${isStudent?'students':'admins'}/${encodeURIComponent(id)}/reset-password`,{new_password:v.new_password,reason:v.reason});
   },'确认重置');return true;
 }
 if(name==='promote-student'){
  notify('管理员账号由超级管理员新增，不再提供把志愿者转为管理员的入口。',true);return true;
 }
 if(name==='fixed-transfer'){openFixedTransfer(id);return true;}
 if(name==='configure-slot'){
  const s=rowsOf(state.data.slots,'slot_id',id);
  openDialog(slotLabel(s),'班次负责人只能管理本时段队员及本时段排班。',field('manager_admin_id','班次负责人',{options:['GARDEN','PUBLICITY'].includes(s.business_code)?[[s.manager_admin_id||'',adminName(s.manager_admin_id)]]:[['','待分配'],...state.data.admins.filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE').map(a=>[a.admin_id,a.name])],value:s.manager_admin_id||'',required:false,full:true})+field('need_num','建议人数',{type:'number',value:s.need_num??'',min:1,max:10000,step:1,full:true,required:false,help:'仅作为建议人数，不影响名单导入；可留空。'}),v=>send('/slots/'+id,{manager_admin_id:v.manager_admin_id?Number(v.manager_admin_id):null,need_num:v.need_num?Number(v.need_num):null},'PATCH'),'保存设置');return true;
 }
 if(name==='membership'){
  const person=rowsOf(state.data.students,'student_id',id);
  if(!person)return notify('队员资料已变化，请刷新页面。',true);
  openAffiliationDialog(person);return true;
 }
 if(name==='import-roster'){openRosterImport(id?Number(id):null);return true;}
 return false;
}

function myFixedSlotsPanel(){
 if(state.role!=='STUDENT')return '';
 const rows=state.data.memberships||[];
 const pending=new Set((state.data.transfer||[]).filter(a=>a.old_slot_id&&a.final_status==='PENDING').map(a=>a.old_slot_id));
 return '<section class="panel"><header class="panel-header"><div><h2>我的固定班次</h2></div></header>'+table(['固定班次','服务时间','班次负责人','操作'],rows.map(s=>`<tr><td><strong>${esc(slotLabel(s))}</strong></td><td>${s.schedule_kind==='WEEKLY'?'每周一次，无固定时间':esc(s.start_time)+' 至 '+esc(s.end_time)}</td><td>${esc(s.manager_name||'待分配')}</td><td>${state.me.status==='ACTIVE'?(pending.has(s.slot_id)?'<span class="muted">换班审批中</span>':`<button class="text-button" data-action="fixed-transfer" data-id="${s.slot_id}">申请换班</button>`):'<span class="muted">暂停服务</span>'}</td></tr>`),'尚未分配固定班次','请联系管理员核对学号与归属时段。')+'</section>';
}

function applicationContent(a,kind,old){
 if(kind==='withdrawal')return '退出志愿服务队';
 if(kind==='transfer')return a.old_slot_id?`每周固定班次：${esc(a.old_slot_name||slotName(a.old_slot_id))}<small>长期换至 ${esc(a.new_slot_name||slotName(a.new_slot_id))}</small>`:'换班申请';
 return `${esc(old?.schedule_date||'')} ${esc(slotName(old?.slot_id||''))}`;
}
function openRosterImport(businessId){
 openImportDialog('BUSINESS', Number(businessId));
}

/* 队员与管理员检索在 app.js 的 submit 分发中按姓名或学号本地过滤，避免两套查询口径。 */

async function openFixedTransfer(id){
 const pending=new Set((state.data.transfer||[]).filter(a=>a.old_slot_id&&a.final_status==='PENDING').map(a=>a.old_slot_id));
 const originals=(state.data.memberships||[]).filter(s=>(!id||String(s.slot_id)===String(id))&&!pending.has(s.slot_id));
 if(!originals.length){notify(pending.size?'该固定班次已有待处理申请，请查看申请进度。':'尚未分配可调整的固定班次，请联系管理员。',true);return;}
 openDialog('申请更换固定班次','审核通过后，长期更换每周固定时段。审核前仍按原固定班次服务。',
  field('old_slot_id','原固定班次',{options:originals.map(s=>[s.slot_id,slotLabel(s)]),full:true})+
  field('new_slot_id','目标固定班次',{options:[['','正在加载…']],full:true})+reasonField(),v=>send('/applications/fixed-transfer',{old_slot_id:Number(v.old_slot_id),new_slot_id:Number(v.new_slot_id),reason:v.reason}));
 const version=modalVersion,session=state.sessionVersion;let seq=0;
 const current=()=>version===modalVersion&&session===state.sessionVersion&&dialog.open;
 const load=async()=>{const n=++seq;const select=$('#f-new_slot_id');select.disabled=true;select.innerHTML='<option value="">正在加载…</option>';
  try{const rows=await request('/my-transfer-options?old_slot_id='+encodeURIComponent($('#f-old_slot_id').value));if(!current()||n!==seq)return;
   select.innerHTML=rows.length?rows.map(s=>`<option value="${s.slot_id}">${esc(slotLabel(s))}（${s.schedule_kind==='WEEKLY'?'每周岗位':esc(s.start_time)+' 至 '+esc(s.end_time)}）</option>`).join(''):'<option value="">暂无其他可选班次</option>';select.disabled=!rows.length;
  }catch(e){if(current()&&n===seq){select.innerHTML='<option value="">读取失败，请重新选择原班次</option>';notify(e.message,true);}}
 };
 $('#f-old_slot_id').addEventListener('change',load);await load();
}
