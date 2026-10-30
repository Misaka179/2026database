'use strict';
const businessOptions=()=>[['','全部业务'],...(state.data.businesses||[]).map(b=>[b.business_id,b.name])];
const fileBase64=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
function businessFilter(){return `<div class="field business-filter"><label for="business-filter">业务</label><select id="business-filter" name="business_id">${businessOptions().map(([id,name])=>`<option value="${id}" ${String(state.businessId||'')===String(id)?'selected':''}>${esc(name)}</option>`).join('')}</select></div>`;}
async function businessesPage(){
 const seq=++state.sequence;
 const editable=state.role==='SUPER';
 const biz=state.data.businesses||[];
 $('#main').innerHTML=heading('业务管理','维护业务、固定时段及负责人；停用归档保留历史，可恢复。',editable?'<div class="button-row"><button class="btn primary" data-action="business-create">新增业务</button><button class="btn" data-action="manual-event">录入临时服务</button></div>':'')+
 `<section class="panel">${table(['业务','类型 / 状态','管理方式',...(editable?['操作']:[])],biz.filter(b=>editable||b.can_collect||b.can_manage||b.manager_scope!=='NONE').map(b=>`<tr><td>${esc(b.name)}</td><td>${b.kind==='FIXED'?'固定时段':b.kind==='WEEKLY'?'每周岗位':'非固定业务'}<small>${badge(b.status||'ACTIVE')}</small></td><td>${b.manager_scope==='SLOT'?'按时段管理':b.manager_scope==='BUSINESS'?esc(adminName(b.manager_admin_id)):'按征集管理范围授权'}</td>${editable?`<td>${b.status==='ARCHIVED'?`<button class="text-button" data-action="business-restore" data-id="${b.business_id}">恢复业务</button>`:`<button class="text-button" data-action="business-rename" data-id="${b.business_id}">改名</button><button class="text-button" data-action="business-archive" data-id="${b.business_id}">停用归档</button>${b.kind==='FIXED'?`<button class="text-button" data-action="business-slot" data-id="${b.business_id}">添加时段</button>`:''}${b.manager_scope==='BUSINESS'?`<button class="text-button" data-action="business-manager" data-id="${b.business_id}">设置管理员</button>`:b.kind==='EVENT'?`<button class="text-button" data-action="event-member" data-id="${b.business_id}">调整业务名单</button>`:'<button class="text-button" data-page="basics">时段与成员设置</button>'}`}</td>`:''}</tr>`))}</section>`+
 `<div class="query-form"><div class="field"><label for="business-term">查看学期</label><select id="business-term">${(state.data.semesters||[]).map(t=>`<option value="${t.semester_id}" ${String(state.businessTerm||'')===String(t.semester_id)?'selected':''}>${esc(t.name)}</option>`).join('')}</select></div><button class="btn" data-action="business-term">查看每周安排</button></div><section class="panel" id="business-weeks">正在读取每周安排…</section>`;
 const term=$('#business-term')?.value;if(!term){$('#business-weeks').textContent='请先设置学期。';return;}
 try{
  const rows=await request('/business-weeks?semester_id='+term);if(seq!==state.sequence)return;state.data.businessWeeks=rows;state.businessTerm=term;
  $('#business-weeks').innerHTML=table(['业务','周次及日期','安排','操作'],rows.map((r,i)=>`<tr><td>${esc(r.business_name)}</td><td>第 ${r.week_no} 周<small>${esc(r.start_date)} ～ ${esc(r.end_date)}</small></td><td>${r.working?'正常上工':'本周停工'}<small>${esc(r.reason)}</small></td><td><button class="text-button" data-action="business-week" data-id="${i}">更正安排</button></td></tr>`),'暂无可管理的业务','普通管理员只可设置自己负责的开心花园、青广宣传。');
 }catch(e){if(seq===state.sequence)$('#business-weeks').textContent=e.message;}
}
async function collectionsPage(){
 const seq=++state.sequence,admin=state.role!=='STUDENT';
 const buttons=admin?'<div class="button-row"><button class="btn" data-page="collection-management">管理范围</button><button class="btn primary" data-action="collection-create">发起征集</button></div>':'';
 $('#main').innerHTML=heading('时长征集','管理员初审，超级管理员终审后计入时长；申报截止前可补报服务范围内的工作。',buttons)+'<div id="collections-result">正在读取…</div>';
 try{
  const rows=await request('/hour-collections');if(seq!==state.sequence)return;state.data.collections=rows;state.collectionSelections=new Map();
  $('#collections-result').innerHTML=rows.length?rows.map(c=>`<section class="panel" data-collection-id="${c.collection_id}"><header class="panel-header"><div><h2>${esc(c.title)}</h2><p>${esc(c.business_name)}${c.group_name?' / '+esc(c.group_name):' / 未分组'} · 服务：${esc(c.start_date)} ～ ${esc(c.end_date)}</p><p>申报截止：${esc(c.submission_deadline||'未设置（历史征集）')} · ${c.effective_status==='CLOSED'?'已结束':'进行中'}</p></div><div class="button-row">${c.can_submit?`<button class="btn" data-action="claim-create" data-id="${c.collection_id}">填写申报</button>`:''}${c.can_manage&&c.effective_status==='OPEN'?`<button class="btn" data-action="collection-close" data-id="${c.collection_id}">结束征集</button>`:''}</div></header><p class="section-footer">${c.items.map(i=>`${esc(i.title)}：每天 ${hourText(i.min_minutes)}～${hourText(i.max_minutes)}`).join('；')}</p>${collectionFiles(c)}${collectionBatchBar(c)}${table([...(state.role==='SUPER'?['选择']:[]),'队员','服务日期','事项及工作说明','申报时长','进度及反馈','操作'],c.submissions.map(s=>`<tr>${collectionBatchCell(c,s)}<td>${esc(s.name)}<small>${esc(s.student_id)}</small></td><td>${esc(s.service_date)}</td><td class="wrap">${esc(s.item_title)}<small>${esc(s.remark)}</small>${submissionFiles(s)}</td><td>${hourText(s.service_minutes)}</td><td class="wrap">${badge(s.status)}<small>${esc(s.rejection_reason||'')}</small>${submissionReviewHistory(s)}</td><td>${s.can_review?`<button class="text-button" data-action="claim-decide" data-id="${s.submission_id}">${state.role==='NORMAL'?'初审':'终审'}</button>`:''}${s.can_correct?`<button class="text-button" data-action="claim-correct" data-id="${s.submission_id}">二次更正</button>`:''}${state.role==='STUDENT'&&c.can_submit&&s.status==='REJECTED'?`<button class="text-button" data-action="claim-edit" data-id="${s.submission_id}">修改重报</button>`:''}</td></tr>`))}</section>`).join(''):empty('暂无时长征集',admin?'在管理范围内发起征集，或先申请管理范围。':'范围内的征集发布后会出现在这里。');
  if(state.focusCollection){document.querySelector(`[data-collection-id="${Number(state.focusCollection)}"]`)?.scrollIntoView({block:'start'});state.focusCollection=null;}
 }catch(e){if(seq===state.sequence)$('#collections-result').textContent=e.message;}
}
function specialtyPage(){
 $('#main').innerHTML=heading('专项名单及时长导入','填写专项业务名称，上传队员和每次服务的日期、事项、时长。先预览再确认。')+
 `<section class="panel"><div class="dialog-body"><div class="form-grid">${field('specialty-business','业务名称',{full:true,maxLength:100,placeholder:'例如：讲解队、校庆专项服务'})}<div class="field full"><label for="specialty-file">Excel 文件</label><input id="specialty-file" type="file" accept=".xlsx"></div>${field('specialty-password','新队员初始密码',{type:'password',required:false,full:true,help:'存在新学号时必填，已有账号密码不会改变。'})}</div><div class="button-row"><button class="btn" data-action="specialty-template">下载导入模板</button><button class="btn primary" data-action="specialty-preview">预览导入</button></div><div id="specialty-preview" aria-live="polite"></div></div></section>`;
 state.specialtyPreview=null;
}
async function downloadBusinessFile(path,filename){
 const session=state.sessionVersion;const response=await fetch(path,{headers:{Authorization:`Bearer ${state.token}`}});
 if(!response.ok)throw new Error('下载失败，请刷新后重试');const blob=await response.blob();if(session!==state.sessionVersion)return;
 const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
}
async function previewSpecialty(commit=false){
 if(state.importBusy)return;state.importBusy=true;
 const seq=state.sequence,session=state.sessionVersion;
 const controls=[...$('#main').querySelectorAll('input,button,select')];
 try{
  const name=$('[name="specialty-business"]').value.trim(),file=$('#specialty-file').files[0];
  if(!name||!file||file.size>8*1024*1024)throw new Error('请填写业务名称并选择不超过8MB的 .xlsx 文件');
  const encoded=await fileBase64(file);const password=$('[name="specialty-password"]').value;
  if(commit&&(!state.specialtyPreview||state.specialtyPreview.name!==name||state.specialtyPreview.encoded!==encoded))throw new Error('文件或业务已改变，请重新预览');
  const duplicates=Object.fromEntries([...document.querySelectorAll('[data-duplicate-row]')].map(el=>[el.dataset.duplicateRow,el.value]));
  if(commit&&Object.values(duplicates).some(x=>!x))throw new Error('请处理每条疑似重复记录');
  controls.forEach(el=>el.disabled=true);
  const result=await send('/specialty-imports',{business_name:name,file_base64:encoded,commit,initial_password:password||null,duplicate_rows:commit?duplicates:{}});
  if(seq!==state.sequence||session!==state.sessionVersion)return;
  if(commit){notify(result.replayed?'该文件已经导入，本次未重复计时。':`已导入 ${result.imported} 条，跳过 ${result.skipped} 条。`);await refresh();return;}
  state.specialtyPreview={name,encoded};
  $('#specialty-preview').innerHTML=result.replayed?'<p class="notice">该业务已导入过此文件，不会重复计时。</p>':`<p>共 ${result.rows.length} 条，新学号 ${result.new_students} 个。</p>${result.errors.map(e=>`<p class="notice error">第 ${e.row} 行：${esc(e.message)}</p>`).join('')}${table(['行号','学号 / 姓名','日期 / 事项','时长','重复处理'],result.rows.map(r=>`<tr><td>${r.row}</td><td>${esc(r.student_id)}<small>${esc(r.name)}</small></td><td>${esc(r.service_date)}<small>${esc(r.title)}</small></td><td>${hourText(r.service_minutes)}</td><td>${result.duplicates.includes(r.row)?`<select data-duplicate-row="${r.row}" aria-label="第${r.row}行重复处理"><option value="">请选择</option><option value="skip">跳过重复记录</option><option value="separate">确认为另一项独立服务</option></select>`:'无重复'}</td></tr>`))}${!result.errors.length?'<button class="btn primary" data-action="specialty-commit">确认导入以上记录</button>':''}`;
 }catch(e){notify(e.message,true);}finally{state.importBusy=false;controls.forEach(el=>el.disabled=false);}
}
function businessAction(name,id,kind){
 if(collectionBatchAction(name,id))return true;
 const biz=state.data.businesses||[];
 if(name==='business-term'){state.businessTerm=$('#business-term').value;businessesPage();return true;}
 if(name==='business-manager'){
  const b=rowsOf(biz,'business_id',id);
  openDialog('设置 '+b.name+' 管理员','该管理员可处理本业务考勤、请假和每周开工安排。',field('manager_admin_id','管理员',{options:[['','待分配'],...(state.data.admins||[]).filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE').map(a=>[a.admin_id,a.name])],value:b.manager_admin_id||'',required:false,full:true}),v=>send(`/businesses/${id}/manager`,{manager_admin_id:v.manager_admin_id?Number(v.manager_admin_id):null},'PUT'));return true;
 }
 if(name==='business-week'){
  const r=state.data.businessWeeks[Number(id)];
  openDialog(`${r.business_name} · 第 ${r.week_no} 周`,'停工会撤销该周时长和对应考勤扣分；历史周只有超级管理员可以更正。',field('working','本周安排',{options:[['true','正常上工'],['false','本周停工']],value:String(Boolean(r.working)),full:true})+reasonField(),v=>send(`/businesses/${r.business_id}/semesters/${state.businessTerm}/weeks/${r.week_no}`,{working:v.working==='true',reason:v.reason},'PUT'));return true;
 }
 if(name==='garden-confirm'){openDialog('确认开心花园本周服务','确认已完成本周服务，认定90分钟。本周A/B岗位调整不会重复计时；日期归属当周周日。',reasonField(),v=>send(`/schedules/${id}/confirm-weekly`,v));return true;}
 if(name==='collection-create'){openCollectionCreate();return true;}
 if(name==='collection-file'){showCollectionFile(id,kind);return true;}
 if(name==='submission-file'){showSubmissionFile(id,kind);return true;}
 if(name==='collection-close'){openDialog('结束时长征集','结束后停止新增申报和修改重报，已提交的申报继续审批。',reasonField(),v=>send(`/hour-collections/${id}/close`,v),'确认结束');return true;}
 if(['claim-create','claim-edit','claim-decide','claim-correct'].includes(name)){
  const rows=state.data.collections||[];const sub=name==='claim-create'?null:rows.flatMap(c=>c.submissions).find(s=>String(s.submission_id)===String(id));
  const c=name==='claim-create'?rows.find(c=>String(c.collection_id)===String(id)):rows.find(c=>c.submissions.includes(sub));
  if(name==='claim-decide'||name==='claim-correct'){
   const correction=name==='claim-correct',half=c.minute_step===30;
   openDialog(correction?'二次更正审批结果':state.role==='NORMAL'?'初审时长申报':'终审时长申报',`${sub.name} · ${sub.service_date} · ${sub.item_title}。${correction?'更正会同步调整已入账时长，须填写原因。':state.role==='NORMAL'?'初审通过后等待超级管理员终审，不立即计时。':'终审通过后计入时长。'}`,
    field('approved','审批结果',{options:[['true','通过'],['false','打回修改']],full:true})+(correction?field('service_minutes',half?'更正后的时长（小时）':'更正后的认定分钟',{type:'number',min:half?0.5:0,max:half?24:1440,step:half?0.5:1,value:sub.service_minutes/(half?60:1),full:true}):'')+field('reason',correction?'更正原因':'审批说明（打回必填）',{type:'textarea',required:correction,full:true,maxLength:500}),v=>{
     if((correction||v.approved==='false')&&!v.reason.trim())throw new Error('请填写具体原因。');
     const body={approved:v.approved==='true',expected_revision:sub.revision,reason:v.reason};if(correction)body.service_minutes=half?halfHourMinutes(v.service_minutes):Number(v.service_minutes);
     return send(`/hour-submissions/${id}/${correction?'correction':'decision'}`,body);
    });return true;
  }
  openSubmissionForm(c,sub);return true;
 }
 if(name==='specialty-preview'||name==='specialty-commit'){previewSpecialty(name==='specialty-commit');return true;}
 if(name==='specialty-template'){downloadBusinessFile('/specialty-imports/template','专项时长导入模板.xlsx').catch(e=>notify(e.message,true));return true;}
 if(name==='event-confirm'){const r=rowsOf(state.data.schedules,'schedule_id',id);openDialog('认定临时服务时长','填写本次实际认定分钟数，仅影响这次服务。',field('service_minutes','认定分钟',{type:'number',min:0,max:1440,step:1,value:r.recognition_minutes})+reasonField(),v=>send(`/schedules/${id}/recognize-event`,{service_minutes:Number(v.service_minutes),reason:v.reason}));return true;}
 if(name==='event-member'){openDialog('调整专项业务名单','只调整此业务的归属，其他业务与历史时长保留。',field('student_id','学号',{maxLength:32})+field('active','操作',{options:[['true','加入业务'],['false','退出此业务']]})+field('effective_date','生效日期',{type:'date',value:getDate(),min:getDate()})+reasonField(),v=>send(`/businesses/${id}/members/${encodeURIComponent(v.student_id)}`,{active:v.active==='true',effective_date:v.effective_date,reason:v.reason},'PUT'));return true;}
 if(name==='manual-event'){
  const key=crypto.randomUUID();
  openDialog('录入临时服务','未来日期先建立排班，完成后认定；今天或历史日期按填写分钟直接认定。',field('business_name','业务名称',{maxLength:100})+field('student_id','学号',{maxLength:32})+field('title','工作事项',{maxLength:100,full:true})+field('service_date','服务日期',{type:'date'})+field('service_minutes','认定分钟',{type:'number',min:0,max:1440,step:1})+reasonField(),v=>send('/business-events',{...v,service_minutes:Number(v.service_minutes),request_key:key}));return true;
 }
 if(name==='leave'){
  const r=rowsOf(state.data.schedules,'schedule_id',id);const opts=id?[[id,`${r.schedule_date} ${slotName(r.slot_id)}`]]:scheduleOptions();
  if(!opts.length){notify('暂无可请假的未来排班',true);return true;}
  openDialog('提交请假申请','请填写原因并上传1至3张PNG/JPEG证明，每张不超过2MB。',field('schedule_id','对应排班',{options:opts,full:true})+reasonField()+'<div class="field full"><label for="leave-images">证明图片</label><input id="leave-images" type="file" accept="image/png,image/jpeg" multiple required></div>',async v=>{
   const files=[...$('#leave-images').files];if(!files.length||files.length>3||files.some(f=>f.size>2*1024*1024))throw new Error('请上传1至3张图片，每张不超过2MB');
   return send('/applications/leave',{schedule_id:Number(v.schedule_id),reason:v.reason,images:await Promise.all(files.map(fileBase64))});
  });return true;
 }
 if(name==='leave-evidence'){showLeaveEvidence(id);return true;}
 if(name==='approve'&&kind==='leave'){
  const a=rowsOf(state.data.leave,'leave_id',id);
  openDialog('审批请假',`${studentName(a.student_id)}：${a.reason}`,field('approved','审批结果',{options:[['true','通过'],['false','打回']],full:true})+field('reason','打回原因',{type:'textarea',required:false,full:true,maxLength:500}),v=>{if(v.approved==='false'&&!v.reason.trim())throw new Error('打回必须填写原因');return send(`/applications/leave/${id}/decision`,{approved:v.approved==='true',reason:v.reason});});return true;
 }
 return false;
}
async function showLeaveEvidence(id){
 const session=state.sessionVersion;
 try{
  const items=await request(`/applications/leave/${id}/evidence`);if(session!==state.sessionVersion)return;
  const urls=await Promise.all(items.map(async i=>{const r=await fetch(`/applications/leave/${id}/evidence/${i.attachment_id}`,{headers:{Authorization:`Bearer ${state.token}`}});if(!r.ok)throw new Error('图片读取失败');return URL.createObjectURL(await r.blob());}));
  if(session!==state.sessionVersion){urls.forEach(URL.revokeObjectURL);return;}
  previousFocus=document.activeElement;modalSubmit=null;modalVersion++;
  dialog.innerHTML='<header class="dialog-header"><h2 id="dialog-title">请假证明</h2><button class="close-button" data-action="close">关闭</button></header><div class="dialog-body">'+(urls.map(u=>`<img src="${u}" alt="请假证明图片" style="max-width:100%;height:auto">`).join('')||'<p>历史申请未附图片。</p>')+'</div>';dialog.showModal();dialog.addEventListener('close',()=>urls.forEach(URL.revokeObjectURL),{once:true});
 }catch(e){notify(e.message,true);}
}

