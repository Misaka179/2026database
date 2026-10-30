'use strict';
async function collectionManagementPage(){
 const seq=++state.sequence,sup=state.role==='SUPER';
 $('#main').innerHTML=heading('征集管理范围',sup?'指定普通管理员及其可管理的非固定业务，或审核管理员的范围申请。':'已批准的业务范围内，可发布征集和初审时长；终审由超级管理员完成。',`<button class="btn primary" data-action="${sup?'collection-grant':'collection-scope-request'}">${sup?'设置管理员范围':'申请管理范围'}</button>`)+ '<div id="collection-management-result">正在读取…</div>';
 try{
  const data=await request('/collection-management');if(seq!==state.sequence)return;state.data.collectionManagement=data;
  $('#collection-management-result').innerHTML='<section class="panel"><header class="panel-header"><h2>已生效范围</h2></header>'+table(['管理员','账号','业务','生效时间'],[...data.grants,...(data.group_grants||[])].map(r=>`<tr><td>${esc(r.admin_name)}</td><td>${esc(r.account)}</td><td>${esc(r.business_name)}${r.group_name?" / "+esc(r.group_name):"（整项业务）"}</td><td>${fmtDate(r.assigned_at)}</td></tr>`),'暂无已生效范围','由超管指定，或提交申请并等待审批。')+'</section><section class="panel"><header class="panel-header"><h2>范围申请</h2></header>'+table(['申请人','业务','原因','进度','操作'],data.requests.map(r=>`<tr><td>${esc(r.admin_name)}<small>${esc(r.account)}</small></td><td>${esc(r.business_name)}${r.group_name?" / "+esc(r.group_name):"（整项业务）"}</td><td class="wrap">${esc(r.reason)}</td><td>${badge(r.status)}<small>${esc(r.review_reason)}</small></td><td>${sup&&r.status==='PENDING'?`<button class="text-button" data-action="collection-scope-decide" data-id="${r.request_id}">审批范围</button>`:'—'}</td></tr>`))+'</section>';
 }catch(e){if(seq===state.sequence)$('#collection-management-result').textContent=e.message;}
}
function scopeCheckboxes(businesses,ids=[],groups=[],gids=[]){return '<div class="field full"><label>管理范围（可多选，整项业务包含所有小组）</label><div class="membership-options" id="collection-scope-options">'+businesses.map(b=>`<label><input type="checkbox" name="scope_${b.business_id}" value="${b.business_id}" ${ids.includes(b.business_id)?'checked':''}>${esc(b.name)}（整项业务）</label>`).join('')+groups.map(g=>`<label><input type="checkbox" name="group_${g.group_id}" value="${g.group_id}" ${gids.includes(g.group_id)?'checked':''}>${esc(g.business_name)} / ${esc(g.name)}</label>`).join('')+'</div></div>';}
const scopeValues=v=>({business_ids:Object.entries(v).filter(([k])=>k.startsWith('scope_')).map(([,v])=>Number(v)),group_ids:Object.entries(v).filter(([k])=>k.startsWith('group_')).map(([,v])=>Number(v)),reason:v.reason});
function governanceAction(name,id){
 if(typeof name!=='string')return false;
 const data=state.data.collectionManagement;
 if(name==='collection-grant'){
  if(!data){notify('请等待管理范围加载完成。',true);return true;}
  const admins=(state.data.admins||[]).filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE');if(!admins.length){notify('请先将负责人设为普通管理员。',true);return true;}
  openDialog('设置征集管理员范围','指定后立即生效；整项业务授权与小组授权可分别撤销。',field('admin_id','普通管理员',{options:admins.map(a=>[a.admin_id,`${a.name}（${a.account}）`]),full:true})+scopeCheckboxes(data.businesses,data.grants.filter(g=>g.admin_id===admins[0].admin_id).map(g=>g.business_id),data.groups,(data.group_grants||[]).filter(g=>g.admin_id===admins[0].admin_id).map(g=>g.group_id))+reasonField(),v=>send('/collection-managers/'+v.admin_id,scopeValues(v),'PUT'),'保存范围');scrollableDialog();
  $('#f-admin_id').addEventListener('change',()=>{const aid=Number($('#f-admin_id').value),ids=data.grants.filter(g=>g.admin_id===aid).map(g=>g.business_id),gids=(data.group_grants||[]).filter(g=>g.admin_id===aid).map(g=>g.group_id);dialog.querySelectorAll('input[name^="scope_"]').forEach(el=>el.checked=ids.includes(Number(el.value)));dialog.querySelectorAll('input[name^="group_"]').forEach(el=>el.checked=gids.includes(Number(el.value)));});return true;
 }
 if(name==='collection-scope-request'){
  if(!data){notify('请等待管理范围加载完成。',true);return true;}
  const busy=new Set([...data.grants.map(g=>g.business_id),...data.requests.filter(r=>r.status==='PENDING'&&!r.group_id).map(g=>g.business_id)]);
  const groupBusy=new Set([...(data.group_grants||[]).map(g=>g.group_id),...data.requests.filter(r=>r.status==='PENDING'&&r.group_id).map(g=>g.group_id)]);
  const options=data.businesses.filter(b=>!busy.has(b.business_id)),groups=(data.groups||[]).filter(g=>!busy.has(g.business_id)&&!groupBusy.has(g.group_id));
  if(!options.length&&!groups.length){notify('全部范围已授权或申请待审批。',true);return true;}
  openDialog('申请征集管理范围','小组授权只允许管理指定小组的征集。',scopeCheckboxes(options,[],groups)+reasonField(),v=>{const body=scopeValues(v);if(!body.business_ids.length&&!body.group_ids.length)throw new Error('请选择至少一个业务或小组。');return send('/collection-scope-requests',body);},'提交申请');scrollableDialog();return true;
 }
 if(name==='collection-scope-decide'){
  const r=data?.requests.find(r=>String(r.request_id)===String(id));if(!r)return true;
  openDialog('审批管理范围',`${r.admin_name} · ${r.business_name}${r.group_name?" / "+r.group_name:"（整项业务）"} · ${r.reason}`,field('approved','审批结果',{options:[['true','通过'],['false','打回']]})+field('reason','审批说明（打回必填）',{type:'textarea',full:true,required:false,maxLength:500}),v=>{if(v.approved==='false'&&!v.reason.trim())throw new Error('打回必须填写原因。');return send(`/collection-scope-requests/${id}/decision`,{approved:v.approved==='true',reason:v.reason,expected_revision:r.revision});});return true;
 }
 if(name.startsWith('inbox-')){inboxAction(name,id);return true;}
 return false;
}

function updateInboxBadge(){
 const n=state.data.inbox?.unread_count||0;
 document.querySelectorAll('[data-inbox-count]').forEach(el=>{el.textContent=n>99?'99+':String(n);el.hidden=!n;});
}
function startInboxPolling(){
 const version=state.sessionVersion,token=state.token,generation=(state.inboxPollGeneration||0)+1;state.inboxPollGeneration=generation;
 async function poll(){
  if(!state.me||version!==state.sessionVersion||token!==state.token||generation!==state.inboxPollGeneration)return;
  try{const result=await request('/inbox?limit=1');if(version===state.sessionVersion&&generation===state.inboxPollGeneration){state.data.inbox=result;updateInboxBadge();}}catch{}
  if(version===state.sessionVersion&&generation===state.inboxPollGeneration)setTimeout(poll,30000);
 }
 setTimeout(poll,30000);
}
async function inboxPage(append=false){
 const seq=++state.sequence;
 if(!append){state.inboxSelected=new Set();state.inboxRows=[];state.inboxCursor=null;$('#main').innerHTML=heading('收件箱','查看申请、审批结果、征集发布与结束，以及账号和服务记录变更通知。','<div class="button-row"><button class="btn" data-action="inbox-refresh">刷新</button><button class="btn" data-action="inbox-read-all">全部标为已读</button></div>')+`<div class="toolbar"><button class="btn" data-action="inbox-filter">${state.inboxUnreadOnly?'显示全部通知':'仅看未读'}</button></div><div id="inbox-results">正在读取…</div>`;}
 try{
  const q=new URLSearchParams({limit:'50',unread_only:String(Boolean(state.inboxUnreadOnly))});if(append&&state.inboxCursor)q.set('before_id',state.inboxCursor);
  const data=await request('/inbox?'+q);if(seq!==state.sequence)return;
  state.data.inbox=data;updateInboxBadge();state.inboxRows=(append?state.inboxRows:[]).concat(data.items);state.inboxCursor=data.next_cursor;
  state.inboxSelected=new Set([...state.inboxSelected].filter(id=>state.inboxRows.some(r=>r.notice_id===id&&!r.read_at)));
  $('#inbox-results').innerHTML=inboxBatchBar()+'<section class="panel">'+table(['选择','通知','时间','状态','操作'],state.inboxRows.map(r=>`<tr><td>${!r.read_at?`<input type="checkbox" data-notice-select="${r.notice_id}" aria-label="选择通知 ${esc(r.title)}" ${state.inboxSelected.has(r.notice_id)?'checked':''}>`:'—'}</td><td class="wrap"><strong>${esc(r.title)}</strong><small>${esc(r.message)}</small></td><td>${fmtDate(r.created_at)}</td><td>${r.read_at?'已读':'<span class="badge pending">未读</span>'}</td><td><button class="text-button" data-action="inbox-open" data-id="${r.notice_id}">查看相关记录</button>${!r.read_at?`<button class="text-button" data-action="inbox-read" data-id="${r.notice_id}">标为已读</button>`:''}</td></tr>`),'暂无通知','新的申请、审批和征集通知会显示在这里。')+'</section>'+(data.next_cursor?'<button class="btn" data-action="inbox-more">加载更多</button>':'');
 }catch(e){if(seq===state.sequence)$('#inbox-results').textContent=e.message;}
}
async function inboxAction(name,id){
 if(state.inboxBusy)return;
 if(name==='inbox-select-all'||name==='inbox-select-none'){state.inboxSelected=new Set(name==='inbox-select-all'?state.inboxRows.filter(r=>!r.read_at).map(r=>r.notice_id):[]);updateInboxSelection();return;}
 if(name==='inbox-filter'){state.inboxUnreadOnly=!state.inboxUnreadOnly;await inboxPage();return;}
 if(name==='inbox-refresh'){await inboxPage();return;}
 if(name==='inbox-more'){await inboxPage(true);return;}
 const row=(state.inboxRows||[]).find(r=>String(r.notice_id)===String(id));const session=state.sessionVersion;
 state.inboxBusy=true;
 try{
  if(name==='inbox-read-batch'){if(!state.inboxSelected?.size)return;setInboxBatchBusy(true);await send('/inbox/read-batch',{notice_ids:[...state.inboxSelected]});}
  else if(name==='inbox-read-all')await send('/inbox/read-all',{});
  else if(row)await send(`/inbox/${id}/read`,{});else return;
  if(session!==state.sessionVersion||state.page!=='inbox')return;
  if(name==='inbox-open'){
   const [page,tab]=row.target_page.split(':');if(page==='collections')state.focusCollection=row.target_id;
   if(state.role==='LEAD'&&row.title.includes('工作日报'))state.leadTab='reports';
   navigate(page);if(tab){state.tab=tab;renderPage();}
   const latest=await request('/inbox?limit=1');if(session===state.sessionVersion){state.data.inbox=latest;updateInboxBadge();}
  }else await inboxPage();
 }catch(e){if(session===state.sessionVersion)notify(e.message,true);}
 finally{state.inboxBusy=false;setInboxBatchBusy(false);}
}
