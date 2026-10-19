import test from 'node:test';
import assert from 'node:assert/strict';
import {withBinding} from '../.test-build/input-bindings.js';

test('changing one button preserves the other overrides and Default removes only that override',()=>{
 const original={cross:'Q',triangle:'Space'};
 assert.deepEqual(withBinding(original,'cross','Left Shift'),{cross:'Left Shift',triangle:'Space'});
 assert.deepEqual(withBinding(original,'cross',''),{triangle:'Space'});
 assert.deepEqual(original,{cross:'Q',triangle:'Space'});
});
test('an explicitly selected new binding can repair a malformed saved mapping',()=>{
 assert.deepEqual(withBinding(null,'cross','Q'),{cross:'Q'});
 assert.deepEqual(withBinding('bad saved value','cross','Q'),{cross:'Q'});
});
