// Launcher background music: plays the first track in <installation>/music (served by the Go
// side at /music/theme) with a mute button and volume bar at the right end of the top bar.
// The main UI re-renders #app wholesale, so this control lives on <body> and follows it.
const bridge = () => window.go?.main?.App;
const DEFAULT_VOLUME = 20;

const ICON_ON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
const ICON_OFF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor"/><path d="M16 9.5l5 5M21 9.5l-5 5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

const STYLE = `
.topbar{padding-inline-end:var(--music-reserve,240px)!important}
.music-control{--m-line:#ffffff14;--m-line-strong:#ffffff26;--m-ink:#f1ede4;--m-muted:#9c9d96;--m-accent:#d8bd77;--m-focus:#f2d894;--m-bg:#ffffff0d;--m-track:#ffffff24;
  position:fixed;top:15px;right:32px;z-index:30;display:flex;align-items:center;gap:6px;height:34px;padding:0 12px 0 4px;
  border-radius:999px;background:var(--m-bg);border:1px solid var(--m-line);color:var(--m-muted);
  font:500 12px/1 "Inter","Segoe UI Variable","Segoe UI",system-ui,"Cantarell","Noto Sans",Arial,sans-serif;
  -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);transition:border-color .15s,background .15s}
.music-control.light{--m-line:#0000001a;--m-line-strong:#00000029;--m-ink:#22251f;--m-muted:#5d625a;--m-accent:#7a5c18;--m-focus:#7a5c18;--m-bg:#0000000a;--m-track:#00000020}
.music-control[hidden]{display:none}
.music-control:hover,.music-control:focus-within{border-color:var(--m-line-strong)}
.music-toggle{display:grid;place-items:center;width:28px;height:28px;padding:0;border:0;border-radius:999px;background:transparent;color:inherit;cursor:pointer}
.music-toggle:hover{color:var(--m-ink)}
.music-toggle svg{width:17px;height:17px}
.music-toggle:focus-visible,.music-volume:focus-visible{outline:2px solid var(--m-focus);outline-offset:2px}
.music-volume{-webkit-appearance:none;appearance:none;box-sizing:content-box;width:92px;height:4px;min-height:0;margin:0 4px;padding:0;border:0!important;border-radius:999px;cursor:pointer;
  background:linear-gradient(to right,var(--m-accent) var(--fill),var(--m-track) var(--fill))}
.music-volume::-webkit-slider-thumb{-webkit-appearance:none;width:12px;height:12px;border-radius:50%;background:var(--m-accent);border:0;box-shadow:0 0 0 3px #0000002e}
.music-volume::-moz-range-thumb{width:12px;height:12px;border-radius:50%;background:var(--m-accent);border:0}
.music-control.off .music-volume{--m-accent:var(--m-muted)}
.music-value{min-width:30px;text-align:right;font-variant-numeric:tabular-nums}
@media(max-width:1120px){.music-control{right:22px}.music-volume{width:76px}}
`;

async function waitForBridge() {
  for (let i = 0; i < 100 && !bridge()?.MusicState; i++) await new Promise((r) => setTimeout(r, 100));
  return bridge();
}

async function start() {
  const app = await waitForBridge();
  if (!app?.MusicState) return;
  let state;
  try { state = await app.MusicState(); } catch { return; }
  if (!state?.available) return;

  // A blob URL plays reliably in every webview; custom-scheme media streaming does not.
  let src;
  try {
    const response = await fetch('/music/theme', {cache: 'no-store'});
    if (!response.ok) return;
    src = URL.createObjectURL(await response.blob());
  } catch { return; }

  const audio = new Audio(src);
  audio.loop = true;
  audio.volume = 0;
  let volume = Number.isFinite(state.volume) ? state.volume : DEFAULT_VOLUME;
  let muted = !!state.muted;
  let gameRunning = false;
  let fadeTimer = 0;
  let saveTimer = 0;
  let waitingForGesture = false;

  const target = () => (muted || gameRunning ? 0 : volume / 100);

  function fadeTo(to, ms, done) {
    clearInterval(fadeTimer);
    const from = audio.volume;
    const began = performance.now();
    fadeTimer = setInterval(() => {
      const t = ms <= 0 ? 1 : Math.min(1, (performance.now() - began) / ms);
      audio.volume = Math.min(1, Math.max(0, from + (to - from) * t));
      if (t >= 1) { clearInterval(fadeTimer); done?.(); }
    }, 30);
  }

  function apply(ms = 250) {
    const to = target();
    if (to > 0) {
      if (audio.paused) {
        audio.play().then(() => fadeTo(target(), ms)).catch(waitForGesture);
      } else {
        fadeTo(to, ms);
      }
    } else {
      fadeTo(0, ms, () => { if (target() === 0) audio.pause(); });
    }
  }

  // If the webview blocks autoplay, start on the first click or key press anywhere.
  function waitForGesture() {
    if (waitingForGesture) return;
    waitingForGesture = true;
    const resume = () => {
      document.removeEventListener('pointerdown', resume, true);
      document.removeEventListener('keydown', resume, true);
      waitingForGesture = false;
      apply(800);
    };
    document.addEventListener('pointerdown', resume, true);
    document.addEventListener('keydown', resume, true);
  }

  const style = document.createElement('style');
  style.textContent = STYLE;
  document.head.appendChild(style);

  const control = document.createElement('div');
  control.className = 'music-control';
  control.title = state.track ? `Launcher music: ${state.track}` : 'Launcher music';
  control.innerHTML = '<button type="button" class="music-toggle"></button>' +
    '<input type="range" class="music-volume" min="0" max="100" step="1" aria-label="Music volume">' +
    '<output class="music-value" aria-hidden="true"></output>';
  const toggle = control.querySelector('.music-toggle');
  const slider = control.querySelector('.music-volume');
  const value = control.querySelector('.music-value');
  document.body.appendChild(control);

  function render() {
    const off = muted || volume === 0;
    control.classList.toggle('off', off);
    toggle.innerHTML = off ? ICON_OFF : ICON_ON;
    toggle.setAttribute('aria-label', muted ? 'Unmute music' : 'Mute music');
    toggle.setAttribute('aria-pressed', String(muted));
    slider.value = String(volume);
    slider.style.setProperty('--fill', `${volume}%`);
    slider.setAttribute('aria-valuetext', muted ? `${volume}%, muted` : `${volume}%`);
    value.textContent = `${volume}%`;
  }

  const saveVolume = () => { app.SetMusicVolume(volume).catch(() => {}); };

  slider.addEventListener('input', () => {
    volume = Number(slider.value);
    if (muted && volume > 0) { muted = false; app.SetMusicMuted(false).catch(() => {}); }
    render();
    apply(80);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveVolume, 300);
  });
  slider.addEventListener('change', () => { clearTimeout(saveTimer); saveVolume(); });

  toggle.addEventListener('click', () => {
    if (muted || volume === 0) {
      muted = false;
      if (volume === 0) { volume = DEFAULT_VOLUME; saveVolume(); }
    } else {
      muted = true;
    }
    app.SetMusicMuted(muted).catch(() => {});
    render();
    apply(400);
  });

  // Fade out while the game runs and back in when it ends.
  window.runtime?.EventsOn?.('worker', (message) => {
    const name = message?.event;
    if (name === 'started') { gameRunning = true; apply(1200); }
    if (name === 'done' || name === 'disconnected') { gameRunning = false; apply(2000); }
  });

  // Follow the main UI: show only beside the top bar and match its light/dark treatment.
  const light = window.matchMedia('(prefers-color-scheme: light)');
  function follow() {
    const shell = document.querySelector('.shell');
    control.hidden = !document.querySelector('.topbar');
    control.classList.toggle('light', light.matches && !!shell && !shell.classList.contains('is-home'));
    reserve();
  }
  // Keep the search box clear of the control: reserve its width plus the top bar's own gap.
  function reserve() {
    const bar = document.querySelector('.topbar');
    if (!bar || control.hidden) return;
    const gap = parseFloat(getComputedStyle(bar).columnGap) || 16;
    const right = parseFloat(getComputedStyle(control).right) || 0;
    const width = Math.ceil(control.getBoundingClientRect().width + right + gap);
    if (document.documentElement.style.getPropertyValue('--music-reserve') !== `${width}px`) {
      document.documentElement.style.setProperty('--music-reserve', `${width}px`);
    }
  }
  new ResizeObserver(reserve).observe(control);
  window.addEventListener('resize', reserve);
  new MutationObserver(follow).observe(document.getElementById('app') ?? document.body,
    {childList: true, subtree: true, attributes: true, attributeFilter: ['class']});
  light.addEventListener?.('change', follow);
  follow();

  render();
  apply(1500);
}

start();
