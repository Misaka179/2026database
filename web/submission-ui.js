'use strict';
function submissionFiles(s){
 return (s.attachments||[]).map(f=>`<button class="text-button" data-action="submission-file" data-id="${f.attachment_id}" data-kind="${s.submission_id}">${esc(f.filename)} · ${Math.ceil(f.size_bytes/1024)} KB</button>`).join('');
}
function submissionReviewHistory(s){
 return s.reviews?.length?'<details><summary>审批记录</summary>'+s.reviews.map(r=>`<p>${esc(({FIRST:'初审',FINAL:'终审',CORRECTION:'二次更正'})[r.stage])}：${r.approved?'通过':'打回'} · ${esc(r.admin_name)}<small>${fmtDate(r.created_at)} · ${hourText(r.service_minutes)}<br>${esc(r.reason||'未附说明')}</small></p>`).join('')+'</details>':'';
}
async function showSubmissionFile(attachmentId,submissionId){
 const s=(state.data.collections||[]).flatMap(c=>c.submissions).find(s=>String(s.submission_id)===String(submissionId));
 const f=s?.attachments?.find(f=>String(f.attachment_id)===String(attachmentId));if(!f)return;
 const session=state.sessionVersion;
 try{
  const preview=['application/pdf','image/png','image/jpeg'].includes(f.mime_type);
  const r=await fetch(`/hour-submissions/${submissionId}/attachments/${attachmentId}?preview=${preview}`,{headers:{Authorization:`Bearer ${state.token}`}});
  if(!r.ok)throw new Error('附件读取失败或没有查看权限。');
  const blob=await r.blob();if(session!==state.sessionVersion)return;
  const url=URL.createObjectURL(blob);
  if(!preview){const a=document.createElement('a');a.href=url;a.download=f.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);return;}
  openDialog(f.filename,'志愿者提交的工作说明附件','',()=>{});
  $('.dialog-body',dialog).innerHTML=(f.mime_type==='application/pdf'?`<iframe class="collection-preview" sandbox title="${esc(f.filename)}" src="${url}"></iframe>`:`<img class="collection-image" alt="${esc(f.filename)}" src="${url}">`)+`<p><a href="${url}" download="${esc(f.filename)}">下载原文件</a></p>`;
  modalSubmit=null;dialog.addEventListener('close',()=>URL.revokeObjectURL(url),{once:true});
 }catch(e){if(session===state.sessionVersion)notify(e.message,true);}
}
function openSubmissionForm(c,sub){
 const range=i=>({min:Math.max(0.5,Math.ceil(i.min_minutes/30)/2),max:Math.min(24,Math.floor(i.max_minutes/30)/2)});
 let retained=[...(sub?.attachments||[])],added=[],changed=false;
 openDialog(sub?'修改并重新申报':'填写服务时长','按实际服务日期填写；管理员初审、超级管理员终审后计时。可填写文字说明并上传文件。',
  field('item_id','工作事项',{options:c.items.map(i=>[i.item_id,`${i.title}（${range(i).min<=range(i).max?range(i).min+'～'+range(i).max+'小时/天':'无可申报的半小时时长'}）`]),value:sub?.item_id||'',full:true})+
  field('service_date','实际服务日期',{type:'date',min:c.start_date,max:c.end_date<getDate()?c.end_date:getDate(),value:sub?.service_date||''})+
  field('service_minutes','申报时长（小时）',{type:'number',min:0.5,max:24,step:0.5,value:sub?sub.service_minutes/60:'',help:'以0.5小时递增，例如0.5、1.0、1.5。历史值不会自动取整。'})+'<p id="submission-range-error" class="notice error full" hidden></p>'+
  field('remark','工作说明',{type:'textarea',required:false,full:true,maxLength:500,value:sub?.remark||''})+
  '<div class="field full"><label for="submission-files">工作说明附件（选填）</label><input id="submission-files" type="file" multiple accept=".pdf,.docx,.xlsx,.txt,.jpg,.jpeg,.png"><small>最多3个，每个不超过2MB。支持PDF、Word、Excel、TXT和JPG/PNG。</small><div id="submission-file-list"></div><p id="submission-files-error" class="notice error" hidden></p></div>',async v=>{
   if(sub&&(Number(v.item_id)!==sub.item_id||v.service_date!==sub.service_date))throw new Error('重报时请保留原事项和日期；其他日期请新建申报。');
   const body={...v,item_id:Number(v.item_id),service_minutes:halfHourMinutes(v.service_minutes),expected_revision:sub?.revision??null};
   const chosen=c.items.find(i=>i.item_id===body.item_id);if(!chosen||body.service_minutes<chosen.min_minutes||body.service_minutes>chosen.max_minutes)throw new Error('申报时长不在该事项允许范围内。');
   const controls=[...dialog.querySelectorAll('input,select,textarea,button')];const previous=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);
   try{
    if(changed||!sub){
     const existing=await Promise.all(retained.map(async f=>{const r=await fetch(`/hour-submissions/${sub.submission_id}/attachments/${f.attachment_id}`,{headers:{Authorization:`Bearer ${state.token}`}});if(!r.ok)throw new Error('原附件读取失败，请重试或移除后重新上传。');return {filename:f.filename,file_base64:await fileBase64(await r.blob())};}));
     body.attachments=existing.concat(await Promise.all(added.map(async f=>({filename:f.name,file_base64:await fileBase64(f)}))));
    }
    return await send('/hour-submissions',body);
   }finally{controls.forEach((el,i)=>el.disabled=previous[i]);}
  },'提交申报');
 function updateRange(){const i=c.items.find(i=>String(i.item_id)===$('#f-item_id').value);if(!i)return;const bounds=range(i),invalid=bounds.min>bounds.max;$('#f-service_minutes').min=bounds.min;$('#f-service_minutes').max=bounds.max;$('#submission-range-error').hidden=!invalid;$('#submission-range-error').textContent='该事项范围没有合法的半小时时长，请联系管理员重新发布事项。';$('#action-dialog button[type="submit"]').disabled=invalid;}
 $('#f-item_id').addEventListener('change',updateRange);updateRange();
 function draw(){
  $('#submission-file-list').innerHTML=retained.map(f=>`<div>${esc(f.filename)} · 已上传 <button class="text-button" type="button" data-remove-retained="${f.attachment_id}">移除</button></div>`).join('')+added.map((f,i)=>`<div>${esc(f.name)} · ${Math.ceil(f.size/1024)} KB <button class="text-button" type="button" data-remove-added="${i}">移除</button></div>`).join('');
 }
 $('#submission-files').addEventListener('change',e=>{
  const files=[...e.target.files];e.target.value='';const error=$('#submission-files-error');error.hidden=true;
  if(retained.length+added.length+files.length>3||files.some(f=>!f.size||f.size>2*1024*1024||!(/\.(pdf|docx|xlsx|txt|jpe?g|png)$/i).test(f.name))){error.textContent='请上传受支持的非空文件，最多3个，每个不超过2MB。';error.hidden=false;return;}
  added.push(...files);changed=true;draw();
 });
 $('#submission-file-list').addEventListener('click',e=>{
  if(e.target.dataset.removeRetained!==undefined){retained=retained.filter(f=>String(f.attachment_id)!==e.target.dataset.removeRetained);changed=true;draw();}
  if(e.target.dataset.removeAdded!==undefined){added.splice(Number(e.target.dataset.removeAdded),1);changed=true;draw();}
 });
 draw();
}
