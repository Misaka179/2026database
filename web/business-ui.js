'use strict';
const businessOptions=()=>[['','全部业务'],...(state.data.businesses||[]).map(b=>[b.business_id,b.name])];
const fileBase64=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
function businessFilter(){return `<div class="field business-filter"><label for="business-filter">业务</label><select id="business-filter" name="business_id">${businessOptions().map(([id,name])=>`<option value="${id}" ${String(state.businessId||'')===String(id)?'selected':''}>${esc(name)}</option>`).join('')}</select></div>`;}
// 业务管理页（含三级导航）在 business-navigation.js 中实现；本文件只保留业务相关的公共工具与其余页面。
async function collectionsPage(){
 if(state.hoursMode==='import'&&state.role==='SUPER'){renderHoursImport();return;}
 const seq=++state.sequence,admin=state.role!=='STUDENT';
 const canCreate=state.role==='SUPER'||(state.data.businesses||[]).some(b=>b.can_collect_all);
 const importButton=state.role==='SUPER'?'<button class="btn" data-action="specialty-open">批量补录</button>':'';
 const buttons=canCreate||importButton?`<div class="button-row">${canCreate?'<button class="btn primary" data-action="collection-create">发起征集</button>':''}${importButton}</div>`:'';
 $('#main').innerHTML=heading(state.role==='STUDENT'?'我的征集':'时长归集',state.role==='STUDENT'?'查看我参与的征集，按征集要求提交材料。':'有业务总负责人的征集由其初审、超级管理员终审；未设置业务总负责人的征集由超级管理员直接审批。',buttons)+'<div id="collections-result">正在读取…</div>';
 try{
  const rows=await request('/hour-collections');if(seq!==state.sequence)return;state.data.collections=rows;state.collectionSelections=new Map();
  $('#collections-result').innerHTML=rows.length?rows.map(c=>`<section class="panel" data-collection-id="${c.collection_id}"><header class="panel-header"><div><h2>${esc(c.title)}</h2><p>${esc(c.business_name)}${c.group_name?' / '+esc(c.group_name):' / 未分组'} · 服务：${esc(c.start_date)} ～ ${esc(c.end_date)}</p><p>申报截止：${esc(c.submission_deadline||'未设置（历史征集）')} · ${c.effective_status==='CLOSED'?'已结束':'进行中'}</p></div><div class="button-row">${c.can_submit?`<button class="btn" data-action="claim-create" data-id="${c.collection_id}">填写申报</button>`:''}${c.can_manage&&c.effective_status==='OPEN'?`<button class="btn" data-action="collection-close" data-id="${c.collection_id}">结束征集</button>`:''}</div></header><p class="section-footer">${c.items.map(i=>`${esc(i.title)}：每天 ${hourText(i.min_minutes)}～${hourText(i.max_minutes)}`).join('；')}</p>${collectionFiles(c)}${collectionBatchBar(c)}${table([...(state.role==='SUPER'?['选择']:[]),'队员','服务日期','事项及工作说明','申报时长','进度及反馈','操作'],c.submissions.map(s=>`<tr>${collectionBatchCell(c,s)}<td>${esc(s.name)}<small>${esc(s.student_id)}</small></td><td>${esc(s.service_date)}</td><td class="wrap">${esc(s.item_title)}<small>${esc(s.remark)}</small>${submissionFiles(s)}</td><td>${hourText(s.service_minutes)}</td><td class="wrap">${badge(s.status)}${s.status==='REJECTED'?`<small>${esc(s.rejection_reason||'')}</small>`:''}${submissionReviewHistory(s)}</td><td>${s.can_review?`<button class="text-button" data-action="claim-decide" data-id="${s.submission_id}">审核</button>`:''}${s.can_correct?`<button class="text-button" data-action="claim-correct" data-id="${s.submission_id}">二次更正</button>`:''}${state.role==='STUDENT'&&c.can_submit&&s.status==='REJECTED'?`<button class="text-button" data-action="claim-edit" data-id="${s.submission_id}">修改重报</button>`:''}</td></tr>`))}</section>`).join(''):`<section class="panel">${empty('暂无时长征集',admin?'由业务总负责人在本业务发起征集。':'负责人发布的征集会出现在这里。')}</section>`;
  if(state.focusCollection){document.querySelector(`[data-collection-id="${Number(state.focusCollection)}"]`)?.scrollIntoView({block:'start'});state.focusCollection=null;}
 }catch(e){if(seq===state.sequence)$('#collections-result').textContent=e.message;}
}
function specialtyForm(){
 return `<section class="panel"><div class="panel-content padded"><div class="form-grid">${field('specialty-business','业务名称',{full:true,maxLength:100,placeholder:'例如：讲解队、校庆专项服务'})}<div class="field full"><label for="specialty-file">Excel 文件</label><input id="specialty-file" type="file" accept=".xlsx"></div>${field('specialty-password','新队员初始密码',{type:'password',required:false,full:true,help:'存在新学号时必填，已有账号密码不会改变。'})}</div><div class="button-row"><button class="btn" data-action="specialty-template">下载导入模板</button><button class="btn primary" data-action="specialty-preview">预览导入</button></div><div id="specialty-preview" aria-live="polite"></div></div></section>`;
}
function specialtyHistoryTime(value){return String(value||'').replace('T',' ').slice(0,16);}
async function loadSpecialtyHistory(){
 const host=$('#specialty-history-body');if(!host)return;
 try{
  const rows=await request('/specialty-imports');
  if(!host.isConnected)return;
  host.innerHTML=rows.length?rows.map(r=>`<div class="specialty-history-row"><div class="specialty-history-main"><strong>${esc(r.business_name)}</strong><small>#${r.batch_id} · ${esc(r.admin_name||'—')}</small></div><div class="specialty-history-meta"><span>写入 ${r.row_count} 条 · ${r.student_count} 人</span><small>${esc(specialtyHistoryTime(r.create_time))}</small></div></div>`).join(''):empty('暂无批量补录批次','完成一次导入后会显示在这里。');
 }catch(e){if(host.isConnected)host.innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
}
function renderHoursImport(){
 state.specialtyPreview=null;
 $('#main').innerHTML=heading('时长归集 · 批量补录','上传专项业务名单与每次服务的日期、事项、时长，先预览再确认。','<button type="button" class="text-button" data-action="specialty-back">返回征集列表</button>')+specialtyForm()+`<section class="panel specialty-history"><header class="panel-header"><div><h2>最近批量补录</h2><p>仅显示最近 10 个批次。</p></div></header><div id="specialty-history-body" class="specialty-history-body">正在读取…</div></section>`;
 loadSpecialtyHistory();
}
function specialtyPage(){state.hoursMode='import';renderHoursImport();}
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
  if(commit){notify(result.replayed?'该文件已经导入，本次未重复计时。':`已导入 ${result.imported} 条，跳过 ${result.skipped} 条。`);state.hoursMode='collections';await refresh();return;}
  state.specialtyPreview={name,encoded};
  $('#specialty-preview').innerHTML=result.replayed?'<p class="notice">该业务已导入过此文件，不会重复计时。</p>':`<p>共 ${result.rows.length} 条，新学号 ${result.new_students} 个。</p>${result.errors.map(e=>`<p class="notice error">第 ${e.row} 行：${esc(e.message)}</p>`).join('')}${table(['行号','学号 / 姓名','日期 / 事项','时长','重复处理'],result.rows.map(r=>`<tr><td>${r.row}</td><td>${esc(r.student_id)}<small>${esc(r.name)}</small></td><td>${esc(r.service_date)}<small>${esc(r.title)}</small></td><td>${hourText(r.service_minutes)}</td><td>${result.duplicates.includes(r.row)?`<select data-duplicate-row="${r.row}" aria-label="第${r.row}行重复处理"><option value="">请选择</option><option value="skip">跳过重复记录</option><option value="separate">确认为另一项独立服务</option></select>`:'无重复'}</td></tr>`))}${!result.errors.length?'<button class="btn primary" data-action="specialty-commit">确认导入以上记录</button>':''}`;
 }catch(e){notify(e.message,true);}finally{state.importBusy=false;controls.forEach(el=>el.disabled=false);}
}
function businessAction(name,id,kind){
 if(collectionBatchAction(name,id))return true;
 const biz=state.data.businesses||[];
 if(name==='business-term'){state.businessTerm=$('#business-term').value;businessesPage();return true;}
 if(name==='business-week'){
  const r=state.data.businessWeeks[Number(id)];
  openDialog(`${r.business_name} · 第 ${r.week_no} 周`,'停工会撤销该周时长和对应考勤扣分；历史周只有超级管理员可以更正。',field('working','本周安排',{options:[['true','正常上工'],['false','本周停工']],value:String(Boolean(r.working)),full:true})+reasonField(),v=>send(`/businesses/${r.business_id}/semesters/${state.businessTerm}/weeks/${r.week_no}`,{working:v.working==='true',reason:v.reason},'PUT'));return true;
 }
 if(name==='garden-confirm'){openDialog('确认开心花园本周服务','确认已完成本周服务，认定90分钟。本周A/B岗位调整不会重复计时；日期归属当周周日。',reasonField(),v=>send(`/schedules/${id}/confirm-weekly`,v));return true;}
 if(name==='collection-create'){console.log('[DEBUG] businessAction collection-create called');openCollectionCreate();return true;}
 if(name==='collection-file'){showCollectionFile(id,kind);return true;}
 if(name==='submission-file'){showSubmissionFile(id,kind);return true;}
 if(name==='collection-close'){openDialog('结束时长征集','结束后停止新增申报和修改重报，已提交的申报继续审批。',reasonField(),v=>send(`/hour-collections/${id}/close`,v),'确认结束');return true;}
 if(['claim-create','claim-edit','claim-decide','claim-correct'].includes(name)){
  const rows=state.data.collections||[];const sub=name==='claim-create'?null:rows.flatMap(c=>c.submissions).find(s=>String(s.submission_id)===String(id));
  const c=name==='claim-create'?rows.find(c=>String(c.collection_id)===String(id)):rows.find(c=>c.submissions.includes(sub));
  if(name==='claim-decide'||name==='claim-correct'){
   const correction=name==='claim-correct',half=c.minute_step===30;
   const reviewLabel=state.role==='SUPER'?'终审 / 直接审批':'业务负责人初审';
   openDialog(correction?'二次更正审批结果':reviewLabel+'时长申报',`${sub.name} · ${sub.service_date} · ${sub.item_title}。${correction?'更正会同步调整已入账时长，须填写原因。':state.role==='SUPER'?'终审通过后计入时长；无业务总负责人的征集由超管直接审批。':'初审通过后仍需超级管理员终审，初审不会计入时长。'}`,    field('approved','审批结果',{options:[['true','通过'],['false','打回修改']],full:true})+(correction?field('service_minutes',half?'更正后的时长（小时）':'更正后的认定分钟',{type:'number',min:half?0.5:0,max:half?24:1440,step:half?0.5:1,value:sub.service_minutes/(half?60:1),full:true}):'')+field('reason',correction?'更正原因':'审批说明（打回必填）',{type:'textarea',required:correction,full:true,maxLength:500}),v=>{
     if((correction||v.approved==='false')&&!v.reason.trim())throw new Error('请填写具体原因。');
     const body={approved:v.approved==='true',expected_revision:sub.revision,reason:v.reason};if(correction)body.service_minutes=half?halfHourMinutes(v.service_minutes):Number(v.service_minutes);
     return send(`/hour-submissions/${id}/${correction?'correction':'decision'}`,body);
    });return true;
  }
  openSubmissionForm(c,sub);return true;
 }
 if(name==='specialty-open'){if(state.role==='SUPER'){state.hoursMode='import';collectionsPage();}return true;}
 if(name==='specialty-back'){state.hoursMode='collections';collectionsPage();return true;}
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
  openReadOnlyDialog('请假证明',(urls.map(u=>`<img class="collection-image" src="${u}" alt="请假证明图片">`).join('')||'<p class="muted">历史申请未附图片。</p>'),'图片仅用于核验本次请假，关闭后释放。');
  dialog.addEventListener('close',()=>urls.forEach(URL.revokeObjectURL),{once:true});
 }catch(e){notify(e.message,true);}
}
