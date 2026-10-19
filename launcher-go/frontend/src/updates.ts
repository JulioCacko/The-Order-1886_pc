export type UpdateStatus = {
  state: string; version: string; downloaded: number; total: number;
  channel: string; automatic: boolean; error: string;
  recovery_pending: boolean; recovery_blocked: boolean; rollback_available: boolean;
  install_available: boolean; install_reason: string;
};

export function parseUpdate(raw: string): UpdateStatus {
  const value = JSON.parse(raw) as Partial<UpdateStatus>;
  return {
    state: value.state ?? 'idle', version: value.version ?? '', downloaded: value.downloaded ?? 0,
    total: value.total ?? 0, channel: value.channel ?? 'preview', automatic: value.automatic ?? false,
    error: value.error ?? '', recovery_pending: value.recovery_pending ?? false,
    recovery_blocked: value.recovery_blocked ?? false,
    rollback_available: value.rollback_available ?? false,
    install_available: value.install_available ?? false, install_reason: value.install_reason ?? '',
  };
}

function percent(status: UpdateStatus) {
  if (!status.total) return 0;
  return Math.min(100, Math.round((status.downloaded / status.total) * 100));
}

function megabytes(bytes: number) {
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/** The one place that decides which update action is offered and why. */
export function updateHeadline(status: UpdateStatus | null, t: (value: string) => string) {
  if (!status) return t('Update state unavailable');
  if (status.recovery_blocked) return t('An interrupted update needs your decision');
  if (status.recovery_pending) return t('Restoring the previous version');  switch (status.state) {
    case 'checking': return t('Checking for updates…');
    case 'available': return `${t('Update available')}: ${status.version}`;
    case 'downloading': return `${t('Downloading')} ${percent(status)}%`;
    case 'staged': return `${t('Ready to install')}: ${status.version}`;
    case 'failed': return t('Update failed');
    default: return t('No update checked yet');
  }
}

export function updateSection(status: UpdateStatus | null, t: (value: string) => string,
                               escape: (value: unknown) => string, disabled: boolean) {
  const busy = disabled || status === null;
  const blocked = status?.recovery_blocked ?? false;
  const recoverable = blocked || (status?.recovery_pending ?? false);
  const rollbackable = status?.rollback_available ?? false;
  const actions: string[] = [];
  actions.push(`<button data-action="update.check"${busy ? ' disabled' : ''}>${escape(t('Check for updates'))}</button>`);
  if (status?.state === 'available') {
    actions.push(`<button data-action="update.download"${busy ? ' disabled' : ''}>${escape(t('Download update'))}</button>`);
  }
  if (status?.state === 'downloading') {
    actions.push(`<button data-action="update.cancel"${disabled ? ' disabled' : ''}>${escape(t('Cancel download'))}</button>`);
  }
  if (status?.state === 'staged' && status.install_available) {
    actions.push(`<button class="danger" data-action="update.install"${busy ? ' disabled' : ''}>${escape(t('Install and restart'))}</button>`);
  }
  if (recoverable) {
    actions.push(`<button class="danger" data-action="update.restore"${disabled ? ' disabled' : ''}>${escape(t('Restore previous version'))}</button>`);
  } else if (rollbackable) {
    actions.push(`<button data-action="update.restore"${disabled ? ' disabled' : ''}>${escape(t('Roll back this update'))}</button>`);
  }
  actions.push(`<button data-link="releases">${escape(t('View releases'))}</button>`);
  const progress = status?.state === 'downloading'
    ? `<progress value="${status.downloaded}" max="${status.total || 1}"></progress>
       <p class="quiet-copy">${escape(megabytes(status.downloaded))} / ${escape(megabytes(status.total))}</p>` : '';
  const reason = status?.state === 'staged' && !status.install_available
    ? `<p class="availability">${escape(t(status.install_reason))}</p>` : '';
  const error = status?.error ? `<p role="alert" class="error">${escape(status.error)}</p>` : '';
  return `<h2>${escape(t('Updates'))}</h2>
  <p><strong>${escape(updateHeadline(status, t))}</strong></p>
  <p class="quiet-copy">${escape(t('Channel'))}: ${escape(t(status?.channel === 'stable' ? 'Stable — released builds only' : 'Preview — every published Go preview'))}
  · ${escape(t(status?.automatic ? 'Checked on start' : 'Checked only when you ask'))}</p>
  <p class="quiet-copy">${escape(t('An update replaces only launcher files. Saves, settings, mods and patches are preserved, and an interrupted update is restored before the launcher starts.'))}</p>
  ${progress}${reason}${error}
  <div class="actions">${actions.join('')}</div>`;
}
