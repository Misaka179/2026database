'use strict';
// 按业务逻辑分组：排班服务、时长与信用、队员与业务（操作日志独立）
const navGroups=[
  ['schedule','排班服务',['semesters','schedules','applications']],
  ['hours','时长与信用',['collections','hours','credit']],
  ['org','队员与业务',['basics','businesses','members']]
];
function navigationHtml(available){
 let saved={};try{saved=JSON.parse(localStorage.getItem('nav-folds-'+state.role)||'{}');}catch{}
 const groupTitle=(id,title)=>({STUDENT:{schedule:'我的服务',hours:'我的时长与信用',org:'我的组织'},NORMAL:{schedule:'排班与审批',hours:'时长与征集',org:'业务与队员'}}[state.role]?.[id])||title;
 const link=([id,title])=>{const navIcon=id==='overview'?'home':id==='inbox'?'inbox':'';return `<button class="nav-link ${state.page===id?'active':''}" data-page="${id}" ${state.page===id?'aria-current="page"':''}>${navIcon?uiIcon(navIcon):''}${navLabel([id,title])}${id==='inbox'?'<span class="badge pending" data-inbox-count hidden></span>':''}</button>`;};
 const pinnedLinks = ['overview','inbox'].map(id=>available.find(n=>n[0]===id)).filter(Boolean).map(link).join('');
 const groupsHtml = navGroups.map(([id,title,items])=>{
  const children=items.map(k=>available.find(n=>n[0]===k)).filter(Boolean);if(!children.length)return '';
  const open=items.includes(state.page)||saved[id]===true;
  return `<div class="nav-group"><button class="nav-group-toggle" data-action="nav-toggle" data-id="${id}" aria-expanded="${open}" aria-controls="nav-${id}">${groupTitle(id,title)}<span class="nav-caret" aria-hidden="true">${uiIcon('chevron-down')}</span></button><div id="nav-${id}" class="nav-children" ${open?'':'hidden'}>${children.map(link).join('')}</div></div>`;
 }).join('');
 // 操作日志独立在最底部
 const logsPage = available.find(n=>n[0]==='logs');
 const logsLink = logsPage ? `<div class="nav-separator"></div><button class="nav-link nav-link-plain ${state.page===logsPage[0]?'active':''}" data-page="${logsPage[0]}">${navLabel(logsPage)}</button>` : '';
 return pinnedLinks + groupsHtml + logsLink;
}
function updateNavigation(){const el=document.querySelector('.nav-list');if(el){el.innerHTML=navigationHtml(navAvailable());updateInboxBadge();}}
function toggleNavGroup(id){let saved={};try{saved=JSON.parse(localStorage.getItem('nav-folds-'+state.role)||'{}');}catch{}const el=document.querySelector(`[data-action="nav-toggle"][data-id="${id}"]`);const open=el.getAttribute('aria-expanded')!=='true';saved[id]=open;localStorage.setItem('nav-folds-'+state.role,JSON.stringify(saved));el.setAttribute('aria-expanded',String(open));document.getElementById('nav-'+id).hidden=!open;}
const activeBusinesses=()=> (state.data.businesses||[]).filter(b=>b.status!=='ARCHIVED');
function groupFilter(value=state.groupId){return '';}
function slotFields(prefix=''){
 const admins=(state.data.admins||[]).filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE');
 return field(prefix+'weekday','星期',{options:[1,2,3,4,5,6,7].map(d=>[d,'周'+'一二三四五六日'[d-1]])})+field(prefix+'period_no','时段编号',{type:'number',min:1,max:100,step:1})+field(prefix+'start_time','开始时间',{type:'time'})+field(prefix+'end_time','结束时间',{type:'time'})+field(prefix+'service_minutes','认定分钟',{type:'number',min:1,max:1440,step:1})+field(prefix+'need_num','建议人数',{type:'number',min:1,max:10000,step:1})+field(prefix+'manager_admin_id','时段管理员',{options:admins.map(a=>[a.admin_id,`${a.name}（${a.account}）`]),full:true});
}
function slotValues(v,prefix=''){const x={};for(const k of ['weekday','period_no','service_minutes','need_num','manager_admin_id'])x[k]=Number(v[prefix+k]);for(const k of ['start_time','end_time'])x[k]=v[prefix+k]||'';return x;}
function scrollableDialog(){dialog.classList.add('collection-dialog');dialog.addEventListener('close',()=>dialog.classList.remove('collection-dialog'),{once:true});}
function openBusinessCreate(){
 openDialog('新增业务','固定排班业务沿用学期日历和默认出勤结算，启用前不补计时长。',field('name','业务名称',{full:true,maxLength:100})+field('kind','业务类型',{options:[['EVENT','非固定业务（时长征集 / 临时服务）'],['FIXED','固定排班业务']],full:true})+'<div class="field full" id="new-business-slots" hidden><div id="new-slot-rows"></div><button class="btn" type="button" id="add-slot-row">添加时段</button></div>',v=>{
  const slots=v.kind==='FIXED'?[...document.querySelectorAll('[data-new-slot]')].map(r=>slotValues(v,r.dataset.newSlot)):[];
  return send('/businesses',{name:v.name,kind:v.kind,slots});
 },'创建业务');
 scrollableDialog();
 let serial=0;function add(){const prefix='slot'+(++serial)+'_';const el=document.createElement('div');el.className='new-slot-row form-grid';el.dataset.newSlot=prefix;el.innerHTML=slotFields(prefix)+'<button type="button" class="text-button full" data-remove-slot>移除此时段</button>';$('#new-slot-rows').append(el);}
 $('#add-slot-row').onclick=add;$('#new-slot-rows').onclick=e=>{if(e.target.hasAttribute('data-remove-slot')&&$('#new-slot-rows').children.length>1)e.target.closest('[data-new-slot]').remove();};
 $('#f-kind').onchange=()=>{const fixed=$('#f-kind').value==='FIXED';$('#new-business-slots').hidden=!fixed;if(fixed&&!$('#new-slot-rows').children.length)add();$('#new-business-slots').querySelectorAll('input,select').forEach(e=>e.disabled=!fixed);};
}
async function openArchive(id,restore=false){
 try{const b=rowsOf(state.data.businesses,'business_id',id),impact=await request(`/businesses/${id}/archive-impact`);
  const blockers=impact.blockers||[];const info=restore?'恢复后只安排允许恢复的未来服务，不补计停用期间。':`将取消 ${impact.future_count} 条尚未开始的排班，不产生处罚；历史时长保留。`;
  openDialog((restore?'恢复业务：':'停用归档：')+b.name,info,(!restore&&blockers.length?'<div class="notice error full">请先处理以下事项：'+blockers.map(r=>`<p>${esc(r.kind)} #${r.id} ${esc(r.label||'')}</p>`).join('')+'</div>':'')+reasonField(),v=>{if(!restore&&blockers.length)throw new Error('请先处理列出的待办后重新打开预览。');return send(`/businesses/${id}/${restore?'restore':'archive'}`,{reason:v.reason,expected_revision:impact.revision});},restore?'确认恢复':'确认停用归档');
  if(!restore&&blockers.length)$('#action-dialog [type="submit"]').disabled=true;
 }catch(e){notify(e.message,true);}
}
async function showGroupMembers(id){const seq=state.sequence,session=state.sessionVersion;try{const rows=await request(`/business-groups/${id}/members`);if(seq!==state.sequence||session!==state.sessionVersion||state.page!=='groups')return;const g=rowsOf(state.data.groups,'group_id',id);if(!g)return;openReadOnlyDialog(g.name,table(['姓名','学号','生效日期','结束日期'],rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.student_id)}</td><td>${esc(r.effective_from)}</td><td>${esc(r.effective_until||'持续有效')}</td></tr>`),'暂无小组成员','该小组当前没有成员。'));}catch(e){if(seq===state.sequence&&session===state.sessionVersion)notify(e.message,true);}}
function directoryAction(name,id,kind){
 if(name==='nav-toggle'){toggleNavGroup(id);return true;}
 if(name==='business-create'){openBusinessCreate();return true;}
 if(name==='business-archive'||name==='business-restore'){openArchive(id,name==='business-restore');return true;}
 if(name==='business-rename'){const b=rowsOf(state.data.businesses,'business_id',id);openDialog('修改业务名称','业务编号、历史记录和授权保持不变。',field('name','业务名称',{value:b.name,maxLength:100,full:true})+reasonField(),v=>send('/businesses/'+id,v,'PATCH'));return true;}
 if(name==='business-slot'){openDialog('添加固定时段','同一业务、同一天内的时段不能重叠。',slotFields(),v=>send(`/businesses/${id}/slots`,slotValues(v)));scrollableDialog();return true;}
 if(name==='group-show'){showGroupMembers(id);return true;}
 if(name==='group-member'){openDialog('调整小组成员','允许兼任其他小组，不追改历史归属。',field('student_id','学号',{maxLength:32})+field('active','操作',{options:[['true','加入'],['false','退出小组']]})+field('effective_date','生效日期',{type:'date',min:getDate(),value:getDate()})+reasonField(),v=>send(`/business-groups/${id}/members/${encodeURIComponent(v.student_id)}`,{active:v.active==='true',effective_date:v.effective_date,reason:v.reason},'PUT'));return true;}
 if(name==='member-import'){openImportDialog('GROUP',Number(id));return true;}
 if(name==='excel-import'){openImportDialog(String(kind||'BUSINESS').toUpperCase(),id?Number(id):null);return true;}
 if(name==='import-records'){openImportRecords(Number(id));return true;}
 if(name==='revert-import'){revertImport(id);return true;}
 return false;
}
function openMemberImport(preset){
 openImportDialog(preset&&preset.group_id?'GROUP':'BUSINESS',preset&&preset.group_id?Number(preset.group_id):null);
}

document.addEventListener('change',e=>{if(e.target.id==='business-filter'){state.groupId='';}});
