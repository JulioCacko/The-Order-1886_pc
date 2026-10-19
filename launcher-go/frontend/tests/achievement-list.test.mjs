import test from 'node:test';
import assert from 'node:assert/strict';
import {achievementRows, unlockDate} from '../.test-build/achievement-list.js';

test('installed trophies include locked items and retain unrecognized earned IDs',()=>{
 const rows=achievementRows([{id:2,unlocked_at:1700000000},{id:7,unlocked_at:1700000001}],
  [{id:1,icon:''},{id:2,icon:'data:image/png;base64,abc'}]);
 assert.deepEqual(rows.map(row=>[row.id,row.unlocked_at??null]),[[1,null],[2,1700000000],[7,1700000001]]);
 assert.equal(rows[1].icon,'data:image/png;base64,abc');
 assert.equal(rows[2].icon,'');
});
test('unlock times are readable dates with a machine-readable value in every launcher locale',()=>{
 for(const locale of ['en','ru','ar','es','pt','fr','de','it','pl','tr','zh','ja','ko']){
  const result=unlockDate(1700000000,locale);
  assert.equal(result.iso,'2023-11-14T22:13:20.000Z');
  assert.ok(result.text.length>5);
 }
 for(const value of [NaN,Infinity,0,-1,2**63]) assert.equal(unlockDate(value,'en'),null);
});
