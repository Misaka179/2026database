'use strict';
function fixedSlotTable(){
 const rows=state.data.slots.filter(s=>s.weekday||s.schedule_kind==='WEEKLY').sort((a,b)=>a.weekday-b.weekday||a.period_no-b.period_no);
 return table(['固定时段','服务时间','人数上限','认定时长','负责人',...(['SUPER','LEAD'].includes(state.role)?['设置']:[])],rows.map(r=>`<tr><td><strong>${esc(r.team_name)}</strong></td><td>${r.schedule_kind==='WEEKLY'?'每周一次，无固定时间':esc(r.start_time)+' 至 '+esc(r.end_time)}</td><td>${r.need_num===null?'待设置':r.need_num+' 人'}</td><td>${hourText(r.service_minutes)}</td><td>${esc(adminName(r.manager_admin_id))}</td>${['SUPER','LEAD'].includes(state.role)?`<td>${['GARDEN','PUBLICITY'].includes(r.business_code)?`<button class="text-button" data-page="businesses">设置业务管理员</button><button class="text-button" data-action="configure-slot" data-id="${r.slot_id}">设置容量</button>`:`<button class="text-button" data-action="configure-slot" data-id="${r.slot_id}">设置负责人和容量</button>`}</td>`:''}</tr>`));
}
function rosterStudentTable(rows){
 const editable=state.role==='SUPER';
 return table(['学号','姓名','学院（选填）','归属时段','状态',...(editable?['管理身份','操作']:[])],rows.map(s=>{
  const admin=(state.data.admins||[]).find(a=>a.student_id===s.student_id);
  const grant=s.status==='ACTIVE'&&(!admin||(admin.role==='NORMAL'&&admin.status==='DISABLED'));
  return `<tr><td><strong>${esc(s.student_id)}</strong></td><td>${esc(s.name)}</td><td>${esc(s.college||'未填写')}</td><td class="wrap">${(s.slots||[]).map(t=>esc(t.name)).join('、')||'尚未分配'}</td><td>${badge(s.status)}</td>${editable?`<td>${admin?esc(roleName(admin.role))+(admin.status==='DISABLED'?'（已停用）':s.status!=='ACTIVE'?'（权限暂停）':''):'志愿者'}</td><td><button class="text-button" data-action="membership" data-id="${esc(s.student_id)}">设置归属时段</button><button class="text-button" data-action="reset-student-password" data-id="${esc(s.student_id)}">重置密码</button>${grant?`<button class="text-button" data-action="promote-student" data-id="${esc(s.student_id)}">${admin?'重新启用管理员':'设为普通管理员'}</button>`:''}</td>`:''}</tr>`;
 }),'未找到队员','可按完整学号查询；新增队员可手动录入或从 Excel 导入。');
}
function rosterBasicsPage(){
 const kind=state.tab||'students';
 if(kind==='admins'){basicsPage();return;}
 const buttons=kind==='students'?'<div class="button-row"><button class="btn" data-action="import-roster">Excel 导入</button><button class="btn primary" data-action="create-students">新增队员</button></div>':'';
 $('#main').innerHTML=heading('基础资料','按业务管理固定时段与每周岗位；以学号识别队员，同一队员可以属于多个时段。',buttons)+`<div class="toolbar">${tabs([['students','志愿者'],['admins','管理员'],['slots','服务班次']],kind)}</div>`+(kind==='students'?'<form id="student-search-form" class="query-form"><div class="field"><label for="student-id-search">按学号精确查询</label><input id="student-id-search" name="student_id" placeholder="输入完整学号，留空显示全部" maxlength="32"></div><button class="btn primary">查询队员</button></form><section class="panel" id="student-results">'+rosterStudentTable(state.data.students)+'</section>':'<p class="rule-note">服务日期按学期日历执行，可设置节假日停工和调休班表。此处设置负责人和人数上限；新增业务及固定时段请进入业务管理。</p><section class="panel">'+fixedSlotTable()+'</section>');
}
function membersPage(){
 $('#main').innerHTML=heading('本时段队员','仅展示你负责时段的队员，以学号精确查询。')+'<form id="student-search-form" class="query-form"><div class="field"><label for="student-id-search">学号</label><input id="student-id-search" name="student_id" maxlength="32" placeholder="完整学号，留空显示全部"></div><button class="btn primary">查询队员</button></form><section class="panel" id="student-results">'+rosterStudentTable(state.data.students||[])+'</section>';
}
function rosterAction(name,id){
 if(name==='increase-fixed-hours'){
  const row=rowsOf(state.data.schedules,'schedule_id',id);
  if(!row)return true;
  openDialog('上调本次服务时长',`${studentName(row.student_id)} · ${row.schedule_date} · ${slotName(row.slot_id)}。当前 ${row.current_minutes} 分钟。上调后通知负责人；未结算的记录仍在周结算时入账。考勤改判会恢复班次标准时长。`,
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
  const choices='<div class="field full"><p>负责时段（可不选；勾选会替换该时段现有负责人）</p><div class="membership-options">'+state.data.slots.filter(s=>s.weekday&&s.business_code!=='PUBLICITY'&&s.status==='ACTIVE').map(s=>`<label><input type="checkbox" name="manage_${s.slot_id}" value="${s.slot_id}"> ${esc(s.team_name)} · ${esc(adminName(s.manager_admin_id))}</label>`).join('')+'</div></div>';
  openDialog('将队员设为普通管理员',`${person.name}（${person.student_id}）。保留志愿者身份、归属和历史；登录时选择“管理员”，使用学号和现有志愿者密码。只管理分配的时段，其他时段负责人保持不变。`,choices+reasonField(),v=>send('/students/'+encodeURIComponent(id)+'/administrator',{slot_ids:Object.entries(v).filter(([k])=>k.startsWith('manage_')).map(([,v])=>Number(v)),reason:v.reason}),'设为普通管理员');return true;
 }
 if(name==='fixed-transfer'){openFixedTransfer(id);return true;}
 if(name==='configure-slot'){
  const s=rowsOf(state.data.slots,'slot_id',id);
  openDialog(s.team_name,'负责人只能管理本时段队员及本时段排班。',field('manager_admin_id','负责人',{options:['GARDEN','PUBLICITY'].includes(s.business_code)?[[s.manager_admin_id||'',adminName(s.manager_admin_id)]]:[['','待分配'],...state.data.admins.filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE').map(a=>[a.admin_id,a.name])],value:s.manager_admin_id||'',required:false,full:true})+field('need_num','人数上限',{type:'number',value:s.need_num??'',min:1,max:10000,step:1,full:true,required:false,help:'可留空待设置；手动新增排班和换入前须填写。'}),v=>send('/slots/'+id,{manager_admin_id:v.manager_admin_id?Number(v.manager_admin_id):null,need_num:v.need_num?Number(v.need_num):null},'PATCH'),'保存设置');return true;
 }
 if(name==='membership'){
  const person=rowsOf(state.data.students,'student_id',id);
  const selected=(person.slots||[]).map(s=>s.slot_id);
  const fields='<div class="field full"><p>勾选该队员的固定归属时段，可多选。已设置学期时，将同步更新尚未开始的日期排班。</p><div class="membership-options">'+state.data.slots.filter(s=>(s.weekday||s.schedule_kind==='WEEKLY')&&(s.business_status!=='ARCHIVED'||selected.includes(s.slot_id))).map(s=>`<label><input type="checkbox" name="member_${s.slot_id}" value="${s.slot_id}" ${selected.includes(s.slot_id)?'checked':''}> ${esc(s.team_name)}</label>`).join('')+'</div></div>';
  openDialog('设置队员归属',`${person.student_id} ${person.name}`,fields+field('effective_date','生效日期',{type:'date',value:getDate(),min:getDate(),full:true})+reasonField(),v=>send('/students/'+encodeURIComponent(id)+'/slots',{slot_ids:Object.entries(v).filter(([k])=>k.startsWith('member_')).map(([,v])=>Number(v)),effective_date:v.effective_date,reason:v.reason},'PUT'),'保存归属');return true;
 }
 if(name==='import-roster'){openRosterImport();return true;}
 return false;
}

function myFixedSlotsPanel(){
 if(state.role!=='STUDENT')return '';
 const rows=state.data.memberships||[];
 const pending=new Set((state.data.transfer||[]).filter(a=>a.old_slot_id&&a.first_status!=='REJECTED'&&a.final_status==='PENDING').map(a=>a.old_slot_id));
 return '<section class="panel"><header class="panel-header"><div><h2>我的固定班次</h2><p>每周重复的服务时段；换班审批通过后长期生效。</p></div></header>'+table(['固定班次','服务时间','负责人','操作'],rows.map(s=>`<tr><td><strong>${esc(s.team_name)}</strong><small>${esc(s.location)}</small></td><td>${s.schedule_kind==='WEEKLY'?'每周一次，无固定时间':esc(s.start_time)+' 至 '+esc(s.end_time)}</td><td>${esc(s.manager_name||'待分配')}</td><td>${state.me.status==='ACTIVE'&&s.status==='ACTIVE'?(pending.has(s.slot_id)?'<span class="muted">换班审批中</span>':`<button class="text-button" data-action="fixed-transfer" data-id="${s.slot_id}">申请换班</button>`):'<span class="muted">暂停服务</span>'}</td></tr>`),'尚未分配固定班次','请联系管理员核对学号与归属时段。')+'</section>';
}

function applicationContent(a,kind,old){
 if(kind==='withdrawal')return '退出志愿服务队';
 if(kind==='transfer'&&a.old_slot_id)return `每周固定班次：${esc(a.old_slot_name||slotName(a.old_slot_id))}<small>长期换至 ${esc(a.new_slot_name||slotName(a.new_slot_id))}</small>`;
 return `${esc(old?.schedule_date||'')} ${esc(slotName(old?.slot_id||''))}${kind==='transfer'?`<small>换至 ${esc(a.new_date)} ${esc(a.new_slot_name||slotName(a.new_slot_id))}</small>`:''}`;
}
function openRosterImport(){
 previousFocus=document.activeElement;modalSubmit=null;modalVersion++;
 const version=modalVersion,session=state.sessionVersion;
 let fileBase64='',lastPreview=null;
 dialog.innerHTML='<header class="dialog-header"><div><h2 id="dialog-title">从 Excel 导入队员</h2><p>先预览，再确认。只导入身份资料和归属时段，不导入历史时长。</p></div><button data-action="close" class="close-button">关闭</button></header><div class="dialog-body"><div class="form-stack"><div class="field"><label for="roster-file">选择 .xlsx 文件（最大 8 MB）</label><input id="roster-file" type="file" accept=".xlsx"></div><div class="field"><label for="roster-sheet">工作表</label><select id="roster-sheet"><option value="">默认第一张工作表</option></select></div><label><input id="roster-map" type="checkbox"> 按一分队＝周一、二分队＝周二，直到七分队＝周日，导入时段归属</label><button type="button" class="btn" id="roster-preview">读取并预览</button><div id="roster-result" aria-live="polite"></div><div class="field"><label for="roster-password">新队员初始密码</label><input id="roster-password" type="password" minlength="8" maxlength="128" autocomplete="new-password"><small>仅用于新账号，已有账号的密码、资料和信用记录保持原样。</small></div><label><input id="roster-accept" type="checkbox"> 我已核对预览提示与所选工作表</label><button type="button" class="btn primary" id="roster-commit" disabled>确认导入</button><div class="notice error" id="roster-error" hidden role="alert"></div></div></div>';
 const businessPicker=document.createElement('div');businessPicker.className='field';businessPicker.innerHTML='<label for="roster-business">导入业务</label><select id="roster-business">'+(state.data.businesses||[]).filter(b=>b.kind==='FIXED').map(b=>`<option value="${b.business_id}">${esc(b.name)}</option>`).join('')+'</select>';$('#roster-file').parentElement.before(businessPicker);
 dialog.showModal();
 const current=()=>version===modalVersion&&session===state.sessionVersion&&dialog.open;
 const reset=()=>{lastPreview=null;$('#roster-commit').disabled=true;$('#roster-result').textContent='选择已改变，请重新预览。';};
 ['roster-file','roster-sheet','roster-map','roster-business'].forEach(id=>$('#'+id).addEventListener('change',reset));
 async function run(commit){
  if(modalBusy)return;
  const error=$('#roster-error');error.hidden=true;
  const controls=[...dialog.querySelectorAll('input,select,button')];
  try{
   const file=$('#roster-file').files[0];if(!file||!file.name.toLowerCase().endsWith('.xlsx')||file.size>8*1024*1024)throw new Error('请选择不超过 8 MB 的 .xlsx 文件。');
   if(commit&&(!lastPreview||lastPreview.errors.length||!$('#roster-accept').checked))throw new Error('请先完成无错误的预览，并勾选核对确认。');
   const password=$('#roster-password').value;
   if(commit&&(password.length<8||password.length>128))throw new Error('新队员初始密码需要 8 至 128 个字符。');
   const sheet=$('#roster-sheet').value,map=$('#roster-map').checked,business=Number($('#roster-business').value)||null;
   setModalBusy(true);controls.forEach(c=>c.disabled=true);$('#roster-result').textContent=commit?'正在创建账号与时段归属，请保持页面打开…':'正在读取工作簿…';
   fileBase64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
   if(!current())return;
   const result=await send('/students/import',{business_id:business,file_base64:fileBase64,sheet_name:sheet||null,map_categories:map,commit,initial_password:commit?password:null,accept_warnings:commit});
   if(!current())return;
   if(commit){setModalBusy(false);closeDialog();notify(`导入完成：新增 ${result.new_students} 名队员，新增 ${result.added_memberships} 条时段归属。`);await refresh();return;}
   lastPreview=result;
   $('#roster-sheet').innerHTML=result.sheets.map(s=>`<option value="${esc(s)}" ${s===result.sheet?'selected':''}>${esc(s)}</option>`).join('');
   const issues=[...result.errors.map(e=>`错误：${e.message}`),...result.warnings.map(w=>`第 ${w.row} 行：${w.message}`)];
   $('#roster-result').innerHTML=`<p><strong>${result.source_rows} 行资料，合并为 ${result.unique_students} 名队员</strong></p><p>新增 ${result.new_students} 名，已有 ${result.existing_students} 名，识别 ${result.memberships} 条时段归属。</p>${issues.length?'<div class="import-issues"><ul>'+issues.map(x=>`<li>${esc(x)}</li>`).join('')+'</ul></div>':'<p>未发现数据冲突。</p>'}<details><summary>查看队员预览（前 50 名）</summary>${table(['学号','姓名','学院','识别时段'],result.students.slice(0,50).map(s=>`<tr><td>${esc(s.student_id)}</td><td>${esc(s.name)}</td><td>${esc(s.college||'未填写')}</td><td>${s.slots.map(([d,p])=>`周${'一二三四五六日'[d-1]}-${(p<=5?'一二三四五'[p-1]:p)}时段`).join('、')||'未分配'}</td></tr>`))}</details>`;
  }catch(e){if(current()){error.textContent=e.message;error.hidden=false;}}
  finally{if(current()){setModalBusy(false);controls.forEach(c=>c.disabled=false);$('#roster-commit').disabled=!lastPreview||lastPreview.errors.length>0;}}
 }
 $('#roster-preview').addEventListener('click',()=>run(false));$('#roster-commit').addEventListener('click',()=>run(true));
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
