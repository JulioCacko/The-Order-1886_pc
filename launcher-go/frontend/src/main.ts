import './style.css';
import {completionNotice} from './session-status';
import {achievementRows, unlockDate, type TrophyArtwork} from './achievement-list';
import {replaceView} from './view-state';
import {withBinding} from './input-bindings';
import {createSettingsSaver} from './settings-save';
import {parseUpdate, updateHeadline, updateSection, type UpdateStatus} from './updates';
import {timingPanel, type Timing} from './timing-panel';
import {patchCatalogue, type CatalogueRow} from './patch-catalogue';
import wails from '../../wails.json';

type Choice = {value:string|number; label:string; available:boolean; reason:string};
type Field = {key:string;label:string;page:string;kind:string;default:unknown;description:string;
  available:boolean;reason:string;minimum?:number;maximum?:number;choices?:Choice[];
  input_kind?:string;buttons?:{id:string;label:string;default:string[]}[]};
type Snapshot = {trophies:{id:number;unlocked_at:number}[];trophy_error:string;settings:Record<string,any>;fields:Field[];pages:{id:string;title:string}[];
  trophy_catalog?:TrophyArtwork[];trophy_catalog_error?:string;
  languages:Record<string,string>;translations:Record<string,string>;game:{ready:boolean;message:string;metadata:Record<string,unknown>;experimental?:boolean};
  busy:boolean;backups:string[];saves_dir:string;logs:string[];logfile:string;state_dir:string;last_exit:number|null;acceptance:string;
  timing?:Timing;patches?:CatalogueRow[]};
type AppBridge = {Call:(method:string,params:Record<string,unknown>)=>Promise<string>;
  Browse:(kind:string)=>Promise<string>;OpenLink:(name:string)=>Promise<void>;
  StartupError:()=>Promise<string>;ConfirmClose:()=>Promise<void>;OpenLocation:(kind:string)=>Promise<void>;
  UpdateState:()=>Promise<string>;UpdateCheck:()=>Promise<string>;UpdateDownload:()=>Promise<string>;
  UpdateCancel:()=>Promise<string>;UpdateInstall:()=>Promise<void>;UpdateRestore:()=>Promise<void>};
declare global { interface Window {
  go?:{main:{App:AppBridge}};
  runtime?:{EventsOn:(name:string,callback:(event:any)=>void)=>void};
}}
let snapshot:Snapshot;
let page = 'home';
let query = '';
let selectedBackup = '';
let notice = '';
let noticeError = false;
let starting = false;
let disconnected = false;
let saving = 0;
let update:UpdateStatus|null = null;
async function refreshUpdate() {
 try { update = parseUpdate(await bridge().UpdateState()); } catch { update = null; }
 return update;
}
const queueSettingsSave=createSettingsSaver(key=>snapshot.settings[key],commitSetting);
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
  noticeError=error;
  const status=document.querySelector<HTMLElement>('#feedback');
  if(status){status.textContent=message;status.classList.toggle('error',error);}
}
function setStarting(value:boolean) { starting=value;render(); }
function showCompletion(data:unknown) {
 const result=completionNotice(data,snapshot.logfile);
 flash(t(result.message),result.failed);
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
  const disabled=!field.available||snapshot.busy||starting||disconnected?' disabled':'';
  const label=`id="field-${field.key}" data-setting="${field.key}" aria-describedby="help-${field.key}"`;
  if(field.kind==='boolean') return `<input type="checkbox" ${label}${disabled}${value?' checked':''}>`;
  if(field.kind==='select') return `<select ${label}${disabled}>${field.choices!.filter(choice=>choice.available||value===choice.value).map(choice=>
    `<option value="${escape(String(choice.value))}"${value===choice.value?' selected':''}${!choice.available?' disabled':''}>${escape(t(choice.label))}${!choice.available?' — '+escape(t('Unavailable')):''}</option>`).join('')}</select>`;
  if(field.kind==='bindings') {
   const mapping=value&&typeof value==='object'&&!Array.isArray(value)?value:{};
   return `<fieldset id="field-${field.key}" class="binding-grid" aria-describedby="help-${field.key}"><legend class="sr-only">${escape(t(field.label))}</legend>${field.buttons!.map(button=>{
    const id=`field-${field.key}-${button.id}`;
    const selected=typeof mapping[button.id]==='string'?mapping[button.id]:'';
    const known=field.choices!.some(choice=>choice.value===selected);
    const fallback=button.default.length?button.default.join(' / '):field.reason?'':field.input_kind==='controller'&&['l2','r2'].includes(button.id)?t('Physical trigger remains active'):t('No digital source');
    return `<label for="${id}">${escape(t(button.label))}</label><select id="${id}" data-setting="${field.key}" data-binding="${button.id}" aria-describedby="help-${field.key}"${disabled}>
     <option value=""${!selected?' selected':''}>${escape(t('Default'))}${fallback?' ('+escape(fallback)+')':''}</option>
     ${selected&&!known?`<option value="${escape(selected)}" selected disabled>${escape(selected)} — ${escape(t('Unavailable'))}</option>`:''}
     ${field.choices!.map(choice=>`<option value="${escape(choice.value)}"${selected===choice.value?' selected':''}${!choice.available?' disabled':''}>${escape(t(choice.label))}${!choice.available?' — '+escape(t('Unavailable')):''}</option>`).join('')}</select>`;
   }).join('')}</fieldset>`;
  }
  if(field.kind==='order') return `<textarea ${label}${disabled} rows="3" spellcheck="false">${escape((value as string[]).join('\n'))}</textarea>`;
  if(field.kind==='number') return `<input type="number" ${label}${disabled} value="${escape(value)}" min="${field.minimum}" max="${field.maximum}" step="1">`;
  if(field.kind==='secret') return `<input type="password" ${label}${disabled} value="${escape(value)}" autocomplete="off" spellcheck="false">`;
  return `<div class="path-input"><input type="text" ${label}${disabled} value="${escape(value)}" autocomplete="off" spellcheck="false">${['directory','file'].includes(field.kind)?`<button data-browse="${field.key}"${disabled} aria-label="${escape(t('Browse')+' '+t(field.label))}">${escape(t('Browse'))}</button>`:''}</div>`;
}
function fieldRow(field:Field) {
 return `<div class="setting-row ${field.kind==='bindings'?'binding-row ':''}${!field.available?'unavailable':''}" data-field-row="${field.key}">
  <div class="setting-copy">${field.kind==='bindings'?`<h2>${escape(t(field.label))}</h2>`:`<label for="field-${field.key}">${escape(t(field.label))}</label>`}
  <p id="help-${field.key}">${escape(t(field.description))}</p>
  ${field.reason?`<p class="availability">${escape(t(field.reason))}</p>`:''}
</div>
  <div class="setting-control">${control(field)}</div></div>`;
}
function actionButton(action:string,title:string,destructive=false) {
 return `<button data-action="${action}" class="${destructive?'danger':''}"${snapshot.busy||starting||disconnected||saving?' disabled':''}>${escape(t(title))}</button>`;
}
function gameActions() {
 return `<section class="utility-section"><h2>${escape(t('Saves'))}</h2>
 <p>${escape(t('Saves folder'))}: <code>${escape(snapshot.saves_dir)}</code></p>
 <p>${escape(t('Import copies saves from another installation, a save backup or a decrypted save folder. Current saves are backed up first; saves with the same name are replaced.'))}</p>
 <div class="actions"><button data-location="saves">${escape(t('Open saves folder'))}</button>${actionButton('saves.import','Import saves…')}</div></section>
 <section class="utility-section"><h2>${escape(t('Save backups'))}</h2>
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
 <h2>${escape(t('Updates and support'))}</h2>
 ${updateSection(update,t,escape,Boolean(snapshot.busy||starting||disconnected||saving))}
 <div class="actions"><button data-link="issues">${escape(t('Report an issue'))}</button></div>
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
 <button class="hero-play" data-action="play"${saving||starting||disconnected?' disabled':''}>${snapshot.busy?escape(t('Stop')):`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7z"/></svg>${escape(t('Play'))}`}</button>
 <button class="quiet hero-settings" data-page="graphics">${escape(t('Configure graphics'))}</button></div></section>
 ${update&&['available','staged','downloading','failed'].includes(update.state)||update?.recovery_blocked?`<section class="utility-section" aria-live="polite">
 <h2>${escape(updateHeadline(update,t))}</h2>
 ${update?.error?`<p role="alert" class="error">${escape(update.error)}</p>`:''}
 <div class="actions"><button data-page="system">${escape(t('Open updates'))}</button></div></section>`:''}
 <section class="home-bottom" aria-label="${escape(t('Launch configuration'))}">
 <div><h2>${escape(t('Launch configuration'))}</h2><dl class="configuration">
 <div><dt>${escape(t('Display'))}</dt><dd>${escape(values.display_mode)}</dd></div>
 <div><dt>${escape(t('Upscaling'))}</dt><dd>${escape(values.presentation_filter==='fsr1'?'FSR 1':values.presentation_filter)}</dd></div>
 <div><dt>${escape(t('Game frame rate'))}</dt><dd>${escape(values.frame_rate)} FPS</dd></div>
 <div><dt>${escape(t('Framing'))}</dt><dd>${escape(values.aspect_ratio)}</dd></div></dl>
 <p class="quiet-copy">${escape(t('GPU readback policy'))}: ${escape(values.readbacks||'relaxed')}</p>
 <p class="quiet-copy">${escape(t('Configured values; measured performance is recorded separately.'))}</p></div>
 <div class="installation"><h2>${escape(t('Game installation'))}</h2>
 <p class="readiness ${snapshot.game.ready?'ready':''}">${escape(t(snapshot.game.ready?'Game files found':'Setup required'))}</p>
 <p class="truncate" title="${escape(values.game_dir)}">${escape(values.game_dir||t('Choose your extracted game folder'))}</p>
 <p class="quiet-copy">${snapshot.game.ready?`${escape(snapshot.game.metadata.TITLE_ID)} · APP_VER ${escape(snapshot.game.metadata.APP_VER)} · VERSION ${escape(snapshot.game.metadata.VERSION)}`:escape(snapshot.game.message)}</p>
 ${snapshot.game.experimental?`<p class="quiet-copy">${escape(t('Experimental edition: only CUSA00076 has been tested with a real dump. If something fails, report it with the session log.'))}</p>`:''}
 <button class="quiet" data-page="game">${escape(t('Manage game and saves'))}</button></div></section>`;
}
function achievementsPage() {
 const catalog=snapshot.trophy_catalog??[];
 const rows=achievementRows(snapshot.trophies,catalog);
 const earned=new Set(snapshot.trophies.map(item=>item.id));
 const count=catalog.filter(item=>earned.has(item.id)).length;
 return `<section class="settings-page"><h1 id="achievements-heading" tabindex="-1">${escape(t('Achievements'))}</h1>
 <p class="quiet-copy">${escape(t('Local unlock history and artwork from your installed game. Names and descriptions are decrypted from your game with your own trophy key. Locked artwork stays hidden.'))}</p>
 ${snapshot.trophy_error?`<p role="alert" class="error">${escape(snapshot.trophy_error)}</p>`:catalog.length?`<p id="achievement-progress">${count} / ${catalog.length} ${escape(t('installed achievements earned'))}</p><progress value="${count}" max="${catalog.length}" aria-labelledby="achievement-progress"></progress>`:''}
 ${snapshot.trophy_catalog_error?`<p class="quiet-copy">${escape(t(snapshot.trophy_catalog_error))}</p>`:''}
 ${rows.length?`<ol class="trophy-list">${rows.map(item=>{
  const date=item.unlocked_at===undefined?null:unlockDate(item.unlocked_at,snapshot.settings.ui_language);
  const status=snapshot.trophy_error?'Unlock status unavailable':item.unlocked_at===undefined?'Locked':'Unlocked';
  return `<li>${item.icon?`<img src="${escape(item.icon)}" alt="" width="64" height="64" loading="lazy" decoding="async">`:`<span class="trophy-placeholder" aria-hidden="true">${icon('achievements')}</span>`}
  <div class="trophy-copy"><strong>${item.name?escape(item.name):item.hidden&&item.unlocked_at===undefined?escape(t('Hidden trophy')):`${escape(t('Trophy'))} ${item.id}`}</strong>${item.detail?`<span>${escape(item.detail)}</span>`:''}<span>${item.grade?escape(t(item.grade[0].toUpperCase()+item.grade.slice(1)))+' · ':''}${escape(t(status))}</span></div>
  ${date?`<time datetime="${date.iso}">${escape(date.text)}</time>`:item.unlocked_at!==undefined?`<span class="quiet-copy">${escape(t('Unlock time unavailable'))}</span>`:''}</li>`;
 }).join('')}</ol>`:`<p class="empty-state">${escape(t('No earned trophies recorded yet. Unlocks appear here when the game writes them.'))}</p>`}
 ${snapshot.fields.filter(field=>field.available&&field.page==='achievements').map(fieldRow).join('')}</section>`;
}
function settingsPage() {
 const matching=snapshot.fields.filter(field=>field.available&&(query?
  `${field.label} ${field.description} ${field.reason} ${field.choices?.map(c=>c.label).join(' ')}`.toLowerCase().includes(query.toLowerCase()):
  field.page===page));
 if(page==='achievements'&&!query) return achievementsPage();
 return `<section class="settings-page"><div class="section-heading"><div><h1>${escape(query?t('Search settings'):t(snapshot.pages.find(p=>p.id===page)!.title))}</h1>
 <p>${escape(query?`${matching.length} ${t('matching options')}`:t('Valid changes save automatically. Game settings take effect on the next launch.'))}</p></div>
 ${!query&&matching.some(f=>f.available)?`<button class="quiet" data-action="reset"${snapshot.busy||saving?' disabled':''}>${escape(t('Reset section'))}</button>`:''}</div>
 ${matching.length?matching.map(fieldRow).join(''):`<p class="empty-state">${escape(t('No matching settings. Try a different search.'))}</p>`}
 ${page==='performance'&&!query?timingPanel(snapshot.timing,t,escape):''}${page==='game'&&!query?patchCatalogue(snapshot.patches,escape)+gameActions():''}${page==='system'&&!query?systemActions():''}</section>`;
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
 replaceView(root,`<div class="shell"><aside class="sidebar"><a href="#" class="brand" data-page="home" aria-label="The Order: 1886 Home"><img src="/assets/logo-stacked.png" alt="The Order: 1886"></a>
 <nav aria-label="${escape(t('Main navigation'))}">${snapshot.pages.map(item=>`<button id="nav-${item.id}" data-page="${item.id}" class="nav-item ${page===item.id&&!query?'selected':''}"${page===item.id&&!query?' aria-current="page"':''}>${icon(item.id)}<span>${escape(t(item.title))}</span></button>`).join('')}</nav>
 <div class="sidebar-bottom"><span>${escape(snapshot.game.metadata?.TITLE_ID??'')}</span><span>v${escape(wails.info.productVersion)}</span><button class="quiet" data-link="releases">${escape(t('View releases'))}</button></div></aside>
 <main><header class="topbar"><span class="current-section">${escape(t(pageTitle))}</span><label class="search">${icon('search')}<span class="sr-only">${escape(t('Search all settings'))}</span><input id="search" type="search" placeholder="${escape(t('Search all settings'))}" value="${escape(query)}" autocomplete="off"></label><span class="session-status">${escape(t(disconnected?'Connection lost':snapshot.busy?'Running':starting?'Starting…':'Idle'))}</span></header>
 <div id="content" class="content">${page==='home'&&!query?home():settingsPage()}</div>
 <footer class="launchbar"><div><p id="feedback" class="${noticeError?'error':''}" role="status" aria-live="polite">${escape(noticeError?notice:saving?t('Saving settings…'):notice||t(snapshot.busy?'Session running. Settings are locked.':'Changes are saved automatically.'))}</p>
 <p class="launch-context">${escape(selectedBackup?t('Selected backup will be restored after confirmation.'):t('Original game files and player data are protected.'))}</p></div>
 <button id="launch" class="primary" data-action="play"${saving||starting||disconnected?' disabled':''}>${escape(t(snapshot.busy?'Stop':'Play'))}</button></footer></main></div>
 <dialog id="confirm" aria-labelledby="confirm-title" aria-describedby="confirm-detail"><h2 id="confirm-title"></h2><p id="confirm-detail"></p><div class="actions"><button id="confirm-no">${escape(t('Cancel'))}</button><button id="confirm-yes" class="primary"></button></div></dialog>`);
 bind();
 if(focusKey) {
  const next=(focused?.id?document.getElementById(focused.id):document.querySelector(`[data-setting="${focusKey}"]`)) as HTMLInputElement|null;
  next?.focus({preventScroll:true});
  if(selection&&next?.type==='text') next.setSelectionRange(selection[0],selection[1]);
 }
}
function navigate(next:string) { page=next;query='';render();document.querySelector<HTMLElement>('#content')?.scrollTo(0,0);document.querySelector<HTMLElement>('#content h1')?.setAttribute('tabindex','-1');document.querySelector<HTMLElement>('#content h1')?.focus(); }
async function refresh() { snapshot=await call<Snapshot>('state.get');render(); }
async function save(key:string,value:unknown) {
 saving++;
 flash(t('Saving settings…'));
 document.querySelectorAll<HTMLButtonElement>('[data-action]').forEach(button=>button.disabled=true);
 try { await queueSettingsSave(key,value); }
 finally {saving--;render();}
}
async function commitSetting(key:string,value:unknown) {
 try {
  snapshot=await call<Snapshot>('settings.set',{values:{[key]:value}});
  notice=t('Saved — applies on next launch.');noticeError=false;
 } catch(error) { notice=String(error);noticeError=true; }
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
  if(field.kind==='bindings') {
   const button=input.dataset.binding!,source=input.value;
   value=(current:unknown)=>withBinding(current,button,source);
  }
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
 bindConfirmation();
}
function bindConfirmation() {
 document.querySelector('#confirm-no')!.addEventListener('click',()=>finishConfirmation(false));
 document.querySelector('#confirm-yes')!.addEventListener('click',()=>finishConfirmation(true));
 document.querySelector<HTMLDialogElement>('#confirm')!.addEventListener('cancel',event=>{event.preventDefault();finishConfirmation(false);});
}
// The launcher refuses every worker call while an update is unrecovered, so the
// recovery screen is built from the journal-only update state: without it a player
// would see "setup required" and no way to restore.
function recoveryView(message:string) {
 root.innerHTML=`<main class="settings-page"><h1 id="recovery-title" tabindex="-1">${escape(t('Update needs your attention'))}</h1>
 <p role="alert" class="error">${escape(message)}</p>
 <section class="utility-section">${updateSection(update,t,escape,false)}</section></main>`;
 document.querySelectorAll<HTMLButtonElement>('[data-action]').forEach(button=>button.onclick=()=>void action(button.dataset.action!));
 document.querySelectorAll<HTMLButtonElement>('[data-link]').forEach(button=>button.onclick=()=>void bridge().OpenLink(button.dataset.link!).catch(error=>flash(String(error),true)));
 bindConfirmation();
 document.querySelector<HTMLElement>('#recovery-title')?.focus();
}
async function action(name:string) {
 try {
  if(saving){flash(t('Wait for settings to finish saving.'));return;}
  if(name==='play'&&snapshot.busy){await call('session.stop');flash(t('Stopping session…'));return;}
  if(['play','verify','prepare'].includes(name)) {
   if(starting||disconnected||saving) return;
   setStarting(true);
   try {
   const params:Record<string,unknown>={mode:name==='play'?'play':name};
   if(name==='play'&&selectedBackup){
    if(!await confirmAction(t('Restore save backup?'),`${selectedBackup}. ${t('Current saves will be backed up before restoring. The game will then start; choose Continue or Load.')} `,t('Restore and play'))) return;
    params.backup=selectedBackup;params.confirmed=true;
   }
   const started=await call<{logfile:string}>('session.start',params);
   snapshot.logfile=started.logfile;selectedBackup='';
   await refresh();
   if(snapshot.busy) flash(t('Starting session…'));
   else if(snapshot.last_exit!==null) showCompletion([snapshot.last_exit,params.mode,false]);
   return;
   } finally {setStarting(false);}
  }
  if(name==='update.check') {
   notice=t('Checking for updates…');noticeError=false;render();
   await refreshUpdate();void bridge().UpdateCheck().then(()=>refreshUpdate()).then(()=>render()).catch(error=>flash(String(error),true));
   return;
  }
  if(name==='update.download') {
   notice=t('Downloading the update…');noticeError=false;render();
   await refreshUpdate();
   void bridge().UpdateDownload().then(()=>refreshUpdate()).then(()=>render()).catch(error=>flash(String(error),true));
   return;
  }
  if(name==='update.cancel') {
   await bridge().UpdateCancel();await refreshUpdate();notice=t('Download cancelled.');noticeError=false;render();
   return;
  }
  if(name==='update.install') {
   if(!await confirmAction(t('Install and restart?'),t('The launcher closes so the update can replace its own files. Saves, settings, mods and patches are preserved, and the launcher reopens when it is done.'),t('Install and restart'))) return;
   await bridge().UpdateInstall();
   return;
  }
  if(name==='update.restore') {
   if(!await confirmAction(t('Restore the previous version?'),t('The interrupted update is rolled back from its verified backup. Choose this only after reading the recorded failure.'),t('Restore previous version'))) return;
   await bridge().UpdateRestore();
   return;
  }
  if(name==='reset'){
   if(!await confirmAction(t('Reset section?'),t('Reset this section to validated defaults?'),t('Reset'))) return;
   snapshot=await call('settings.reset',{page});notice=t('Section reset.');
  }else if(name==='saves.restore'){
   if(!selectedBackup) {flash(t('Choose a save backup first.'),true);return;}
   if(!await confirmAction(t('Restore save backup?'),`${selectedBackup}. ${t('Current saves will be backed up first. Stop the game before restoring.')} `,t('Restore'))) return;
   snapshot=await call(name,{name:selectedBackup,confirmed:true});selectedBackup='';notice=t('Save restored. Start the game and choose Continue or Load.');
  }else if(name==='saves.import'){
   const path=await bridge().Browse('directory');
   if(!path) return;
   if(!await confirmAction(t('Import saves?'),`${path}. ${t('Current saves will be backed up first. Stop the game before importing.')} `,t('Import'))) return;
   snapshot=await call(name,{path,confirmed:true});notice=t('Saves imported. Start the game and choose Continue or Load.');
  }else if(name==='cache.clear'){
   if(!await confirmAction(t('Clear shader cache?'),t('Only this title’s regenerable shader cache will be removed. Saves and settings are preserved.'),t('Clear shader cache'))) return;
   snapshot=await call(name,{confirmed:true});notice=t('Shader cache cleared.');
  }else{
   const result=await call(name);
   if(result.settings) snapshot=result;
   notice=result.path?`${t('Completed')}: ${result.path}`:t('Completed');
  }
  noticeError=false;render();
 }catch(error){flash(String(error),true);}
}
async function start() {
 root.innerHTML='<main class="boot"><h1>The Order: 1886</h1><p role="status">Connecting to your local launcher…</p></main>';
 try{
  for(let i=0;i<100&&!window.go;i++) await new Promise(resolve=>setTimeout(resolve,100));
  const startup=await bridge().StartupError();
  await refreshUpdate();
  try {
   await refresh();
  } catch (error) {
   // A recovery-blocked launcher refuses the worker on purpose; its update panel
   // comes from the journal and must still be reachable.
   if (update?.recovery_blocked || update?.recovery_pending || update?.rollback_available) {
    recoveryView(startup || String(error));
    if (startup) flash(startup, true);
    return;
   }
   throw error;
  }
  if(startup) flash(startup,true);
  window.runtime?.EventsOn('update',(status:unknown)=>{
   update=parseUpdate(JSON.stringify(status));
   if(update.state==='available') notice=`${t('Update available')}: ${update.version}`;
   if(update.recovery_blocked) notice=t('An interrupted update needs your decision');
   noticeError=update.state==='failed';
   render();
  });
  window.runtime?.EventsOn('worker',(event:{event:string;data:unknown})=>{
   if(event.event==='line') {
    snapshot.logs.push(String(event.data));snapshot.logs=snapshot.logs.slice(-100);
    const output=document.querySelector('#session-output');if(output) output.textContent=snapshot.logs.join('');
   }
   if(event.event==='done') {snapshot.busy=false;showCompletion(event.data);void refresh().catch(error=>flash(String(error),true));}
   if(event.event==='disconnected') {
    disconnected=true;snapshot.busy=false;
    flash(t('Worker connection lost. A game may still be running; check its window and the session log before starting another session.'),true);
    render();
   }
   if(event.event==='started') {snapshot.busy=true;render();}
  });
  window.runtime?.EventsOn('close-requested',async()=>{
   if(await confirmAction(t('Stop and close?'),t('The current session will be stopped before the launcher closes.'),t('Stop and close'))) await bridge().ConfirmClose();
  });
  setInterval(()=>{if(page==='achievements'&&!saving&&!confirmation&&!disconnected&&!document.hidden) void refresh().catch(error=>flash(String(error),true));},3000);
  // A download reports progress only through UpdateState, so keep reading it while
  // one is running and while a recovery needs the player's decision.
  setInterval(()=>{
   if(document.hidden||!update) return;
   if(update.state!=='downloading') return;
   void refreshUpdate().then(()=>render()).catch(()=>{});
  },500);
 }catch(error){root.innerHTML=`<main class="boot"><h1>Launcher setup required</h1><p role="alert">${escape(String(error))}</p><p>Repair the portable installation, or restore the previous version from the updates section of a working installation.</p></main>`;}
}
document.addEventListener('keydown',event=>{
 if((event.ctrlKey||event.metaKey)&&event.key==='k'){event.preventDefault();document.querySelector<HTMLInputElement>('#search')?.focus();}
});
void start();

