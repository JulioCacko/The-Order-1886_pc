import './style.css';

type Choice = {value:string|number; label:string; available:boolean; reason:string};
type Field = {key:string;label:string;page:string;kind:string;default:unknown;description:string;
  available:boolean;reason:string;minimum?:number;maximum?:number;choices?:Choice[]};
type Snapshot = {trophies:{id:number;unlocked_at:number}[];trophy_error:string;settings:Record<string,any>;fields:Field[];pages:{id:string;title:string}[];
  languages:Record<string,string>;translations:Record<string,string>;game:{ready:boolean;message:string;metadata:Record<string,unknown>};
  busy:boolean;backups:string[];logs:string[];logfile:string;state_dir:string;last_exit:number|null;acceptance:string};
type AppBridge = {Call:(method:string,params:Record<string,unknown>)=>Promise<string>;
  Browse:(kind:string)=>Promise<string>;OpenLink:(name:string)=>Promise<void>;
  StartupError:()=>Promise<string>;ConfirmClose:()=>Promise<void>;OpenLocation:(kind:string)=>Promise<void>};
declare global { interface Window {
  go?:{main:{App:AppBridge}};
  runtime?:{EventsOn:(name:string,callback:(event:any)=>void)=>void};
}}
let snapshot:Snapshot;
let page = 'home';
let query = '';
let selectedBackup = '';
let notice = '';
let saving = false;
let confirmation:((value:boolean)=>void)|null = null;
const root = document.querySelector<HTMLDivElement>('#app')!;
const escape = (value:unknown) => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const t = (value:string) => snapshot?.translations[value] ?? value;
const bridge = () => {
  if (!window.go?.main.App) throw new Error('The desktop worker bridge is unavailable. Open the installed launcher.');
  return window.go.main.App;
};
const paths:Record<string,string> = {
  home:'M3 11 12 3l9 8M5 10v11h5v-7h4v7h5V10',
  graphics:'M3 4h18v13H3zM8 21h8m-4-4v4',
  performance:'M3 12h4l3-8 4 16 3-8h4',
  controls:'M7 8h10a5 5 0 0 1 5 5v4a3 3 0 0 1-5 2l-2-2H9l-2 2a3 3 0 0 1-5-2v-4a5 5 0 0 1 5-5zM7 11v5m-2-2h4m7-1h.01m3 3h.01',
  game:'M3 6h7l2 2h9v12H3zM3 6V4h7l2 2',
  achievements:'M8 3h8v7a4 4 0 0 1-8 0zM8 5H4v3a4 4 0 0 0 4 4m8-7h4v3a4 4 0 0 1-4 4m-4 2v7m-4 0h8',
  system:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',
  search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
};
const icon=(name:string)=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]??paths.system}"/></svg>`;
async function call<T=any>(method:string,params:Record<string,unknown>={}):Promise<T> {
  return JSON.parse(await bridge().Call(method,params));
}
function flash(message:string,error=false) {
  notice=message;
  const status=document.querySelector<HTMLElement>('#feedback');
  if(status){status.textContent=message;status.classList.toggle('error',error);}
}
function confirmAction(title:string,detail:string,action='Confirm'):Promise<boolean> {
  const dialog=document.querySelector<HTMLDialogElement>('#confirm')!;
  dialog.querySelector('#confirm-title')!.textContent=title;
  dialog.querySelector('#confirm-detail')!.textContent=detail;
  dialog.querySelector('#confirm-yes')!.textContent=action;
  dialog.showModal();
  return new Promise(resolve=>confirmation=resolve);
}
function finishConfirmation(value:boolean) {
  document.querySelector<HTMLDialogElement>('#confirm')?.close();
  confirmation?.(value); confirmation=null;
}
function control(field:Field) {
  const value=snapshot.settings[field.key]??field.default;
  const disabled=!field.available||snapshot.busy?' disabled':'';
  const label=`id="field-${field.key}" data-setting="${field.key}" aria-describedby="help-${field.key}"`;
  if(field.kind==='boolean') return `<input type="checkbox" ${label}${disabled}${value?' checked':''}>`;
  if(field.kind==='select') return `<select ${label}${disabled}>${field.choices!.map(choice=>
    `<option value="${escape(String(choice.value))}"${value===choice.value?' selected':''}${!choice.available?' disabled':''}>${escape(t(choice.label))}${!choice.available?' — '+escape(t('Unavailable')):''}</option>`).join('')}</select>`;
  if(field.kind==='order') return `<textarea ${label}${disabled} rows="3" spellcheck="false">${escape((value as string[]).join('\n'))}</textarea>`;
  if(field.kind==='number') return `<input type="number" ${label}${disabled} value="${escape(value)}" min="${field.minimum}" max="${field.maximum}" step="1">`;
  return `<div class="path-input"><input type="text" ${label}${disabled} value="${escape(value)}" autocomplete="off" spellcheck="false">${['directory','file'].includes(field.kind)?`<button data-browse="${field.key}"${disabled} aria-label="${escape(t('Browse')+' '+t(field.label))}">${escape(t('Browse'))}</button>`:''}</div>`;
}
function fieldRow(field:Field) {
 const unavailable=field.choices?.filter(c=>!c.available)??[];
 return `<div class="setting-row ${!field.available?'unavailable':''}" data-field-row="${field.key}">
  <div class="setting-copy"><label for="field-${field.key}">${escape(t(field.label))}</label>
  <p id="help-${field.key}">${escape(t(field.description))}</p>
  ${field.reason?`<p class="availability">${escape(t(field.reason))}</p>`:''}
  ${unavailable.length?`<details class="availability"><summary>${escape(t('Additional modes'))}</summary><ul>${unavailable.map(c=>`<li><strong>${escape(t(c.label))}</strong>: ${escape(t(c.reason))}</li>`).join('')}</ul></details>`:''}</div>
  <div class="setting-control">${control(field)}</div></div>`;
}
function actionButton(action:string,title:string,destructive=false) {
 return `<button data-action="${action}" class="${destructive?'danger':''}"${snapshot.busy?' disabled':''}>${escape(t(title))}</button>`;
}
function gameActions() {
 return `<section class="utility-section"><h2>${escape(t('Save backups'))}</h2>
 <p>${escape(t('Use current saves, or choose a complete backup to restore before Play. Current saves are backed up before replacement.'))}</p>
 <label for="backup">${escape(t('Selected backup'))}</label><select id="backup"${snapshot.busy?' disabled':''}>
 <option value="">${escape(t('Use current saves'))}</option>${snapshot.backups.map(name=>`<option${selectedBackup===name?' selected':''}>${escape(name)}</option>`).join('')}</select>
 <p id="backup-detail">${escape(selectedBackup?t('Play will ask to restore the selected backup first.'):t('Play uses the current save data.'))}</p>
 <div class="actions">${actionButton('saves.backup','Back up saves now')}${actionButton('saves.restore','Restore selected backup',true)}</div></section>`;
}
function systemActions() {
 return `<section class="utility-section"><h2>${escape(t('Installation tools'))}</h2>
 <div class="actions">${actionButton('verify','Verify files')}${actionButton('prepare','Prepare game')}${actionButton('cache.clear','Clear shader cache',true)}
 ${actionButton('shortcut.create','Create desktop shortcut')}${actionButton('steam.add','Add to Steam')}</div>
 <h2>${escape(t('Updates and support'))}</h2><p>${escape(t('Manual release downloads are available. Automatic installation and rollback are not yet qualified.'))}</p>
 <div class="actions"><button data-link="releases">${escape(t('View releases'))}</button><button data-link="issues">${escape(t('Report an issue'))}</button></div>
 <div class="actions"><button data-location="installation">${escape(t('Open installation'))}</button><button data-location="state">${escape(t('Open player data'))}</button><button data-location="logs">${escape(t('Open logs'))}</button></div>
 <dl class="locations"><dt>${escape(t('Player data'))}</dt><dd>${escape(snapshot.state_dir)}</dd><dt>${escape(t('Session log'))}</dt><dd>${escape(snapshot.logfile||t('No session yet'))}</dd></dl>
 <details><summary>${escape(t('Session output'))}</summary><pre id="session-output" tabindex="0">${escape(snapshot.logs.join('')||t('No session output yet.'))}</pre></details></section>`;
}
function home() {
 const values=snapshot.settings;
 return `<section class="hero" aria-labelledby="home-title"><div class="hero-content">
 <img class="hero-logo" src="/assets/logo-horizontal.png" alt="The Order: 1886">
 <h1 id="home-title">${escape(t('Return to Whitechapel'))}</h1>
 <p>${escape(t('Your game. Your settings. Ready when you are.'))}</p>
 <button class="hero-play" data-action="play"${saving?' disabled':''}>${snapshot.busy?escape(t('Stop')):`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7z"/></svg>${escape(t('Play'))}`}</button>
 <button class="quiet hero-settings" data-page="graphics">${escape(t('Configure graphics'))}</button></div></section>
 <section class="home-bottom" aria-label="${escape(t('Launch configuration'))}">
 <div><h2>${escape(t('Launch configuration'))}</h2><dl class="configuration">
 <div><dt>${escape(t('Display'))}</dt><dd>${escape(values.display_mode)}</dd></div>
 <div><dt>${escape(t('Upscaling'))}</dt><dd>${escape(values.presentation_filter==='fsr1'?'FSR 1':values.presentation_filter)}</dd></div>
 <div><dt>${escape(t('Game frame rate'))}</dt><dd>${escape(values.frame_rate)} FPS</dd></div>
 <div><dt>${escape(t('Framing'))}</dt><dd>${escape(values.aspect_ratio)}</dd></div></dl>
 <p class="quiet-copy">${escape(t('Configured values; measured performance is recorded separately.'))}</p></div>
 <div class="installation"><h2>${escape(t('Game installation'))}</h2>
 <p class="readiness ${snapshot.game.ready?'ready':''}">${escape(t(snapshot.game.ready?'Game files found':'Setup required'))}</p>
 <p class="truncate" title="${escape(values.game_dir)}">${escape(values.game_dir||t('Choose your extracted game folder'))}</p>
 <p class="quiet-copy">${snapshot.game.ready?`APP_VER ${escape(snapshot.game.metadata.APP_VER)} · VERSION ${escape(snapshot.game.metadata.VERSION)}`:escape(snapshot.game.message)}</p>
 <button class="quiet" data-page="game">${escape(t('Manage game and saves'))}</button></div></section>`;
}
function settingsPage() {
 const matching=snapshot.fields.filter(field=>query?
  `${field.label} ${field.description} ${field.reason} ${field.choices?.map(c=>c.label).join(' ')}`.toLowerCase().includes(query.toLowerCase()):
  field.page===page);
 if(page==='achievements'&&!query) return `<section class="settings-page"><h1>${escape(t('Achievements'))}</h1><p class="quiet-copy">${escape(t('Live local trophy IDs and first-unlock times. Official names and artwork are not yet available.'))}</p>
 ${snapshot.trophy_error?`<p role="alert" class="error">${escape(snapshot.trophy_error)}</p>`:snapshot.trophies.length?`<ol class="trophy-list">${snapshot.trophies.map(item=>`<li><strong>${escape(t('Trophy'))} ${item.id}</strong><time>${escape(String(item.unlocked_at))} ${escape(t('UTC epoch seconds'))}</time></li>`).join('')}</ol>`:`<p class="empty-state">${escape(t('No earned trophies recorded yet. Unlocks appear here when the game writes them.'))}</p>`}</section>`;
 return `<section class="settings-page"><div class="section-heading"><div><h1>${escape(query?t('Search settings'):t(snapshot.pages.find(p=>p.id===page)!.title))}</h1>
 <p>${escape(query?`${matching.length} ${t('matching options')}`:t('Valid changes save automatically. Game settings take effect on the next launch.'))}</p></div>
 ${!query&&matching.some(f=>f.available)?`<button class="quiet" data-action="reset"${snapshot.busy?' disabled':''}>${escape(t('Reset section'))}</button>`:''}</div>
 ${matching.length?matching.map(fieldRow).join(''):`<p class="empty-state">${escape(t('No matching settings. Try a different search.'))}</p>`}
 ${page==='game'&&!query?gameActions():''}${page==='system'&&!query?systemActions():''}</section>`;
}
function render() {
 if(!snapshot) return;
 const focused=document.activeElement as HTMLInputElement|null;
 const focusKey=focused?.dataset.setting;
 const selection=focused&&['text','search'].includes(focused.type)?[focused.selectionStart,focused.selectionEnd]:null;
 const locale=snapshot.settings.ui_language??'en';
 document.documentElement.lang=locale==='pt'?'pt-BR':locale;
 document.documentElement.dir=locale==='ar'?'rtl':'ltr';
 const pageTitle=snapshot.pages.find(p=>p.id===page)?.title??'Home';
 root.innerHTML=`<div class="shell"><aside class="sidebar"><a href="#" class="brand" data-page="home" aria-label="The Order: 1886 Home"><img src="/assets/logo-stacked.png" alt="The Order: 1886"></a>
 <nav aria-label="${escape(t('Main navigation'))}">${snapshot.pages.map(item=>`<button data-page="${item.id}" class="nav-item ${page===item.id&&!query?'selected':''}"${page===item.id&&!query?' aria-current="page"':''}>${icon(item.id)}<span>${escape(t(item.title))}</span></button>`).join('')}</nav>
 <div class="sidebar-bottom"><span>CUSA00076</span><span>${escape(t('Development preview'))}</span><button class="quiet" data-link="releases">${escape(t('View releases'))}</button></div></aside>
 <main><header class="topbar"><span class="current-section">${escape(t(pageTitle))}</span><label class="search">${icon('search')}<span class="sr-only">${escape(t('Search all settings'))}</span><input id="search" type="search" placeholder="${escape(t('Search all settings'))}" value="${escape(query)}" autocomplete="off"></label><span class="session-status">${escape(t(snapshot.busy?'Running':'Idle'))}</span></header>
 <div id="content" class="content">${page==='home'&&!query?home():settingsPage()}</div>
 <footer class="launchbar"><div><p id="feedback" role="status" aria-live="polite">${escape(notice||t(snapshot.busy?'Session running. Settings are locked.':'Changes are saved automatically.'))}</p>
 <p class="launch-context">${escape(selectedBackup?t('Selected backup will be restored after confirmation.'):t('Original game files and player data are protected.'))}</p></div>
 <button id="launch" class="primary" data-action="play"${saving?' disabled':''}>${escape(t(snapshot.busy?'Stop':'Play'))}</button></footer></main></div>
 <dialog id="confirm" aria-labelledby="confirm-title" aria-describedby="confirm-detail"><h2 id="confirm-title"></h2><p id="confirm-detail"></p><div class="actions"><button id="confirm-no">${escape(t('Cancel'))}</button><button id="confirm-yes" class="primary"></button></div></dialog>`;
 bind();
 if(focusKey) {
  const next=document.querySelector<HTMLInputElement>(`[data-setting="${focusKey}"]`);
  next?.focus();
  if(selection&&next?.type==='text') next.setSelectionRange(selection[0],selection[1]);
 }
}
function navigate(next:string) { page=next;query='';render();document.querySelector<HTMLElement>('#content h1')?.setAttribute('tabindex','-1');document.querySelector<HTMLElement>('#content h1')?.focus(); }
async function refresh() { snapshot=await call<Snapshot>('state.get');render(); }
async function save(key:string,value:unknown) {
 saving=true;
 try {
  snapshot=await call<Snapshot>('settings.set',{values:{[key]:value}});
  notice=t('Saved — applies on next launch.'); render();
 } catch(error) { render();flash(String(error),true); }
 finally {saving=false;document.querySelectorAll<HTMLButtonElement>('[data-action="play"]').forEach(b=>b.disabled=false);}
}
function bind() {
 document.querySelectorAll<HTMLElement>('[data-page]').forEach(button=>button.onclick=event=>{event.preventDefault();navigate(button.dataset.page!);});
 const search=document.querySelector<HTMLInputElement>('#search')!;
 search.oninput=()=>{
  const position=search.selectionStart;query=search.value;render();
  const next=document.querySelector<HTMLInputElement>('#search')!;next.focus();next.setSelectionRange(position,position);
 };
 document.querySelectorAll<HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement>('[data-setting]').forEach(input=>input.onchange=()=>{
  const field=snapshot.fields.find(f=>f.key===input.dataset.setting)!;
  let value:unknown=input.value;
  if(field.kind==='boolean') value=(input as HTMLInputElement).checked;
  if(field.kind==='number') value=Number(input.value);
  if(field.kind==='select') value=field.choices!.find(c=>String(c.value)===input.value)!.value;
  if(field.kind==='order') value=input.value.split('\n').map(x=>x.trim()).filter(Boolean);
  void save(field.key,value);
 });
 document.querySelectorAll<HTMLButtonElement>('[data-browse]').forEach(button=>button.onclick=async()=>{
  try{const field=snapshot.fields.find(f=>f.key===button.dataset.browse)!;const path=await bridge().Browse(field.kind);if(path) await save(field.key,path);}
  catch(error){flash(String(error),true);}
 });
 document.querySelectorAll<HTMLButtonElement>('[data-link]').forEach(button=>button.onclick=()=>void bridge().OpenLink(button.dataset.link!).catch(error=>flash(String(error),true)));
 document.querySelectorAll<HTMLButtonElement>('[data-location]').forEach(button=>button.onclick=()=>void bridge().OpenLocation(button.dataset.location!).catch(error=>flash(String(error),true)));
 document.querySelectorAll<HTMLButtonElement>('[data-action]').forEach(button=>button.onclick=()=>void action(button.dataset.action!));
 const backup=document.querySelector<HTMLSelectElement>('#backup');
 if(backup) backup.onchange=()=>{selectedBackup=backup.value;render();};
 document.querySelector('#confirm-no')!.addEventListener('click',()=>finishConfirmation(false));
 document.querySelector('#confirm-yes')!.addEventListener('click',()=>finishConfirmation(true));
 document.querySelector<HTMLDialogElement>('#confirm')!.addEventListener('cancel',event=>{event.preventDefault();finishConfirmation(false);});
}
async function action(name:string) {
 try {
  if(name==='play'&&snapshot.busy){await call('session.stop');flash(t('Stopping session…'));return;}
  if(['play','verify','prepare'].includes(name)) {
   const params:Record<string,unknown>={mode:name==='play'?'play':name};
   if(name==='play'&&selectedBackup){
    if(!await confirmAction(t('Restore save backup?'),`${selectedBackup}. ${t('Current saves will be backed up before restoring. The game will then start; choose Continue or Load.')} `,t('Restore and play'))) return;
    params.backup=selectedBackup;params.confirmed=true;
   }
   await call('session.start',params);selectedBackup='';notice=t('Starting session…');await refresh();return;
  }
  if(name==='reset'){
   if(await confirmAction(t('Reset section?'),t('Reset this section to validated defaults?'),t('Reset'))) snapshot=await call('settings.reset',{page});
  }else if(name==='saves.restore'){
   if(!selectedBackup) {flash(t('Choose a save backup first.'),true);return;}
   if(!await confirmAction(t('Restore save backup?'),`${selectedBackup}. ${t('Current saves will be backed up first. Stop the game before restoring.')} `,t('Restore'))) return;
   snapshot=await call(name,{name:selectedBackup,confirmed:true});selectedBackup='';notice=t('Save restored. Start the game and choose Continue or Load.');
  }else if(name==='cache.clear'){
   if(!await confirmAction(t('Clear shader cache?'),t('Only this title’s regenerable shader cache will be removed. Saves and settings are preserved.'),t('Clear shader cache'))) return;
   snapshot=await call(name,{confirmed:true});notice=t('Shader cache cleared.');
  }else{
   const result=await call(name);
   if(result.settings) snapshot=result;
   notice=result.path?`${t('Completed')}: ${result.path}`:t('Completed');
  }
  render();
 }catch(error){flash(String(error),true);}
}
async function start() {
 root.innerHTML='<main class="boot"><h1>The Order: 1886</h1><p role="status">Connecting to your local launcher…</p></main>';
 try{
  for(let i=0;i<100&&!window.go;i++) await new Promise(resolve=>setTimeout(resolve,100));
  const startup=await bridge().StartupError();
  await refresh();if(startup) flash(startup,true);
  window.runtime?.EventsOn('worker',(event:{event:string;data:unknown})=>{
   if(event.event==='line') {
    snapshot.logs.push(String(event.data));snapshot.logs=snapshot.logs.slice(-100);
    const output=document.querySelector('#session-output');if(output) output.textContent=snapshot.logs.join('');
   }
   if(event.event==='done') {notice=t('Session ended.');void refresh().catch(error=>flash(String(error),true));}
   if(event.event==='started') {snapshot.busy=true;render();}
  });
  window.runtime?.EventsOn('close-requested',async()=>{
   if(await confirmAction(t('Stop and close?'),t('The current session will be stopped before the launcher closes.'),t('Stop and close'))) await bridge().ConfirmClose();
  });
  setInterval(()=>{if(page==='achievements'&&!saving&&!confirmation&&!document.hidden) void refresh().catch(error=>flash(String(error),true));},3000);
 }catch(error){root.innerHTML=`<main class="boot"><h1>Launcher setup required</h1><p role="alert">${escape(String(error))}</p><p>Repair the portable installation or use the retained legacy launcher.</p></main>`;}
}
document.addEventListener('keydown',event=>{
 if((event.ctrlKey||event.metaKey)&&event.key==='k'){event.preventDefault();document.querySelector<HTMLInputElement>('#search')?.focus();}
});
void start();

