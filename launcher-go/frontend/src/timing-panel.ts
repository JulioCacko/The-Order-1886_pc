/** The resolved timing the worker reports: a diagnostic, never a measurement. */
export type Timing = {
  engine_fps: number; fps_cap: number; fps_limit: number | null;
  vblank_hz: number; vsync: boolean; error?: string;
};

export function timingPanel(timing: Timing | undefined | null,
                            t: (value: string) => string,
                            escape: (value: unknown) => string) {
  if (!timing) return '';
  if (timing.error) {
    return `<section class="utility-section"><h2>${escape(t('Timing'))}</h2>` +
           `<p role="alert" class="error">${escape(timing.error)}</p></section>`;
  }
  const limit = timing.fps_limit === null ? t('uncapped') : `${timing.fps_limit} FPS`;
  const vblank = timing.vblank_hz ? `${timing.vblank_hz} Hz` : t('uncapped');
  return `<section class="utility-section"><h2>${escape(t('Resolved timing'))}</h2><dl class="locations">
 <dt>${escape(t('Game frame rate'))}</dt><dd>${timing.engine_fps} FPS</dd>
 <dt>${escape(t('Presentation cap'))}</dt><dd>${timing.fps_cap} FPS</dd>
 <dt>${escape(t('Effective limit'))}</dt><dd>${escape(limit)}</dd>
 <dt>${escape(t('VBlank'))}</dt><dd>${escape(vblank)}</dd>
 <dt>${escape(t('VSync'))}</dt><dd>${escape(timing.vsync ? t('On') : t('Off'))}</dd></dl>
 <p class="quiet-copy">${escape(t('These are the values the next launch will ask for, not measured performance.'))}</p></section>`;
}
