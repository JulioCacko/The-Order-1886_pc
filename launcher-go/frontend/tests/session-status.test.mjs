import test from 'node:test';
import assert from 'node:assert/strict';
import {completionNotice} from '../.test-build/session-status.js';

test('verification and preparation successes have distinct results',()=>{
  assert.equal(completionNotice([0,'verify',false],'log').message,'Verification completed.');
  assert.equal(completionNotice([0,'prepare',false],'log').message,'Preparation completed.');
  assert.equal(completionNotice([0,'play',false],'log').failed,false);
});
test('failure retains its exit code and durable log location',()=>{
  const result=completionNotice([23,'prepare',false],'C:/player/session.log');
  assert.equal(result.failed,true);
  assert.match(result.message,/23/);
  assert.match(result.message,/C:\/player\/session.log/);
});
test('stops are distinct from success and cannot hide another failure',()=>{
  assert.equal(completionNotice([130,'play',true],'log').message,'Session stopped.');
  assert.equal(completionNotice([0,'play',true],'log').message,'Session stopped.');
  assert.equal(completionNotice([7,'play',true],'log').failed,true);
});
test('malformed completion is reported as a failure',()=>{
  for(const value of [null,[],['0','play',false]]) assert.equal(completionNotice(value,'log').failed,true);
});

