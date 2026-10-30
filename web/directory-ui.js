'use strict';
const navGroups=[['people','业务与人员',['leaders','lead-workspace','businesses','groups','basics','members','slots']],['work','排班与考勤',['schedules','semesters']],['hours','时长与信用',['collections','hours','specialty','credit']],['approvals','申请与审批',['applications','collection-management']],['system','系统管理',['logs']]];
function navigationHtml(available){
 let saved={};try{saved=JSON.parse(localStorage.getItem('nav-folds-'+state.role)||'{}');}catch{}
 const link=([id,title])=>`<button class="nav-link ${state.page===id?'active':''}" data-page="${id}" ${state.page===id?'aria-current="page"':''}>${title}${id==='inbox'?'<span class="badge pending" data-inbox-count hidden></span>':''}</button>`;
 return ['overview','inbox'].map(id=>available.find(n=>n[0]===id)).filter(Boolean).map(link).join('')+navGroups.map(([id,title,items])=>{
  const children=items.map(k=>available.find(n=>n[0]===k)).filter(Boolean);if(!children.length)return '';
  const open=items.includes(state.page)||saved[id]===true;
  return `<div class="nav-group"><button class="nav-group-toggle" data-action="nav-toggle" data-id="${id}" aria-expanded="${open}" aria-controls="nav-${id}">${title}<span aria-hidden="true">${open?'⌄':'›'}</span></button><div id="nav-${id}" class="nav-children" ${open?'':'hidden'}>${children.map(link).join('')}</div></div>`;
 }).join('');
}
function updateNavigation(){const el=document.querySelector('.nav-list');if(el){el.innerHTML=navigationHtml(nav.filter(n=>n[2].includes(state.role)));updateInboxBadge();}}
function toggleNavGroup(id){let saved={};try{saved=JSON.parse(localStorage.getItem('nav-folds-'+state.role)||'{}');}catch{}const el=document.querySelector(`[data-action="nav-toggle"][data-id="${id}"]`);const open=el.getAttribute('aria-expanded')!=='true';saved[id]=open;localStorage.setItem('nav-folds-'+state.role,JSON.stringify(saved));el.setAttribute('aria-expanded',String(open));el.querySelector('span').textContent=open?'⌄':'›';document.getElementById('nav-'+id).hidden=!open;}
const activeBusinesses=()=> (state.data.businesses||[]).filter(b=>b.status!=='ARCHIVED');
function groupFilter(value=state.groupId){return `<div class="field"><label for="group-filter">小组</label><select id="group-filter" name="group_id"><option value="">全部小组</option><option value="0" ${String(value)==='0'?'selected':''}>未分组</option>${(state.data.groups||[]).filter(g=>!state.businessId||String(g.business_id)===String(state.businessId)).map(g=>`<option value="${g.group_id}" ${String(value)===String(g.group_id)?'selected':''}>${esc(g.name)}</option>`).join('')}</select></div>`;}
function slotFields(prefix=''){
 const admins=(state.data.admins||[]).filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE');
 return field(prefix+'weekday','星期',{options:[1,2,3,4,5,6,7].map(d=>[d,'周'+'一二三四五六日'[d-1]])})+field(prefix+'period_no','时段编号',{type:'number',min:1,max:100,step:1})+field(prefix+'start_time','开始时间',{type:'time'})+field(prefix+'end_time','结束时间',{type:'time'})+field(prefix+'service_minutes','认定分钟',{type:'number',min:1,max:1440,step:1})+field(prefix+'need_num','容量',{type:'number',min:1,max:10000,step:1})+field(prefix+'manager_admin_id','时段管理员',{options:admins.map(a=>[a.admin_id,`${a.name}（${a.account}）`]),full:true})+field(prefix+'location','服务地点',{required:false,full:true,maxLength:200});
}
function slotValues(v,prefix=''){const x={};for(const k of ['weekday','period_no','service_minutes','need_num','manager_admin_id'])x[k]=Number(v[prefix+k]);for(const k of ['start_time','end_time','location'])x[k]=v[prefix+k]||'';return x;}
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
async function groupsPage(){
 const seq=++state.sequence;$('#main').innerHTML=heading('小组与成员','支持兼任；加入小组同时建立所属业务归属，离开小组不会删除历史。',state.role==='SUPER'?'<button class="btn primary" data-action="member-import">导入业务／小组名单</button>':'')+'<section class="panel" id="groups-result">正在读取…</section><section id="group-members-result"></section>';
 try{const groups=await request('/business-groups');if(seq!==state.sequence)return;state.data.groups=groups;
  $('#groups-result').innerHTML=table(['业务 / 小组','在队人数','操作'],groups.filter(g=>g.can_manage).map(g=>`<tr><td>${esc(g.business_name)}<small>${esc(g.name)}${g.business_status==='ARCHIVED'?'（已归档）':''}</small></td><td>${g.member_count}</td><td><button class="text-button" data-action="group-show" data-id="${g.group_id}">查看名单</button>${state.role==='SUPER'&&g.business_status==='ACTIVE'?`<button class="text-button" data-action="group-member" data-id="${g.group_id}">调整成员</button>`:''}</td></tr>`),'暂无可管理小组','请先申请或配置管理范围。');
  if(state.role==='SUPER'){const bids=new Set(groups.map(g=>g.business_id));const ungrouped=(state.data.students||[]).filter(p=>p.status==='ACTIVE'&&(p.business_ids||[]).some(b=>bids.has(b)&&!(p.groups||[]).some(g=>g.business_id===b)));$('#groups-result').insertAdjacentHTML('beforeend','<header class="panel-header"><h2>干部及干事 · 未分组成员</h2></header>'+table(['姓名','学号'],ungrouped.map(p=>`<tr><td>${esc(p.name)}</td><td>${esc(p.student_id)}</td></tr>`),'暂无未分组成员','历史成员不会被自动分配小组。'));}
 }catch(e){if(seq===state.sequence)$('#groups-result').textContent=e.message;}
}
async function showGroupMembers(id){const seq=state.sequence;try{const rows=await request(`/business-groups/${id}/members`);if(seq!==state.sequence)return;const g=rowsOf(state.data.groups,'group_id',id);$('#group-members-result').innerHTML='<section class="panel"><header class="panel-header"><h2>'+esc(g.name)+'</h2></header>'+table(['姓名','学号','生效日期','结束日期'],rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.student_id)}</td><td>${esc(r.effective_from)}</td><td>${esc(r.effective_until||'持续有效')}</td></tr>`))+'</section>';}catch(e){notify(e.message,true);}}
function directoryAction(name,id){
 if(name==='nav-toggle'){toggleNavGroup(id);return true;}
 if(name==='business-create'){openBusinessCreate();return true;}
 if(name==='business-archive'||name==='business-restore'){openArchive(id,name==='business-restore');return true;}
 if(name==='business-rename'){const b=rowsOf(state.data.businesses,'business_id',id);openDialog('修改业务名称','业务编号、历史记录和授权保持不变。',field('name','业务名称',{value:b.name,maxLength:100,full:true})+reasonField(),v=>send('/businesses/'+id,v,'PATCH'));return true;}
 if(name==='business-slot'){openDialog('添加固定时段','同一业务、同一天内的时段不能重叠。',slotFields(),v=>send(`/businesses/${id}/slots`,slotValues(v)));scrollableDialog();return true;}
 if(name==='group-show'){showGroupMembers(id);return true;}
 if(name==='group-member'){openDialog('调整小组成员','允许兼任其他小组，不追改历史归属。',field('student_id','学号',{maxLength:32})+field('active','操作',{options:[['true','加入'],['false','退出小组']]})+field('effective_date','生效日期',{type:'date',min:getDate(),value:getDate()})+reasonField(),v=>send(`/business-groups/${id}/members/${encodeURIComponent(v.student_id)}`,{active:v.active==='true',effective_date:v.effective_date,reason:v.reason},'PUT'));return true;}
 if(name==='member-import'){openMemberImport();return true;}
 return false;
}
function openMemberImport(){
 let encoded='',preview=null,mappings={},decisions={};
 openDialog('导入业务／小组名单','识别各工作表中的姓名、学号、学院。只建立归属，不计服务时长。',
 '<div class="field full"><label for="member-file">名单 Excel</label><input id="member-file" type="file" accept=".xlsx"></div>'+field('initial_password','新账号初始密码',{type:'password',required:false,full:true,minLength:8,maxLength:128})+'<div class="field full"><button type="button" class="btn" id="member-preview">读取 / 重新核对</button><div id="member-import-results"></div></div>',async v=>{
  if(preview?.replayed)return preview;
  if(!preview||preview.errors.length)throw new Error('请先读取名单，处理异常后重新核对。');
  return send('/member-imports',{file_base64:encoded,mappings,decisions,initial_password:v.initial_password||null,commit:true});
 },'确认导入');
 dialog.classList.add('collection-dialog');dialog.addEventListener('close',()=>dialog.classList.remove('collection-dialog'),{once:true});
 $('#member-file').onchange=()=>{encoded='';preview=null;mappings={};decisions={};$('#member-import-results').innerHTML='';};
 const targetOptions=()=>[['','跳过此表'],...activeBusinesses().filter(b=>b.kind==='EVENT').flatMap(b=>[[String(b.business_id),b.name+'（未分组）'],...(state.data.groups||[]).filter(g=>g.business_id===b.business_id).map(g=>[`${b.business_id}:${g.group_id}`,b.name+' / '+g.name])])];
 $('#member-preview').onclick=async()=>{
  const btn=$('#member-preview');btn.disabled=true;
  try{const file=$('#member-file').files[0];if(!file||file.size>8*1024*1024)throw new Error('请选择不超过8MB的 .xlsx 文件。');if(!encoded)encoded=await fileBase64(file);
   preview=await send('/member-imports',{file_base64:encoded,mappings,decisions});
   $('#member-import-results').innerHTML=preview.replayed?'<p class="notice">本批次已导入，不会重复添加。</p>':`<p>可导入 ${preview.eligible} 条，新账号 ${preview.new_students} 个，跳过 ${preview.skipped} 条，待核对 ${preview.errors.length} 条。</p>`+preview.sheets.map(s=>`<label class="import-sheet">${esc(s.name)}（${s.count}行）<select data-sheet-map="${esc(s.name)}">${targetOptions().map(([v,n])=>`<option value="${v}" ${v===(s.target?String(s.target.business_id)+(s.target.group_id?':'+s.target.group_id:''):'')?'selected':''}>${esc(n)}</option>`).join('')}</select></label>`).join('')+table(['来源','姓名 / 原学号','核对','处理'],preview.rows.map(r=>`<tr><td>${esc(r.sheet)} 第${r.row}行</td><td>${esc(r.name)}<small>${esc(r.student_id||'缺学号')}</small></td><td class="wrap">${esc(r.error|| (r.skipped?'已跳过':'有效'))}${r.candidates?.length?'<small>同名账号：'+r.candidates.map(p=>esc(p.student_id)).join('、')+'</small>':''}</td><td><label><input type="checkbox" data-row-skip="${esc(r.key)}" ${decisions[r.key]?.skip?'checked':''}>跳过</label><input aria-label="${esc(r.key)}核对后学号" data-row-id="${esc(r.key)}" value="${esc(decisions[r.key]?.student_id||'')}" placeholder="核对后填写学号"><label><input type="checkbox" data-row-confirm="${esc(r.key)}" ${decisions[r.key]?.confirmed?'checked':''}>已核实身份</label></td></tr>`));
  }catch(e){notify(e.message,true);}finally{btn.disabled=false;}
 };
 $('#member-import-results').onchange=e=>{const x=e.target;
  if(x.dataset.sheetMap!==undefined){const [b,g]=x.value.split(':');mappings[x.dataset.sheetMap]=b?{business_id:Number(b),group_id:g?Number(g):null}:null;}
  for(const [key,field] of [['rowSkip','skip'],['rowId','student_id'],['rowConfirm','confirmed']])if(x.dataset[key]!==undefined){const k=x.dataset[key];decisions[k]??={};decisions[k][field]=field==='student_id'?x.value.trim():x.checked;}
  preview=null;
 };
}

document.addEventListener('change',e=>{if(e.target.id==='group-filter'){state.groupId=e.target.value;hoursPage();}if(e.target.id==='business-filter'){state.groupId='';}});
