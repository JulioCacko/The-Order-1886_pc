import test from 'node:test';
import assert from 'node:assert/strict';
import {createSettingsSaver} from '../.test-build/settings-save.js';
import {withBinding} from '../.test-build/input-bindings.js';

test('rapid button edits wait for the prior response and merge from confirmed state',async()=>{
 const settings={keyboard_bindings:{}};
 const writes=[];
 let release;
 const delayed=new Promise(resolve=>release=resolve);
 const save=createSettingsSaver(key=>settings[key],async(key,value)=>{
  writes.push(value);
  if(writes.length===1) await delayed;
  settings[key]=value;
 });
 const first=save('keyboard_bindings',current=>withBinding(current,'cross','Q'));
 const second=save('keyboard_bindings',current=>withBinding(current,'triangle','Space'));
 await Promise.resolve();
 assert.equal(writes.length,1);
 release();
 await Promise.all([first,second]);
 assert.deepEqual(settings.keyboard_bindings,{cross:'Q',triangle:'Space'});
});
test('a rejected save does not poison later edits or use an uncommitted value',async()=>{
 let settings={cross:'Q'};
 let count=0;
 const save=createSettingsSaver(()=>settings,async(_key,value)=>{
  if(++count===1) throw new Error('save failed');
  settings=value;
 });
 await assert.rejects(save('keyboard_bindings',current=>withBinding(current,'cross','Space')));
 await save('keyboard_bindings',current=>withBinding(current,'triangle','Left Shift'));
 assert.deepEqual(settings,{cross:'Q',triangle:'Left Shift'});
});
