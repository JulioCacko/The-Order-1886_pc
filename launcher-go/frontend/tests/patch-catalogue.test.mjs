import test from 'node:test';
import assert from 'node:assert/strict';
import {patchCatalogue} from '../.test-build/patch-catalogue.js';

const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const builtin = {
  id: 'order1886-a8ce-engine-60-v1', title: '60 FPS unlock',
  description: 'Engine timing unlock verified against the CUSA00076 executable.',
  builtin: true, available: false,
  reason: 'Configured by the game frame rate or framing setting, not by a patch selection.',
  warning: 'Experimental: gameplay remains unverified.',
};

test('no catalogue renders nothing at all', () => {
  assert.equal(patchCatalogue(undefined, escape), '');
  assert.equal(patchCatalogue([], escape), '');
  assert.equal(patchCatalogue(null, escape), '');
});

test('a built-in recipe says where it is configured instead of offering a toggle', () => {
  const html = patchCatalogue([builtin], escape);
  assert.match(html, /60 FPS unlock/);
  assert.match(html, /configured elsewhere/);
  assert.match(html, /Configured by the game frame rate/);
  assert.doesNotMatch(html, /<input/);
});

test('an applicable recipe is listed without a refusal line', () => {
  const available = {...builtin, builtin: false, available: true, reason: '', warning: ''};
  const html = patchCatalogue([available], escape);
  assert.match(html, /60 FPS unlock/);
  assert.doesNotMatch(html, /class="availability"/);
  assert.doesNotMatch(html, /configured elsewhere/);
});

test('a recipe that does not match this build shows its reason', () => {
  const wrongBuild = {...builtin, builtin: false, available: false,
    reason: 'this build is APP_VER 01.02; the recipe was verified against 01.00'};
  const html = patchCatalogue([wrongBuild], escape);
  assert.match(html, /verified against 01.00/);
});

test('recipe text is escaped, never injected as markup', () => {
  const hostile = {...builtin, title: '<img src=x onerror=alert(1)>', description: '<script>bad()</script>'};
  const html = patchCatalogue([hostile], escape);
  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /<script/);
  assert.match(html, /&lt;img/);
});

test('the panel states that the game folder is never modified', () => {
  assert.match(patchCatalogue([builtin], escape), /game folder is never modified/);
});
