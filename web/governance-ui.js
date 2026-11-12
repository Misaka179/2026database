'use strict';
function governanceAction(name,id){
 if(typeof name!=='string')return false;
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
const inboxCategoryLabels={APPLICATION:'申请',SERVICE:'服务记录',ACCOUNT:'账号',COLLECTION:'时长征集',SCOPE:'管理范围'};
const inboxStatusLabels={NORMAL:'正常',LATE:'迟到',ABSENT:'缺勤',LEAVE:'请假',PENDING:'待登记',ANOMALY:'异常'};
const inboxTargetLabels={collections:'时长征集',schedules:'排班记录',hours:'服务时长',credit:'信用记录',applications:'申请记录','collection-management':'征集管理','lead-workspace':'负责人工作台',overview:'工作概览'};
function inboxCategoryLabel(category){return inboxCategoryLabels[category]||'通知';}
function inboxStatusText(code){return inboxStatusLabels[code]||'已更新';}
function inboxTitle(row){const title=String(row.title||'').trim();if(/^\d+$/.test(title))return inboxCategoryLabel(row.category)+'通知';return (title||'通知').replace(/^考勤记录已更新$/,'考勤已登记').replace(/^(请假|长期换班|退队)申请(待审批|已提交)$/,'$1$2').replace(/审核结果抄送$/,'审核结果');}
const inboxNoisePatterns=[/如需核对[，,]?请查看本条排班记录[。.]?/g,/日报保留生成时快照[，,]?请查看最新记录[。.]?/g,/请使用负责人账号登录[。.]?/g,/申请已进入审批流程[，,]?可在申请记录查看进度[。.]?/g,/可在申请记录查看进度[。.]?/g,/请进入申请记录查看(?:审批|审核)结果[。.]?/g,/请查看相关记录[。.]?/g,/请查看本条排班记录[。.]?/g,/请查看工作事项和申报截止日期[。.]?/g,/已提交的申报继续审批[。.]?/g,/^请查看[。.]?$/g];
function inboxCleanText(value){
 let text=String(value||'');
 for(const pattern of inboxNoisePatterns)text=text.replace(pattern,'');
 return text.replace(/。。+/g,'。').replace(/^[：:，,。；;\s]+/,'').replace(/[：:，,。；;\s]+$/,'').trim();
}
function inboxStudent(sid){const name=studentName(sid);return name&&String(name)!==String(sid)?`${name}（${sid}）`:`学号 ${sid}`;}
function inboxAttendance(date,sid,who,status,rest){
 const identity=who||inboxStudent(sid);
 const reason=inboxCleanText(rest).replace(/^(?:说明|原因)[：:]\s*/,'').replace(/^\d{1,8}[。.、；;]\s*/,'');
 const note=reason&&!/^\d{1,8}$/.test(reason)?reason:'';
 return {summary:`${date} · ${identity} · ${status}`,note,facts:[['队员',identity],['日期',date],['结果',status],...(note?[['说明',note]]:[])]};
}
function inboxReadable(row){
 const raw=String(row.message||'').replace(/。。+/g,'。').trim();
 const legacy=raw.match(/^学号\s*([^，,。；;\s]+)[，,]\s*(\d{4}-\d{2}-\d{2})[：:]\s*([A-Z_]+)[。.]?\s*(.*)$/);
 if(legacy)return inboxAttendance(legacy[2],legacy[1],inboxStudent(legacy[1]),inboxStatusText(legacy[3]),legacy[4]);
 const service=raw.match(/^(.+?)（([^）]+)）\s*(\d{4}-\d{2}-\d{2})\s*的考勤已登记为[“"]([^”"]+)[”"][。.]?\s*(.*)$/);
 if(service){
  const who=/^学号\b/.test(service[1])?`学号 ${service[2]}`:`${service[1]}（${service[2]}）`;
  return inboxAttendance(service[3],service[2],who,service[4],service[5]);
 }
 const compact=raw.match(/^(\d{4}-\d{2}-\d{2})\s*[·•]\s*(.+?)\s*[·•]\s*(正常|迟到|缺勤|请假)(?:\s*[；;]\s*说明[：:]\s*(.*))?$/);
 if(compact)return inboxAttendance(compact[1],'',compact[2],compact[3],compact[4]||'');
 const copied=raw.match(/^(.+?)\s*·\s*(通过|驳回)(?:\s*·\s*审核人\s*(.+?))?(?:\s*[；;]\s*原因[：:]\s*(.+))?$/);
 if(copied){
  const note=copied[4]||'';
  return {summary:[copied[1],copied[2],copied[3]?`审核人 ${copied[3]}`:''].filter(Boolean).join(' · '),note,facts:[['申请人',copied[1]],['结果',copied[2]],...(copied[3]?[['审核人',copied[3]]]:[]),...(note?[['原因',note]]:[])]};
 }
 const pending=raw.match(/^学号\s*([^，,。；;\s]+)\s*提交了?[^，,。；;]*申请[，,。]?\s*(.*)$/);
 if(pending){const who=inboxStudent(pending[1]);return {summary:who,note:inboxCleanText(pending[2]),facts:[['申请人',who]]};}
 const decided=raw.match(/^学号\s*([^，,。；;\s]+)\s*的[^，,。；;]*?申请已(通过|驳回)[。.]?\s*(.*)$/);
 if(decided){
  const reviewer=decided[3].match(/审核人[：:]\s*([^。；;]+)/),reason=decided[3].match(/原因[：:]\s*([^。；;]+)/);
  const bits=[inboxStudent(decided[1]),decided[2]];if(reviewer)bits.push(`审核人 ${reviewer[1].trim()}`);
  return {summary:bits.join(' · '),note:reason?reason[1].trim():'',facts:[['申请人',inboxStudent(decided[1])],['结果',decided[2]],...(reviewer?[['审核人',reviewer[1].trim()]]:[]),...(reason?[['原因',reason[1].trim()]]:[])]};
 }
 let text=inboxCleanText(raw.replace(/\b(NORMAL|LATE|ABSENT|LEAVE|PENDING|ANOMALY)\b/g,code=>inboxStatusText(code)));
 const prefix=text.match(/^([^，。:：]{1,24})[：:]\s*(.*)$/);
 if(prefix&&!/[\u4e00-\u9fa5]/.test(prefix[1])&&/[\u4e00-\u9fa5]/.test(prefix[2]))text=prefix[2];
 text=text.replace(/^\d{1,8}[。.、；;]\s*/,'');
 if(!text||!/[\u4e00-\u9fa5]/.test(text))return {summary:'',note:'',facts:[]};
 let summary=text,note='';
 const parts=text.split('。').map(part=>part.trim()).filter(Boolean);
 if(parts.length>1){summary=parts.shift();note=inboxCleanText(parts.join('。'));}
 return {summary,note,facts:[]};
}
function inboxRecordCard(title,fields){
 return `<div class="notice-record"><strong>${esc(title)}</strong><dl>${fields.map(([key,value])=>`<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl></div>`;
}
function inboxRelatedRecord(row,skipKeys){
 const [page,tab]=String(row.target_page||'').split(':');const id=row.target_id;
 if(page==='schedules'){
  const identity=String(row.message||'').match(/^学号\s*([^，,。；;\s]+)[，,]\s*(\d{4}-\d{2}-\d{2})/);
  let s=rowsOf(state.data.schedules,'schedule_id',id)||rowsOf(state.data.schedules,'attendance_id',id);
  if(s&&identity&&(String(s.student_id)!==identity[1]||String(s.schedule_date)!==identity[2]))s=null;
  if(!s)return '';
  const fields=[['队员',`${studentName(s.student_id)}（${s.student_id}）`],['日期',s.schedule_date],['班次',slotName(s.slot_id)],['考勤',label[s.attendance_status]||s.attendance_status||'未登记']].filter(([key])=>!skipKeys?.has(key));
  return inboxRecordCard('排班记录',[...fields,...(s.service_minutes?[['认定时长',hourText(s.service_minutes)]]:[])]);
 }
 if(page==='applications'){
  const source=tab==='transfer'?'transfer':tab==='withdrawal'?'withdrawal':'leave';
  const key=source==='leave'?'leave_id':source==='transfer'?'transfer_id':'withdrawal_id';
  const a=rowsOf(state.data[source],key,id);if(!a)return '';
  return inboxRecordCard('申请记录',[['申请人',`${studentName(a.student_id)}（${a.student_id}）`],['申请类型',source==='leave'?'请假':source==='transfer'?'换班':'退队'],['原因',a.reason||'未填写'],['进度',appStatus(a,source)[1]]]);
 }
 if(page==='hours'||page==='credit'){
  const s=rowsOf(state.data.students,'student_id',id);if(!s)return '';
  return inboxRecordCard('志愿者',[['姓名',s.name],['学号',s.student_id],['状态',label[s.status]||s.status],...(page==='credit'?[['信用分',`${s.credit_score} 分`]]:[])]);
 }
 if(page==='account'||page==='scope'){
  const a=rowsOf(state.data.admins,'admin_id',id);if(a)return inboxRecordCard('管理员',[['姓名',a.name],['登录账号',a.account],['角色',roleName(a.role)]]);
 }
 return '';
}
function inboxCanGo(row){
 const [page]=String(row.target_page||'').split(':');
 if(page==='collections'||page==='applications')return true;
 if((page==='hours'||page==='credit')&&rowsOf(state.data.students,'student_id',row.target_id))return true;
 return false;
}
function inboxNavigate(row){
 const [page,tab]=String(row.target_page||'').split(':');if(!page)return;
 if(page==='collections')state.focusCollection=row.target_id;
 if(page==='hours'||page==='credit'){const student=rowsOf(state.data.students,'student_id',row.target_id);if(student){state.selectedStudent=student.student_id;state.studentQuery=student.student_id;}}
 navigate(page);if(tab){state.tab=tab;renderPage();}
}
function openInboxDetail(row){
 const view=inboxReadable(row),fields=view.facts;
 const related=inboxRelatedRecord(row,new Set(fields.map(([key])=>key)));
 const facts=fields.length?`<dl class="notice-detail-facts">${fields.map(([key,value])=>`<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`:'';
 const extra=view.note?`<p class="notice-detail-note">${esc(view.note)}</p>`:'';
 const action=inboxCanGo(row)?`<div class="notice-detail-actions"><button class="btn" type="button" data-action="inbox-goto" data-id="${row.notice_id}">打开${esc(inboxTargetLabels[String(row.target_page||'').split(':')[0]]||'相关页面')}</button></div>`:'';
 openReadOnlyDialog(inboxTitle(row),`<div class="notice-detail">${!fields.length&&view.summary?`<p class="notice-detail-summary">${esc(view.summary)}</p>`:''}${extra}${facts}${related}${action}</div>`,`${inboxCategoryLabel(row.category)} · ${fmtDate(row.created_at)}${row.read_at?'':' · 未读'}`);
}
function inboxDetailAvailable(row){
 const [page]=String(row.target_page||'').split(':');
 if(page!=='schedules'&&page!=='applications')return false;
 return inboxReadable(row).facts.length>0||Boolean(inboxRelatedRecord(row));
}
function inboxRowHtml(row){
 const view=inboxReadable(row);
 const detail=inboxDetailAvailable(row);
 const meta=`${fmtDate(row.created_at)}${row.read_at?'':' · 未读'}`;
 return `<article class="inbox-item${row.read_at?'':' unread'}"><div class="inbox-check">${row.read_at?'<span class="inbox-check-mark" aria-hidden="true"></span>':`<input type="checkbox" class="control" data-notice-select="${row.notice_id}" aria-label="选择通知 ${esc(inboxTitle(row))}" ${state.inboxSelected?.has(row.notice_id)?'checked':''}>`}</div><div class="inbox-main"><div class="inbox-head"><span class="inbox-category inbox-category--${(row.category||'').toLowerCase()}">${esc(inboxCategoryLabel(row.category))}</span><strong>${esc(inboxTitle(row))}</strong></div>${view.summary?`<p class="inbox-summary">${esc(view.summary)}</p>`:''}${view.note?`<p class="inbox-note">${esc(view.note)}</p>`:''}<div class="inbox-footer"><span class="inbox-meta">${meta}</span><div class="inbox-actions">${detail?`<button class="text-button" data-action="inbox-open" data-id="${row.notice_id}">查看详情</button>`:''}${!row.read_at?`<button class="text-button" data-action="inbox-read" data-id="${row.notice_id}">标为已读</button>`:''}</div></div></div></article>`;
}
function renderInboxRows(){
 const el=$('#inbox-results');if(!el)return;
 const rows=state.inboxRows||[];
 const list=rows.length?`<section class="panel inbox-panel"><div class="inbox-list">${rows.map(inboxRowHtml).join('')}</div></section>`:`<section class="panel">${empty('暂无通知','新的申请、审批和征集通知会显示在这里。')}</section>`;
 el.innerHTML=list+(state.inboxCursor?'<div class="inbox-more"><button class="btn" data-action="inbox-more">加载更多</button></div>':'');
 updateInboxSelection();
}
async function inboxPage(append=false){
 const seq=++state.sequence;
 if(!append){state.inboxSelected=new Set();state.inboxRows=[];state.inboxCursor=null;$('#main').innerHTML=heading('收件箱','申请、审批、征集和考勤变更都在这里。','')+`<div class="toolbar inbox-toolbar" id="inbox-batch"><select class="control" id="inbox-category-filter" aria-label="通知类型">${['',...Object.keys(inboxCategoryLabels)].map(c=>`<option value="${c}" ${state.inboxCategory===c?'selected':''}>${c?esc(inboxCategoryLabel(c)):'全部类型'}</option>`).join('')}</select><button class="btn small" data-action="inbox-filter">${state.inboxUnreadOnly?'显示全部':'仅看未读'}</button><button class="btn small" data-action="inbox-refresh">刷新</button>${inboxBatchBar()}</div><div id="inbox-results">正在读取…</div>`;}
 try{
  const q=new URLSearchParams({limit:'50',unread_only:String(Boolean(state.inboxUnreadOnly))});if(state.inboxCategory)q.set('category',state.inboxCategory);if(append&&state.inboxCursor)q.set('before_id',state.inboxCursor);
  const data=await request('/inbox?'+q);if(seq!==state.sequence)return;
  state.data.inbox=data;updateInboxBadge();state.inboxRows=(append?state.inboxRows:[]).concat(data.items);state.inboxCursor=data.next_cursor;
  state.inboxSelected=new Set([...state.inboxSelected].filter(id=>state.inboxRows.some(r=>r.notice_id===id&&!r.read_at)));
  renderInboxRows();
 }catch(e){if(seq===state.sequence)$('#inbox-results').textContent=e.message;}
}
function markInboxReadLocal(row){
 if(!row||row.read_at)return;
 row.read_at=new Date().toISOString();
 if(state.data.inbox)state.data.inbox.unread_count=Math.max(0,Number(state.data.inbox.unread_count||0)-1);
 state.inboxSelected?.delete(row.notice_id);updateInboxBadge();
}
async function inboxAction(name,id){
 if(state.inboxBusy)return;
 if(name==='inbox-goto'){const row=(state.inboxRows||[]).find(r=>String(r.notice_id)===String(id));if(row){closeDialog(true);inboxNavigate(row);}return;}
 if(name==='inbox-select-all'||name==='inbox-select-none'){state.inboxSelected=new Set(name==='inbox-select-all'?state.inboxRows.filter(r=>!r.read_at).map(r=>r.notice_id):[]);updateInboxSelection();return;}
 if(name==='inbox-filter'){state.inboxUnreadOnly=!state.inboxUnreadOnly;await inboxPage();return;}
 if(name==='inbox-refresh'){await inboxPage();return;}
 if(name==='inbox-more'){await inboxPage(true);return;}
 const row=(state.inboxRows||[]).find(r=>String(r.notice_id)===String(id));const session=state.sessionVersion;
 state.inboxBusy=true;
 try{
  if(name==='inbox-read-batch'){if(!state.inboxSelected?.size)return;setInboxBatchBusy(true);await send('/inbox/read-batch',{notice_ids:[...state.inboxSelected]});}
  else if(name==='inbox-read-all')await send('/inbox/read-all',{});
  else if(row&&!row.read_at)await send(`/inbox/${id}/read`,{});else if(!row)return;
  if(session!==state.sessionVersion||state.page!=='inbox')return;
  if(name==='inbox-open'){
   markInboxReadLocal(row);renderInboxRows();openInboxDetail(row);
   const latest=await request('/inbox?limit=1');if(session===state.sessionVersion){state.data.inbox=latest;updateInboxBadge();}
  }else if(name==='inbox-read'){markInboxReadLocal(row);renderInboxRows();}
  else await inboxPage();
 }catch(e){if(session===state.sessionVersion)notify(e.message,true);}
 finally{state.inboxBusy=false;setInboxBatchBusy(false);}
}
