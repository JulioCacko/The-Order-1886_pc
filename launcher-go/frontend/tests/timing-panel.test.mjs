import test from 'node:test';
import assert from 'node:assert/strict';
import {timingPanel} from '../.test-build/timing-panel.js';

// The panel shows the resolved timing the worker reports. It is a diagnostic: what the
// next launch will ask for, never a measured result.
const t = value => value;
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

test('the default timing shows the engine rate as the effective limit', () => {
  const html = timingPanel({engine_fps: 60, fps_cap: 120, fps_limit: 60, vblank_hz: 60, vsync: true}, t, escape);
  assert.match(html, /Game frame rate<\/dt><dd>60 FPS/);
  assert.match(html, /Presentation cap<\/dt><dd>120 FPS/);
  assert.match(html, /Effective limit<\/dt><dd>60 FPS/);
  assert.match(html, /VSync<\/dt><dd>On/);
  assert.match(html, /not measured performance/);
});

test('a throttling cap is visible as a lower effective limit', () => {
  const html = timingPanel({engine_fps: 60, fps_cap: 30, fps_limit: 30, vblank_hz: 60, vsync: false}, t, escape);
  assert.match(html, /Effective limit<\/dt><dd>30 FPS/);
  assert.match(html, /VSync<\/dt><dd>Off/);
});

test('an uncapped launch says so instead of printing null', () => {
  const html = timingPanel({engine_fps: 60, fps_cap: 120, fps_limit: null, vblank_hz: 0, vsync: true}, t, escape);
  assert.match(html, /Effective limit<\/dt><dd>uncapped/);
  assert.match(html, /VBlank<\/dt><dd>uncapped/);
  assert.doesNotMatch(html, /null/);
});

test('a refused timing configuration is reported, not hidden', () => {
  const html = timingPanel({error: 'Presentation frame cap must be a whole number from 30 to 240'}, t, escape);
  assert.match(html, /role="alert"/);
  assert.match(html, /30 to 240/);
});

test('no timing data renders nothing rather than an empty panel', () => {
  assert.equal(timingPanel(undefined, t, escape), '');
  assert.equal(timingPanel(null, t, escape), '');
});
