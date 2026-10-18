/* Assignments and results are authorized and persisted by the task API. */
dict.ru.tasks='Задачи';dict.kk.tasks='Тапсырмалар';
let taskTab='active',taskViewVersion=0;
const taskManager=()=>['manager','hr'].includes(user?.role);
const taskLabels={active:'Активные',completed:'Завершённые',overdue:'Просроченные',draft:'Черновик',soon:'Скоро срок'};
const taskSymbols={active:'●',completed:'✓',overdue:'✕',draft:'›'};
const taskAccept='.pdf,.docx,.xlsx,.pptx,.txt,.png,.jpg,.jpeg';
function taskFileLinks(task,kind){return (task.files||[]).filter(f=>f.kind===kind).map(f=>`<a class="btn task-attachment" href="/api/tasks/${task.id}/files/${f.id}" data-document-download data-filename="${esc(f.filename)}">▤ ${esc(f.filename)} · ${sizeLabel(f.size)} ↓</a>`).join('');}
function taskDueSoon(t){const left=new Date(t.deadline)-Date.now();return t.status==='active'&&left>0&&left<=48*3600000;}
function taskRow(t){return `<button class="task-row" data-task-open="${t.id}"><span class="task-mark ${t.status}" aria-label="${esc(taskLabels[t.status])}">${taskSymbols[t.status]}</span><span class="task-row-main"><b>${esc(t.title)}</b><small>${t.assignee_name?'Кому: '+esc(t.assignee_name):'Получатель не выбран'} · От: ${esc(t.author_name)}</small><small>Дедлайн: ${t.deadline?dateTime(t.deadline):'не указан'}${taskDueSoon(t)?' <span class="task-soon">Срок скоро истекает</span>':''}</small></span><span class="task-row-end">${t.status==='draft'?'›':t.status==='completed'?'Выполнено':'Открыть →'}</span></button>`;}
async function renderTasks(){
 const version=++taskViewVersion,token=tabToken,root=contentRoot();
 if(!taskManager()&&taskTab==='draft')taskTab='active';
 if(taskManager()&&taskTab==='soon')taskTab='active';
 root.innerHTML='<p class="muted">Загружаем задачи…</p>';
 try{
  const tasks=await api('/tasks');if(version!==taskViewVersion||token!==tabToken||page!=='tasks'||!root.isConnected)return;
  const tabs=taskManager()?['active','completed','overdue','draft']:['active','soon','completed','overdue'];
  root.innerHTML=`<section class="task-board"><div class="section-title"><h2>${taskManager()?'Задачи':'Мои задачи'}</h2>${taskManager()?'<button class="btn btn-primary" data-new-task>＋ Добавить задачу</button>':''}</div><div class="task-tabs" role="tablist">${tabs.map(k=>`<button role="tab" aria-selected="${taskTab===k}" class="${taskTab===k?'active':''}" data-task-tab="${k}">${taskLabels[k]} <span data-task-count="${k}">0</span></button>`).join('')}</div><div id="taskListHost"></div></section>`;
  const host=$('#taskListHost');const valid=()=>version===taskViewVersion&&token===tabToken&&page==='tasks'&&host.isConnected;
  const paint=list=>{
   for(const k of tabs){const count=k==='soon'?list.filter(taskDueSoon).length:list.filter(t=>t.status===k).length;const el=root.querySelector(`[data-task-count="${k}"]`);if(el)el.textContent=count;}
   const shown=list.filter(t=>taskTab==='soon'?taskDueSoon(t):t.status===taskTab);
   shown.sort((a,b)=>taskTab==='completed'?String(b.completed_at).localeCompare(String(a.completed_at)):taskTab==='draft'?b.id-a.id:new Date(a.deadline)-new Date(b.deadline));
   host.innerHTML=shown.map(taskRow).join('')||'<div class="empty-state">В этом разделе пока нет задач.</div>';
  };
  paint(tasks);let busy=false;
  const timer=setInterval(async()=>{if(!valid()){clearInterval(timer);return;}if(busy)return;busy=true;try{const next=await api('/tasks');if(valid())paint(next);}catch{}finally{busy=false;}},5000);
 }catch(e){if(version===taskViewVersion&&root.isConnected)root.innerHTML=`<p class="form-error">${esc(e.message)}</p>`;}
}
function localDeadline(value){if(!value)return '';const d=new Date(value);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
async function readTaskFile(input){
 const file=input.files?.[0];if(!file)return null;
 if(!file.size||file.size>8*1024*1024)throw Error('Выберите файл размером от 1 байта до 8 МБ');
 const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('Не удалось прочитать файл'));reader.readAsDataURL(file);});
 return {filename:file.name,content};
}
async function taskForm(recipientId=null,draftId=null){
 if(!taskManager())return;
 closeMapTimer();
 const version=++taskViewVersion,token=tabToken;
 const [options,draft]=await Promise.all([api('/tasks/options'),draftId?api('/tasks/'+draftId):null]);
 if(version!==taskViewVersion||token!==tabToken)return;
 if(draft&&!draft.can_edit)throw Error('Этот черновик недоступен для редактирования');
 const selected=draft?.assignee_id??recipientId;
 const recipient=options.recipients.find(p=>p.id===selected);
 if(selected&&!recipient)throw Error('Нельзя назначить задачу этому сотруднику');
 page='tasks';renderNav();
 openDialog(draft?'Редактировать черновик':'Добавить задачу',`<form id="taskEditForm" class="task-form" novalidate>
 <label>Кому отправить<select name="assignee_id"><option value="">Выберите сотрудника</option>${options.recipients.map(p=>`<option value="${p.id}" ${selected===p.id?'selected':''}>${esc(p.name)} · ${esc(p.position)}</option>`).join('')}</select></label>
 <label>Наименование задачи:<input name="title" maxlength="180" value="${esc(draft?.title||'')}" placeholder="Что нужно сделать?"></label>
 <label>Файл:<input type="file" name="attachment" accept="${taskAccept}"><small>PDF, DOCX, XLSX, PPTX, TXT, PNG, JPG · до 8 МБ</small></label>
 ${draft?.files?.some(f=>f.kind==='assignment')?`<div class="task-existing-file">${taskFileLinks(draft,'assignment')}<label class="task-checkbox"><input type="checkbox" name="remove_file"> Удалить текущий файл</label></div>`:''}
 <label>Дедлайн:<input type="datetime-local" name="deadline" value="${localDeadline(draft?.deadline)}"></label>
 <label>Комментарий или описание:<textarea name="description" rows="5" maxlength="5000" placeholder="Опишите ожидаемый результат">${esc(draft?.description||'')}</textarea></label>
 <p id="taskFormError" class="form-error" role="alert"></p><div class="task-form-actions"><button type="submit" name="intent" value="draft" class="btn">${draft?'Сохранить черновик':'Черновик'}</button>${draft?'<button type="button" class="btn" data-task-cancel>Отменить</button>':''}<button type="submit" name="intent" value="send" class="btn btn-primary">Отправить →</button></div></form>`);
 const form=$('#taskEditForm');let saving=false;
 form.addEventListener('submit',async e=>{
  e.preventDefault();if(saving)return;saving=true;
  const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
  try{
   const data=new FormData(form),deadline=data.get('deadline');
   const file=await readTaskFile(form.elements.attachment);
   const body={action:e.submitter?.value||'draft',title:data.get('title'),description:data.get('description'),assignee_id:data.get('assignee_id')?Number(data.get('assignee_id')):null,deadline:deadline?new Date(deadline).toISOString():null,file,remove_file:data.get('remove_file')==='on',...(draft?{version:draft.version}:{})};
   const saved=await api('/tasks'+(draft?'/'+draft.id:''),'POST',body);
   if(token!==tabToken)return;
   taskTab=saved.status==='draft'?'draft':'active';toast(saved.status==='draft'?'Черновик сохранён':'Задача отправлена сотруднику');
   if(form.isConnected){await load();await navigate('tasks');}
  }catch(err){if(form.isConnected)$('#taskFormError').textContent=err.message;}
  finally{saving=false;buttons.forEach(b=>b.disabled=false);}
 });
}
async function taskDetail(id){
 const version=++taskViewVersion,token=tabToken;
 const task=await api('/tasks/'+id);if(version!==taskViewVersion||token!==tabToken)return;
 if(task.status==='draft')return taskForm(null,id);
 page='tasks';renderNav();
 openDialog(task.title,`<section class="task-detail"><div class="task-detail-heading"><span class="task-mark ${task.status}">${taskSymbols[task.status]}</span><b>${taskLabels[task.status]}</b></div><p><b>От:</b> ${esc(task.author_name)} · ${task.author_role==='hr'?'HR / администратор':'Руководитель'}</p><p><b>Кому:</b> ${esc(task.assignee_name)}</p><p><b>Дедлайн:</b> ${dateTime(task.deadline)}</p>${taskDueSoon(task)?'<p class="task-soon">Срок скоро истекает</p>':''}<h3>Описание</h3><p class="task-description">${esc(task.description||'Описание не добавлено')}</p>${taskFileLinks(task,'assignment')}
 ${task.status==='completed'?`<section class="task-result"><h3>✓ Результат отправлен</h3><small>${dateTime(task.completed_at)}</small><p class="task-description">${esc(task.result_text)}</p>${taskFileLinks(task,'result')}</section>`:task.can_submit?`<div id="taskResultArea"><button class="btn btn-primary" data-task-work="${task.id}">Сделать задачу →</button></div>`:'<p class="muted">Ожидаем результат сотрудника.</p>'}
 <div class="task-form-actions"><button class="btn" data-task-cancel>К списку задач</button></div></section>`);
}
function taskResultForm(id){
 const host=$('#taskResultArea');if(!host)return;
 host.innerHTML=`<form id="taskResultForm" class="task-form"><h3>Результат работы</h3><label>Что сделано:<textarea name="result_text" rows="5" maxlength="5000" placeholder="Опишите результат или приложите готовый файл"></textarea></label><label>Файл результата:<input type="file" name="attachment" accept="${taskAccept}"><small>До 8 МБ</small></label><p id="taskResultError" class="form-error" role="alert"></p><div class="task-form-actions"><button type="submit" class="btn btn-primary">Отправить результат →</button></div></form>`;
 const form=$('#taskResultForm'),token=tabToken;let sending=false;
 form.addEventListener('submit',async e=>{e.preventDefault();if(sending)return;sending=true;const button=e.submitter;button.disabled=true;try{const file=await readTaskFile(form.elements.attachment);await api('/tasks/'+id+'/submit','POST',{result_text:form.elements.result_text.value,file});if(token!==tabToken)return;toast('Результат отправлен. Задача завершена');if(form.isConnected){await load();await taskDetail(id);}}catch(err){if(form.isConnected)$('#taskResultError').textContent=err.message;}finally{sending=false;button.disabled=false;}});
 form.elements.result_text.focus();
}
document.addEventListener('click',e=>{
 const b=e.target.closest('button');if(!b)return;
 if(b.hasAttribute('data-new-task'))action(b,()=>taskForm(b.dataset.newTask?Number(b.dataset.newTask):null));
 else if(b.dataset.taskTab){taskTab=b.dataset.taskTab;renderTasks();}
 else if(b.dataset.taskOpen)action(b,()=>taskDetail(Number(b.dataset.taskOpen)));
 else if(b.dataset.taskWork)taskResultForm(Number(b.dataset.taskWork));
 else if(b.hasAttribute('data-task-cancel'))navigate('tasks');
});
