import test from 'node:test';
import assert from 'node:assert/strict';
import {parseUpdate, updateHeadline, updateSection} from '../.test-build/updates.js';

const t = value => value;
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const base = {
  state: 'idle', version: '', downloaded: 0, total: 0, channel: 'preview', automatic: false,
  error: '', recovery_pending: false, recovery_blocked: false, install_available: false,
  install_reason: 'Download an update before installing it.',
};

test('a parsed status fills every field the pages read', () => {
  const status = parseUpdate(JSON.stringify({state: 'available', version: 'v1.0.0'}));
  assert.equal(status.state, 'available');
  assert.equal(status.version, 'v1.0.0');
  assert.equal(status.channel, 'preview');
  assert.equal(status.install_available, false);
  assert.equal(status.recovery_blocked, false);
});

test('an empty bridge response still yields a usable status', () => {
  const status = parseUpdate('{}');
  assert.equal(status.state, 'idle');
  assert.equal(status.total, 0);
});

test('install is offered only for a staged update the backend allows', () => {
  const staged = updateSection({...base, state: 'staged', version: 'v1.0.0', install_available: true}, t, escape, false);
  assert.match(staged, /data-action="update\.install"/);
  const locked = updateSection({...base, state: 'staged', install_available: false}, t, escape, false);
  assert.doesNotMatch(locked, /data-action="update\.install"/);
  assert.match(locked, /Download an update before installing it\./);
});

test('a blocked recovery offers restore instead of install', () => {
  const blocked = updateSection({...base, recovery_pending: true, recovery_blocked: true}, t, escape, false);
  assert.match(blocked, /data-action="update\.restore"/);
  assert.doesNotMatch(blocked, /data-action="update\.install"/);
  assert.equal(updateHeadline({...base, recovery_blocked: true}, t), 'An interrupted update needs your decision');
});

test('a pending recovery is reachable before any failure is recorded', () => {
  // The launcher refuses every worker call while a journal is pending, so the
  // restore action must exist from the journal state alone.
  const pending = updateSection({...base, recovery_pending: true}, t, escape, false);
  assert.match(pending, /data-action="update\.restore"/);
  assert.doesNotMatch(pending, /data-action="update\.install"/);
});

test('a completed update can be rolled back on request', () => {
  const completed = updateSection({...base, rollback_available: true}, t, escape, false);
  assert.match(completed, /data-action="update\.restore"/);
  assert.match(completed, /Roll back this update/);
  assert.doesNotMatch(completed, /data-action="update\.install"/);
});

test('a pending journal blocks installing another update', () => {
  const staged = updateSection({...base, state: 'staged', install_available: false}, t, escape, false);
  assert.doesNotMatch(staged, /data-action="update\.install"/);
});

test('progress and failures are visible', () => {
  const downloading = updateSection({...base, state: 'downloading', downloaded: 5, total: 10}, t, escape, false);
  assert.match(downloading, /<progress value="5" max="10">/);
  assert.match(downloading, /50%/);
  const failed = updateSection({...base, state: 'failed', error: 'HTTP 404'}, t, escape, false);
  assert.match(failed, /role="alert"/);
  assert.match(failed, /HTTP 404/);
});

test('every mutating action is disabled while a session or save is busy', () => {
  const section = updateSection({...base, state: 'staged', install_available: true}, t, escape, true);
  const actions = section.match(/<button[^>]*data-action[^>]*>/g) ?? [];
  assert.ok(actions.length >= 2);
  for (const button of actions) assert.match(button, /disabled/);
  // A link to the release page changes nothing, so it stays available.
  assert.match(section, /<button data-link="releases">/);
});
