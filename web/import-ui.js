'use strict';
// 业务管理下的 Excel 导入：二级（整业务）与三级（本班次／本小组）共用一套弹窗骨架。
// 正常行不渲染，只列需要处理的行；学号是唯一身份依据。

function importScopeInfo(kind, id){
  if(kind === 'SLOT'){
    const slot = (state.data.slots||[]).find(s => String(s.slot_id) === String(id));
    const business = (state.data.businesses||[]).find(b => b.business_id === (slot && slot.business_id));
    return {kind:'SLOT', id:Number(id), businessId:slot?slot.business_id:null, business,
      label:(business?business.name:'业务') + ' · ' + (slot?slot.team_name:'本班次')};
  }
  if(kind === 'GROUP'){
    const group = (state.data.groups||[]).find(g => String(g.group_id) === String(id));
    const business = (state.data.businesses||[]).find(b => b.business_id === (group && group.business_id));
    return {kind:'GROUP', id:Number(id), businessId:group?group.business_id:null, group, business,
      label:(business?business.name:'业务') + ' · ' + (group?group.name:'小组')};
  }
  const business = (state.data.businesses||[]).find(b => b.business_id === Number(id));
  return {kind:'BUSINESS', id:Number(id), businessId:Number(id), business,
    label:business?business.name:'业务'};
}

const IMPORT_ISSUE_LABEL = {
  name:'姓名不一致', reactivate:'已退队', credit:'信用停用', dupname:'同号不同名',
  slot:'时段冲突', formula:'公式无文本值', group:'未选择小组',
};
function importIssueLabel(issue){
  return IMPORT_ISSUE_LABEL[issue] || '需要确认';
}

function openImportDialog(kind, id){
  const scope = importScopeInfo(kind, id);
  if(!scope.businessId){ notify('该业务信息已变化，请刷新页面。', true); return; }
  if(modalBusy) return;
  if(dialog.open) closeDialog(true);
  const fixed = scope.kind === 'SLOT' || scope.business.kind === 'FIXED';
  previousFocus = document.activeElement; modalSubmit = null; modalVersion++;
  const version = modalVersion, session = state.sessionVersion;
  let encoded = '', preview = null, approvals = {}, mappings = {};
  const activeBusiness = scope.businessId;

  const targetNote = scope.kind === 'SLOT'
    ? `本次只导入到 ${scope.label}：表中「分类／时段」列不参与识别。`
    : scope.kind === 'GROUP'
      ? `本次只导入到 ${scope.label}：每张工作表都写入该小组。`
      : fixed
        ? '导入整个业务：按「分类／时段」列识别时段，识别不到的只建账号。'
        : '导入整个业务：按工作表选择去向，业务已分组时必须选小组。';

  dialog.innerHTML = `<header class="dialog-header"><div><h2 id="dialog-title">Excel 导入</h2>
      <p id="import-target">${esc(scope.label)} · 表头须含「姓名」「学号」，学院可选</p></div><button type="button" class="close-button" data-action="close">关闭</button></header>
    <div class="dialog-body"><form id="import-form" novalidate class="import-form">
      <div class="form-grid">
        <div class="field full"><label for="import-file">名单文件</label>
          <input id="import-file" type="file" accept=".xlsx">
          <small class="field-help">${esc(targetNote)}</small></div>
      </div>
      <div id="import-stats" class="import-stats" hidden></div>
      <div id="import-report" class="import-report"></div>
      <div class="form-grid" id="import-password-field" hidden>
        ${field('import-password','新账号初始密码',{type:'password',full:true,minLength:8,maxLength:128,required:false,
          help:'只用于本次新建的账号；已有账号的密码、资料与信用记录保持原样。'})}
      </div>
      <div class="notice error" id="import-error" role="alert" hidden></div>
      <footer class="dialog-footer">
        <button type="button" class="btn" data-action="close">取消</button>
        <button type="button" class="btn" id="import-preview">读取并预览</button>
        <button type="button" class="btn primary" id="import-commit" disabled>确认导入</button>
      </footer>
    </form></div>`;
  dialog.classList.add('import-dialog');
  dialog.addEventListener('close', () => dialog.classList.remove('import-dialog'), {once:true});
  dialog.showModal();

  const current = () => version === modalVersion && session === state.sessionVersion && dialog.open;

  function payload(commit){
    const password = $('#f-import-password').value;
    const base = {file_base64:encoded, commit, initial_password:commit?password:null, approvals};
    if(fixed){
      return {...base, business_id:activeBusiness, slot_id:scope.kind === 'SLOT'?scope.id:null, map_categories:true};
    }
    return {...base, mappings, decisions:{}, scope:{business_id:activeBusiness, group_id:scope.kind === 'GROUP'?scope.id:null}};
  }

  function renderReport(){
    if(!preview) return;
    const stats = preview.stats || {};
    const cards = [['识别人数', stats.students || 0], ['新建账号', stats.new_accounts || 0],
      ['已有账号', stats.existing || 0], ['待确认', stats.pending || 0], ['已跳过', stats.skipped || 0]];
    $('#import-stats').hidden = false;
    $('#import-stats').innerHTML = cards.map(([n, v]) => `<div class="import-stat"><strong>${v}</strong><span>${n}</span></div>`).join('');
    const errors = (preview.errors || []).map(e => `<li>${esc(e.message)}</li>`);
    const skipped = (preview.credits || []).map(c => `<li>${esc(c.name || '')}（${esc(c.student_id)}）${esc(c.message)}</li>`)
      .concat((preview.skipped || []).map(s => `<li>${esc(s.message)}</li>`));
    const sheets = (preview.sheets || []).map(s => s.name || s);
    const sheetRows = (scope.kind === 'BUSINESS' && !fixed)
      ? `<div class="import-sheet-map"><div class="import-sheet-map-head">工作表去向：已按表名自动匹配，可改为其他小组或本表不导入</div>${sheets.map(name => `<label>${esc(name)}
          <select data-sheet-map="${esc(name)}">${[['','本表不导入'],
            ...(state.data.groups||[]).filter(g => g.business_id === activeBusiness).map(g => [`${activeBusiness}:${g.group_id}`, g.name])]
            .map(([v, n]) => `<option value="${v}" ${v === sheetValue(preview, name)?'selected':''}>${esc(n)}</option>`).join('')}</select></label>`).join('')}</div>`
      : '';
    const pending = preview.pending || [];
    const rows = pending.map(p => `<tr>
        <td>${esc((p.sheets||[]).join('、'))}${p.rows && p.rows.length ? `<small>第 ${p.rows.join('、')} 行</small>` : ''}</td>
        <td><strong>${esc(p.name || '')}</strong><small>${esc(p.student_id)}</small></td>
        <td class="wrap">${esc(importIssueLabel(p.issue))}<small>${esc(p.detail || '')}</small><small>${esc(p.target || '')}</small></td>
        <td><label class="switch"><input type="checkbox" data-approve="${esc(p.student_id)}" ${approvals[p.student_id]?'checked':''}><span>按导入</span></label></td>
      </tr>`);
    $('#import-report').innerHTML = (errors.length ? `<div class="notice error"><ul>${errors.join('')}</ul></div>` : '')
      + sheetRows
      + (pending.length
        ? `<div class="import-pending-head"><strong>待确认 ${pending.length} 行</strong><button type="button" class="text-button" id="import-approve-all">全部改为导入</button></div>
           ${table(['来源','姓名 / 学号','问题','处理'], rows)}`
        : '<p class="muted">没有需要确认的行。</p>')
      + (skipped.length
        ? `<details class="import-skipped"><summary>已跳过 ${skipped.length} 行</summary><ul>${skipped.join('')}</ul></details>`
        : '');
    const passwordNeeded = (stats.new_accounts || 0) > 0;
    const passwordInput = $('#f-import-password');
    $('#import-password-field').hidden = !passwordNeeded;
    passwordInput.required = passwordNeeded;
    $('#import-commit').disabled = errors.length > 0;
    $('#import-approve-all')?.addEventListener('click', () => {
      pending.forEach(p => { approvals[p.student_id] = true; });
      renderReport();
    });
    $('#import-report').querySelectorAll('[data-approve]').forEach(input => {
      input.addEventListener('change', () => { approvals[input.dataset.approve] = input.checked; });
    });
    $('#import-report').querySelectorAll('[data-sheet-map]').forEach(select => {
      select.addEventListener('change', async () => {
        const value = select.value;
        mappings[select.dataset.sheetMap] = value
          ? {business_id:Number(value.split(':')[0]), group_id:Number(value.split(':')[1])} : null;
        preview = null;
        await run(false);
      });
    });
  }

  function sheetValue(payload, name){
    const sheet = (payload.sheets || []).find(s => (s.name || s) === name);
    const target = sheet && sheet.target;
    return target ? `${target.business_id}:${target.group_id || ''}` : '';
  }

  async function run(commit){
    if(modalBusy) return;
    const errorEl = $('#import-error'); errorEl.hidden = true;
    const controls = [...dialog.querySelectorAll('input,select,button')];
    try{
      const file = $('#import-file').files[0];
      if(!file || !file.name.toLowerCase().endsWith('.xlsx') || file.size > 8*1024*1024) throw new Error('请选择不超过 8 MB 的 .xlsx 文件。');
      if(!encoded) encoded = await fileBase64(file);
      if(commit){
        if(!preview || (preview.errors || []).length) throw new Error('请先完成没有错误提示的预览。');
        if((preview.stats.new_accounts || 0) > 0){
          const password = $('#f-import-password').value;
          if(password.length < 8 || password.length > 128) throw new Error('新账号初始密码需要 8 至 128 个字符。');
        }
      }
      setModalBusy(true); controls.forEach(c => { c.disabled = true; });
      $('#import-report').innerHTML = commit ? '<p class="muted">正在写入账号与归属，请保持页面打开…</p>'
        : '<p class="muted">正在读取工作簿…</p>';
      let result = await send(fixed ? '/students/import' : '/member-imports', payload(commit));
      if(!current()) return;
      if(commit){
        setModalBusy(false); closeDialog(); await refresh();
        notify(`导入完成：新增账号 ${result.new_students || 0} 个，新增归属 ${result.added_memberships !== undefined ? result.added_memberships : result.imported || 0} 条。`);
        return;
      }
      // 三级小组：先把每张工作表都锁定到当前小组，再出正式预览。
      if(scope.kind === 'GROUP' && !Object.keys(mappings).length && (result.sheets || []).length){
        (result.sheets || []).forEach(s => { mappings[s.name || s] = {business_id:activeBusiness, group_id:scope.id}; });
        result = await send('/member-imports', payload(false));
        if(!current()) return;
      }
      preview = result;
      renderReport();
    }catch(e){ if(current()){ errorEl.textContent = e.message; errorEl.hidden = false; } }
    finally{ if(current()){ setModalBusy(false); controls.forEach(c => { c.disabled = false; }); } }
  }

  $('#import-preview').addEventListener('click', () => run(false));
  $('#import-commit').addEventListener('click', () => run(true));
  $('#import-file').addEventListener('change', () => {
    encoded = ''; preview = null; approvals = {}; mappings = {};
    $('#import-report').innerHTML = ''; $('#import-stats').hidden = true; $('#import-commit').disabled = true;
  });
}

let importRecordsBusiness = null;

async function openImportRecords(businessId){
  importRecordsBusiness = businessId;
  const version = modalVersion, session = state.sessionVersion;
  let data;
  try{
    data = await request('/member-imports?business_id=' + encodeURIComponent(businessId));
  }catch(e){ notify(e.message, true); return; }
  if(version !== modalVersion || session !== state.sessionVersion) return;
  const rows = (data.batches || []).map(b => `<tr>
      <td>${fmtDate(b.created_at)}</td>
      <td class="wrap">${esc(b.scope_kind === 'SLOT' ? '本班次' : b.scope_kind === 'GROUP' ? '本小组' : '整业务')}<small>${esc(b.sheet_names || '')}</small></td>
      <td>${b.imported_count || 0}</td>
      <td>${b.skipped_count || 0}</td>
      <td>${esc(b.admin_name || '')}</td>
      <td>${b.reverted_at ? '<span class="muted">已撤销</span>' : badge('ACTIVE','有效')}</td>
      <td>${b.reverted_at ? '' : `<button class="text-button" data-action="revert-import" data-id="${b.batch_id}">撤销本批次</button>`}</td>
    </tr>`);
  openReadOnlyDialog('导入记录', table(['导入时间','范围','导入','跳过','操作人','状态','操作'], rows,
    '暂无导入记录', '业务导入后会记在这里。'), '只显示最近 30 个批次；撤销后本次新建的账号、归属会撤回，被移除的冲突时段自动加回。');
}

function revertImport(batchId){
  openDialog('撤销这次导入', '本次新建且没有其他归属的账号会被删除，业务与小组归属撤回，被移除的冲突时段自动加回。只支持最近 7 天。',
    reasonField(), v => send(`/member-imports/${batchId}/revert`, {reason:v.reason}).then(result => {
      setTimeout(() => openImportRecords(importRecordsBusiness), 80);
      return result;
    }), '确认撤销');
}
