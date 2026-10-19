/** The catalogued patch recipes the worker reports, as a read-only list. */
export type CatalogueRow = {
  id: string; title: string; description: string;
  builtin: boolean; available: boolean; reason: string; warning: string;
};

export function patchCatalogue(rows: CatalogueRow[] | undefined | null,
                                escape: (value: unknown) => string) {
  if (!rows || rows.length === 0) return '';
  const items = rows.map(row => `<li>
   <strong>${escape(row.title)}</strong>${row.builtin ? ' · configured elsewhere' : ''}
   <p>${escape(row.description)}</p>
   ${row.reason ? `<p class="availability">${escape(row.reason)}</p>` : ''}
   ${row.warning ? `<p class="availability">${escape(row.warning)}</p>` : ''}</li>`).join('');
  return `<section class="utility-section"><h2>Catalogued patches</h2>
  <p class="quiet-copy">Recipes that edit the prepared image. A recipe applies only to the
  exact build it was verified against, and the game folder is never modified.</p>
  <ol class="trophy-list">${items}</ol></section>`;
}
