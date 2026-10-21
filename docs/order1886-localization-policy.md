# Launcher localization policy: what gets translated and what stays English

Issue [#8](https://github.com/JulioCacko/The-Order-1886_pc/issues/8) asks for thirteen UI
languages. `launcher/order1886_lang_data.py` already carried 178 strings from the old Tk
launcher in eleven languages' worth of machine translation, and
`launcher/order1886_lang_ui.py` catalogued the 261 strings the Go frontend and the settings
catalogue show, all of which fell back to English. This page states the rule for turning
the second catalogue into real translations, so the next translator does not have to
guess which half of it is fair game.

Owner: `launcher/order1886_lang_ui_translations.py`. It holds
`{locale: {english_key: translated_text}}` and nothing else.

## The rule

A string is translated when a player who cannot read English would otherwise be stuck or
misled by it, **and** a wrong rendering could not send them down the wrong path. Everything
else stays English until a person who speaks the language owns the wording.

**INCLUDE** — the reader's first-contact text:

- page titles and navigation or breadcrumb words (`Achievements`, `Updates`,
  `Main navigation`);
- section headings on the settings pages (`Game installation`, `Installation tools`,
  `Launch configuration`, `Session log`, `Player data`, `Save backups`);
- button labels, action verbs and their confirmation titles (`Cancel`, `Download update`,
  `Install and restart?`, `Reset section?`, `Restore and play`, `Stop and close`,
  `View releases`);
- short state words and one-clause status lines (`On`, `Off`, `Default`, `Completed`,
  `Unlocked`, `Unavailable`, `uncapped`, `Downloading`, `Ready to install`,
  `Update available`, `Update failed`);
- field labels that are short and unambiguous (`Game frame rate`, `Motion blur`,
  `Film grain`, `Depth of field`, `Chromatic aberration`,
  `Mouse camera`, `Mouse sensitivity`, `Invert vertical camera`, `Controller vibration`,
  `Keyboard buttons`, `Controller buttons`);
- the graphics-preset level names that are ordinary words (`Quality`, `Balanced`).

**EXCLUDE** — and this half is a decision, not a to-do list:

- **Field descriptions.** They explain what a setting does and what it does not do
  (`Limits how often the runtime presents, not how fast the engine runs (#14)…`). A
  mistranslation here changes the meaning of the control.
- **Availability reasons and blocked-choice reasons.** They state why something is not
  available yet, usually with an issue number. Paraphrasing them turns "not qualified
  yet" into "broken" or "supported".
- **Warning paragraphs and confirmations of consequences.** Restoring a save, closing a
  session, rolling back an update: the reader has to be certain what will happen before
  clicking.
- **Any string carrying a technical term whose mistranslation misleads**: `HTILE`, `FSR`,
  `DLSS`, `XeSS`, `PSSR`, `VSync`, `VBlank`, `APP_VER`, `shader`, `readback`,
  `frame generation`, `GPU`, `CPU`. A translated GPU-readback policy is a guess dressed
  as documentation. English is the honest fallback when a player is troubleshooting, and
  `EXCLUDED_TECHNICAL_TERMS` in the module is the enforcement of that list.
- **Strings whose conventional rendering *is* the English word.** `System` is `System` in
  German and Polish. `untranslated()` measures "the value equals the key", so a correct
  translation would be reported as missing, and every later attempt to fix that report
  would hide a real gap. Identity translations are simply not expressed by this catalogue.
- **Language endonyms** (`Deutsch`, `English`, `Español`, `日本語`, …). They are already
  correct in every language; translating them would be the error.
- **Counted fragments** (`installed achievements earned`, `matching options`). They are
  glued to a number, and the plural rules they need are per locale, not per table entry.
- **Creative copy** (`Your game. Your settings. Ready when you are.`). A tagline needs a
  writer, not a catalogue entry.
- **Ambiguous one-word labels** (`Framing`, `Native`). Both could be read as composition
  or as a resolution claim, and a wrong guess is worse than English.

74 of the 274 UI keys are translated. The remaining 200 are English in all twelve
non-English languages on purpose, and their reasons are the classes above.

## The translated keys

`Achievements`, `Additional modes`, `Balanced`, `Cancel`, `Cancel download`,
`Checking for updates…`, `Choose your extracted game folder`, `Chromatic aberration`,
`Completed`, `Configure graphics`, `Controller buttons`, `Controller vibration`,
`Default`, `Depth of field`, `Download update`, `Downloading`, `Film grain`,
`Game & Content`, `Game frame rate`, `Game installation`, `Install and restart`,
`Install and restart?`, `Installation tools`, `Invert vertical camera`,
`Keyboard buttons`, `Launch configuration`, `Main navigation`, `Manage game and saves`,
`Motion blur`, `Mouse camera`, `Mouse sensitivity`, `No session yet`,
`No update checked yet`, `Off`, `On`, `Open installation`, `Open logs`,
`Open player data`, `Open updates`, `Player data`, `Quality`, `Ready to install`,
`Report an issue`, `Reset`, `Reset section`, `Reset section?`, `Restore`,
`Restore and play`, `Restore previous version`, `Restore the previous version?`,
`Restoring the previous version`, `Return to Whitechapel`, `Roll back this update`,
`Save backups`, `Saving settings…`, `Search all settings`, `Search settings`,
`Selected backup`, `Session log`, `Session output`, `Starting session…`, `Stop`,
`Stop and close`, `Stop and close?`, `Timing`, `Trophy`, `Unavailable`, `Unlocked`,
`Update available`, `Update failed`, `Updates`, `Use current saves`, `View releases`,
`uncapped`.

Languages: `ru`, `ar`, `es`, `pt`, `fr`, `de`, `it`, `pl`, `tr`, `zh`, `ja`, `ko` — the
twelve non-English entries of `LANGUAGES`.

## Translation quality rules

1. **Never translate the product name.** `The Order: 1886` stays byte-identical in every
   sentence, and no word inside it is translated. The subset contains no such string
   today; the rule exists for the first one that does.
2. **Keep placeholders and format specifiers exactly.** `{path}`, `{code}` and anything
   `str.format` consumes must survive unchanged, including their conversion. There are
   none in this subset — checked, not assumed: `tests/test_order1886_localization.py`
   compares the format fields of every key with its translation in every language, and
   `tests/test_order1886_lang_ui_translations.py` rejects a placeholder that the English
   key does not have.
3. **Stay short enough for the existing UI.** A button label is a button label: the tests
   cap a value at 48 characters, and `tests/test_order1886_localization.py` already
   checks that a page button still fits its 180 px slot in Tk. Prefer the shorter
   conventional wording (`Abbrechen`, `İptal`, `取消`) over a longer faithful one.
4. **Prefer the conventional system term over a literal rendering.** `Cancel` is
   `Abbrechen`, not "Rückgängig machen"; `Off`/`On` are `Aus`/`Ein`, `Çıkış`-style
   literalism is wrong; `uncapped` is `sans limite` / `без ограничения` / `无上限`, not a
   word-for-word "ohne Kappe".
5. **Match the register of the existing tables.** `launcher/order1886_lang_data.py` uses
   a neutral, capitalized, sentence-case UI register with no trailing full stop on
   labels; these entries follow it, including the German noun capitalization
   (`Extrahierten Spielordner wählen`) and the Japanese `です・ます` form the older table
   already uses for prompts.
6. **Keep the punctuation the key relies on.** A key ending in `…` keeps its ellipsis, and
   a key ending in `?` keeps a question mark, which is `？` in Chinese and `؟` in Arabic.
   The tests read those marks.

## Honesty

**These translations are machine-assisted and no native speaker has reviewed them.** That
is the same standing as every other entry in `launcher/order1886_lang_data.py`, whose
docstring says as much. Nothing here is a claim of review; a wording that looks odd is a
candidate for a review pass, and the file is the place to fix it in one line.

## How it is enforced

- `tests/test_order1886_lang_ui_translations.py` requires every key to exist in `UI_KEYS`,
  every locale to be one of `LANGUAGES` minus `en`, every locale to carry the same keys,
  and every value to be non-empty, different from the English text, free of the excluded
  technical terms, free of foreign placeholders, and punctuated like its key. Its
  `problems()` helper is the rule set: an empty string or a copied English label fails on
  the first rule it breaks.
- `tests/test_order1886_ui_catalog.py` pins the remaining count per language, so a new
  English-only UI string cannot slip in unnoticed, and `untranslated()` keeps counting
  only keys that are still English: 186 of 261 for each of the twelve languages today.
- `tests/test_order1886_localization.py` still checks all thirteen catalogues for blanks,
  format fields and donor-game leftovers.
