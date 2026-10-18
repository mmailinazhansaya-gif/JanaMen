// Execute scripts separately, as defer script tags do, to catch load-order errors.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();const events={};
function el(id){if(!nodes.has(id))nodes.set(id,{id,hidden:true,value:'',style:{},dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(type,fn){(events[id+':'+type]??=[]).push(fn)},appendChild(){},reset(){},focus(){},setAttribute(){},querySelectorAll(){return []},isConnected:true,innerHTML:''});return nodes.get(id)}
const body=el('body');const document={body,hidden:false,activeElement:null,querySelector:el,querySelectorAll:()=>[],getElementById:id=>el('#'+id),addEventListener:(type,fn)=>(events['document:'+type]??=[]).push(fn)};
const ctx=vm.createContext({document,window:{addEventListener(){}},localStorage:{getItem:()=>null,setItem(){}},performance:{now:()=>0},setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){},requestAnimationFrame:()=>1,cancelAnimationFrame(){},ResizeObserver:class{observe(){}},console,Date});
for(const file of ['app.js','avatars.js','office.js','learning.js','leave.js','live.js','tasks.js'])vm.runInContext(fs.readFileSync(__dirname+'/static/'+file,'utf8'),ctx,{filename:file});
assert.equal(events['#closeDialog:click'].length,1);
el('#dialogBackdrop').hidden=false;el('#dialogBody').innerHTML='open dialog';events['#closeDialog:click'][0]();assert.equal(el('#dialogBackdrop').hidden,true);assert.equal(el('#dialogBody').innerHTML,'');
el('#dialogBackdrop').hidden=false;events['document:keydown'][0]({key:'Escape'});assert.equal(el('#dialogBackdrop').hidden,true);
assert.equal(events['#menuToggle:click'].length,1);events['#menuToggle:click'][0]();
vm.runInContext(`const route=routeBetween('entrance','desk','seat4');if(JSON.stringify(pointAlong(route,0))!==JSON.stringify(OFFICE_POINTS.entrance))throw Error('Wrong entrance');if(JSON.stringify(pointAlong(route,1))!==JSON.stringify(SEATS.seat4))throw Error('Wrong seat');if(JSON.stringify(pointAlong(route,.5))===JSON.stringify(SEATS.seat4))throw Error('No walk');`,ctx);
console.log('PASS: separate script loading, close button, Escape, sidebar toggle and entrance route');

vm.runInContext(`for(let id=1;id<=9;id++){const card=avatarHTML(id);const map=sceneAvatar("teamPerson"+id,"Person",0,"actual-person");if(!map.includes(card))throw Error("Inconsistent map avatar "+id);}if(new Set(Object.values(avatarDefaults)).size!==11)throw Error("Repeated defaults");`,ctx);
vm.runInContext(`
 user={id:1,role:'employee',name:'Алина',learning:{level:2,xp:120}};
 const scene=officeScene();
 for(const n of NPCS){if(!scene.includes('id="selfNpc'+n.personId+'"'))throw Error('NPC ID mismatch');const end=pointAlong(routeBetween('lounge','desk',n.seat),1);if(JSON.stringify(end)!==JSON.stringify(SEATS[n.seat]))throw Error('Wrong NPC seat');}
 lang='kk';if(mapText('КУХНЯ')!=='АСҮЙ')throw Error('Kitchen translation');if(mapText('ВАШЕ МЕСТО')!=='СІЗДІҢ ОРНЫҢЫЗ')throw Error('Seat translation');lang='ru';if(mapText('КУХНЯ')!=='КУХНЯ')throw Error('Russian restoration');
 renderNav();
 `,ctx);
assert(!el('#mainNav').innerHTML.includes('data-page="notifications"'));
assert(!el('#mainNav').innerHTML.includes('data-page="requests"'));
assert(el('#mainNav').innerHTML.includes('data-page="services"'));
console.log('PASS: map language, stable employee identifiers, return to assigned seats and unified navigation');
vm.runInContext(`page='services';requests=[];renderServices();`,ctx);
assert(el('#serviceContent').innerHTML.includes('Мои заявки'));
assert(el('#serviceContent').innerHTML.includes('Оформить отпуск'));
console.log('PASS: HR services and request history render together');

vm.runInContext(`chatHistory=[{who:'bot',text:'Ваши заявки',sources:[{id:'requests',page:'services',title:'Мои заявки'}]},{who:'bot',text:'Нет надежного ответа <script>',sources:[],escalation:{id:3,name:'Аружан'}},{who:'bot',text:'Инструкция',sources:[{id:7,title:'Документы'}]}];renderMessages();`,ctx);
assert(el('#messages').innerHTML.includes('data-page="services"'));
assert(el('#messages').innerHTML.includes('data-source="7"'));
assert(el('#messages').innerHTML.includes('data-open-chat="3"'));
assert(!el('#messages').innerHTML.includes('<script>'));
console.log('PASS: assistant source navigation, HR escalation and escaped answer text');

(async()=>{
 await vm.runInContext(`(async()=>{
  page='academy';user={id:1,role:'employee',learning:{level:2,xp:200,badges:[]}};
  courses=[{id:3,title:'Клиентский сервис',description:'Практический урок',duration:'5:45',assigned:true,video:true,progress:0}];
  api=async path=>path==='/academy/options'?{people:[{id:1,name:'Алина',position:'Специалист',department:'Сервис'}],courses:[{id:3,title:'Клиентский сервис'}]}:[{id:7,title:'Помощь Алине',description:'Инструкция',author:'HR',kind:'folder',recipients:[{id:1,read_at:null}],files:[{id:1,filename:'instruction.pdf'}]}];
  await renderAcademy();
  if(!contentRoot().innerHTML.includes('Персональные материалы'))throw Error('Missing personal folder');
  if(contentRoot().innerHTML.includes('Управление обучением'))throw Error('Employee sees HR tab');
  user.role='hr';academyTab='manage';await renderAcademy();
  if(!contentRoot().innerHTML.includes('Управление обучением')||!contentRoot().innerHTML.includes('Назначить обучение'))throw Error('Missing HR academy management');
  if(!contentRoot().innerHTML.includes('Помощь Алине'))throw Error('Missing assignment list');
 })()`,ctx);
 console.log('PASS: role-aware Academy tabs, personal folders and HR assignment list');
 await vm.runInContext(`(async()=>{
  user={id:1,role:'employee'};page='messages';
  globalThis.sentMessages=[];
  api=async(path,method,body)=>{
   if(path==='/messages/contacts')return [{id:3,name:'Аружан',position:'HR'},{id:5,name:'Арман',position:'Поддержка'}];
   if(path==='/messages'&&method==='POST'){sentMessages.push(body);return {ok:true};}
   return [];
  };
  refreshMessageIndicators=async()=>{};
  await renderMessenger(3);
 })()`,ctx);
 assert(el('#serviceContent').innerHTML.includes('<textarea id="messageInput"'));
 assert(el('#serviceContent').innerHTML.includes('Сообщение для Аружан'));
 el('#messageInput').value='Черновик для HR';
 events['#messageInput:input'].at(-1)();
 await vm.runInContext('renderMessenger(5)',ctx);
 assert.equal(el('#messageInput').value,'');
 el('#messageInput').value='Помоги с обращением';
 events['#messageInput:input'].at(-1)();
 await vm.runInContext('renderMessenger(3)',ctx);
 assert.equal(el('#messageInput').value,'Черновик для HR');
 await events['#messageForm:submit'].at(-1)({preventDefault(){},submitter:el('#sendMessage')});
 assert.equal(vm.runInContext('sentMessages.length',ctx),1);
 assert.equal(vm.runInContext('sentMessages[0].recipient_id',ctx),3);
 assert.equal(vm.runInContext('sentMessages[0].body',ctx),'Черновик для HR');
 assert.equal(el('#messageInput').value,'');
 await vm.runInContext('renderMessenger(5)',ctx);
 assert.equal(el('#messageInput').value,'Помоги с обращением');
 let submitted=0;el('#messageForm').requestSubmit=button=>{assert.equal(button,el('#sendMessage'));submitted++;};
 const keyHandler=events['#messageInput:keydown'].at(-1);
 keyHandler({key:'Enter',shiftKey:true,preventDefault(){throw Error('Shift+Enter should add a newline');}});
 keyHandler({key:'Enter',shiftKey:false,isComposing:true,preventDefault(){throw Error('IME composition should not send');}});
 keyHandler({key:'Enter',shiftKey:false,isComposing:false,preventDefault(){}});
 assert.equal(submitted,1);
 console.log('PASS: message composer sends to selected colleague, preserves separate drafts and supports Enter/Shift+Enter');
 await vm.runInContext(`(async()=>{
  const requests=[];api=async(path,method,body)=>{requests.push({path,body});return {mode:'work',changed_at:1,server_time:Date.now()/1000};};
  user={id:1};tabToken='idle-test-alina';welcomeActive=false;officeBusy=true;
  officePresence={mode:'work',changed_at:0};
  noteHumanInput({isTrusted:false});if(inputToken==='idle-test-alina')throw Error('Synthetic event counted');
  noteHumanInput({isTrusted:true});officeBusy=false;await flushHumanInput();
  if(requests.length!==1||requests[0].path!=='/activity')throw Error('Human input not sent');
  await flushHumanInput();if(requests.length!==1)throw Error('Polling counted as input');
  user={id:2};tabToken='idle-test-manager';await flushHumanInput();
  if(requests.length!==1)throw Error('Input leaked across accounts');
  officePresence={mode:'off'};noteHumanInput({isTrusted:true});await flushHumanInput();
  if(requests.length!==1)throw Error('Finished shift restarted');
  const timer=personStatusMarkup({mode:'break',location:'lounge',current_seconds:125,work_seconds:3600,break_seconds:125},1);
  if(!timer.includes('00:02:06')||!timer.includes('На перерыве'))throw Error('Current break duration missing');
 })()`,ctx);
 console.log('PASS: trusted activity, account isolation, ended shifts and current break duration');
 await vm.runInContext(`(async()=>{
  const oldTimer=showMapTimer,oldDetail=personDetail,calls=[];
  showMapTimer=async(el,id)=>calls.push('timer:'+id);personDetail=async id=>calls.push('profile:'+id);
  const avatar={dataset:{person:'1'},classList:{contains:c=>c==='office-person'}};
  user={id:2,role:'manager'};await openMapPerson(avatar);
  user={id:3,role:'hr'};await openMapPerson(avatar);
  user={id:4,role:'employee'};await openMapPerson(avatar);
  user={id:2,role:'manager'};await openMapPerson({dataset:{person:'1'},classList:{contains:()=>false}});
  if(calls.join(',')!=='timer:1,timer:1,profile:1,profile:1')throw Error('Wrong role or map click routing');
  showMapTimer=oldTimer;personDetail=oldDetail;lang='ru';
  if(mapTimerText({mode:'work',current_seconds:65},1).time!=='00:01:06')throw Error('Work timer');
  if(mapTimerText({mode:'break',auto_break:true,current_seconds:125},1).label!=='На перерыве · нет активности')throw Error('Idle label');
  if(mapTimerText({mode:'off',current_seconds:125},9).time!=='—')throw Error('Ended shift timer');
 })()`,ctx);
 console.log('PASS: map click opens supervisor timer, employee opens profile, timer labels match status');
 await vm.runInContext(`(async()=>{
  user={id:3,role:'hr'};tabToken='task-ui';page='tasks';
  globalThis.taskCalls=[];
  globalThis.FormData=class{constructor(form){this.values=form.values;}get(key){return this.values[key]??null;}};
  api=async(path,method,body)=>{
   if(path==='/tasks/options')return {recipients:[{id:1,name:'Алина',position:'Специалист'},{id:5,name:'Арман',position:'Поддержка'}]};
   if(path==='/tasks/99'&&!method)return {id:99,assignee_id:1,title:'Черновик',description:'Описание',deadline:'2027-01-01T10:00:00Z',files:[],version:7,can_edit:true};
   taskCalls.push({path,method,body});return {id:99,status:body.action==='draft'?'draft':'active'};
  };
  load=async()=>{};navigate=async()=>{};
  await taskForm(1);
 })()`,ctx);
 const taskHTML=el('#dialogBody').innerHTML;
 for(const label of ['Кому отправить','Наименование задачи:','Файл:','Дедлайн:','Комментарий или описание:','Черновик','Отправить'])assert(taskHTML.includes(label),label);
 assert(taskHTML.indexOf('Наименование задачи:')<taskHTML.indexOf('Файл:'));
 assert(taskHTML.indexOf('Файл:')<taskHTML.indexOf('Дедлайн:'));
 const taskFormEl=el('#taskEditForm');taskFormEl.elements={attachment:{files:[]}};
 taskFormEl.values={title:'Новая задача',description:'Описание',assignee_id:'1',deadline:'2027-01-01T10:00'};
 await events['#taskEditForm:submit'].at(-1)({preventDefault(){},submitter:{value:'draft'}});
 assert.equal(vm.runInContext('taskCalls[0].body.action',ctx),'draft');
 assert.equal(vm.runInContext('taskCalls[0].body.assignee_id',ctx),1);
 await vm.runInContext('taskForm(null,99)',ctx);
 assert(el('#dialogBody').innerHTML.includes('Отменить'));
 taskFormEl.values={title:'Изменённая задача',description:'Новое описание',assignee_id:'5',deadline:'2027-01-02T10:00'};
 await events['#taskEditForm:submit'].at(-1)({preventDefault(){},submitter:{value:'send'}});
 assert.equal(vm.runInContext('taskCalls[1].path',ctx),'/tasks/99');
 assert.equal(vm.runInContext('taskCalls[1].body.version',ctx),7);
 assert.equal(vm.runInContext('taskCalls[1].body.assignee_id',ctx),5);
 await vm.runInContext(`user={id:1,role:'employee'};renderNav();`,ctx);
 assert(el('#mainNav').innerHTML.includes('Мои задачи'));
 assert(el('#mainNav').innerHTML.indexOf('data-page="services"')<el('#mainNav').innerHTML.indexOf('data-page="tasks"'));
 assert(el('#mainNav').innerHTML.indexOf('data-page="tasks"')<el('#mainNav').innerHTML.indexOf('data-page="academy"'));
 console.log('PASS: task form fields, editable recipient/draft, publish payload and employee navigation');
})().catch(error=>{console.error(error);process.exitCode=1;});

// Guard against the old map style swallowing avatar clicks before JS receives them.
const avatarRules=[...fs.readFileSync(__dirname+'/static/app.css','utf8').replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/([^{}]+)\{([^{}]+)\}/g)].filter(m=>m[1].trim()==='.office-person[data-person]');
assert(avatarRules.at(-1)[2].includes('pointer-events:auto'));
console.log('PASS: main-map avatars accept pointer clicks');
