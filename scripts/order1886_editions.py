# SPDX-License-Identifier: GPL-2.0-or-later
"""The editions of The Order: 1886 the launcher accepts (#113).

Every regional release of update 01.02 carries the same executable code: the published
GoldHEN patch (patches/TheOrder1886-Orbis.xml) lists all six title IDs at the same addresses,
and so do the two other ports that run them. Nothing here trusts that claim on its own: every
recipe still checks the original instruction bytes at each site before it edits a prepared
copy. Only CUSA00076 has been run here with a real dump; the others are experimental.

All six keep their saves under the same INSTALL_DIR_SAVEDATA (CUSA00035), so a save works in
every edition without migration.
"""

VERIFIED_TITLE_ID = 'CUSA00076'
TITLE_IDS = (VERIFIED_TITLE_ID, 'CUSA00035', 'CUSA00070', 'CUSA00100', 'CUSA00670', 'CUSA00785')
# OrbisSystemParamLanguage 17 (Brazilian Portuguese) has assets only in CUSA00785. These
# editions lack it and would fall back to English, so they get 7 (Portugal Portuguese).
LANGUAGE_FALLBACKS = {'CUSA00035': {17: 7}, 'CUSA00070': {17: 7}, 'CUSA00076': {17: 7}}


def supported(title_id):
    return title_id in TITLE_IDS


def experimental(title_id):
    """True for an accepted edition that has not been run here with a real dump."""
    return supported(title_id) and title_id != VERIFIED_TITLE_ID


def system_language(title_id, language):
    """The system language this edition can show: the selected one, or its closest substitute."""
    return LANGUAGE_FALLBACKS.get(title_id, {}).get(language, language)
