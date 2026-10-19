package updates

import (
	"encoding/json"
	"errors"
	"os"
	"path"
	"path/filepath"
	"strings"
)

type sessionLocation struct {
	Path     string `json:"path"`
	Portable bool   `json:"portable"`
}

func validateSessionLocation(location *sessionLocation) error {
	if location == nil {
		return nil
	}
	name := location.Path
	if name == "" || len(name) > 4096 || strings.ContainsAny(name, "\x00\r\n") {
		return errors.New("invalid recovery player-state path")
	}
	if location.Portable {
		if strings.ContainsAny(name, `\:`) || path.IsAbs(name) || path.Clean(name) != name || name == ".." || strings.HasPrefix(name, "../") {
			return errors.New("portable player state escapes its installation")
		}
	} else if !filepath.IsAbs(filepath.FromSlash(name)) || filepath.ToSlash(filepath.Clean(filepath.FromSlash(name))) != name {
		return errors.New("external player state must use a complete path")
	}
	return nil
}

// BindSession records the original profile before handoff; recovery never guesses
// from a later launch's default state directory.
func (t *Transaction) BindSession(state string) error {
	if t.Phase() != "prepared" || state == "" {
		return errors.New("bind player state before starting the update")
	}
	absolute, err := filepath.Abs(state)
	if err != nil {
		return err
	}
	relative, relErr := filepath.Rel(t.root.Name(), absolute)
	location := sessionLocation{Path: filepath.ToSlash(absolute)}
	if relErr == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		location = sessionLocation{Path: filepath.ToSlash(relative), Portable: true}
	}
	if err = validateSessionLocation(&location); err != nil {
		return err
	}
	if t.record.Session != nil && *t.record.Session != location {
		return errors.New("recovery must keep the original player state")
	}
	previous := t.record.Session
	t.record.Session = &location
	if err = t.saveJournal("prepared"); err != nil {
		t.record.Session = previous
	}
	return err
}

func (t *Transaction) SessionDirectory() (string, error) {
	if t.record.Session == nil {
		return "", errors.New("update journal does not identify the original player state")
	}
	if err := validateSessionLocation(t.record.Session); err != nil {
		return "", err
	}
	if t.record.Session.Portable {
		return filepath.Join(t.root.Name(), filepath.FromSlash(t.record.Session.Path)), nil
	}
	return filepath.FromSlash(t.record.Session.Path), nil
}

// PendingRecovery only inspects startup state; it does not load Python or modify files.
func PendingRecovery(directory string) (bool, string, error) {
	root, err := unlinkedDirectory(directory)
	if err != nil {
		return false, "", err
	}
	err = noLinks(root, journalPath)
	if err == nil {
		_, err = root.Lstat(journalPath)
	}
	root.Close()
	if os.IsNotExist(err) {
		return false, "", nil
	}
	if err != nil {
		return false, "", err
	}
	t, err := OpenTransaction(directory)
	if err != nil {
		return false, "", err
	}
	defer t.Close()
	if t.Phase() == "applied" || t.Phase() == "rolled_back" {
		return false, "", nil
	}
	state, err := t.SessionDirectory()
	if err != nil {
		return false, "", err
	}
	return true, state, nil
}

// JournalPhase reads the recorded phase without taking the installation lock, so a
// caller can refuse work on a clean installation without creating updater files.
func JournalPhase(directory string) (string, bool, error) {
	root, err := unlinkedDirectory(directory)
	if err != nil {
		return "", false, err
	}
	defer root.Close()
	err = noLinks(root, journalPath)
	if err == nil {
		_, err = root.Lstat(journalPath)
	}
	if os.IsNotExist(err) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	body, err := readSmall(root, journalPath)
	if err != nil {
		return "", false, err
	}
	var record journal
	if err = json.Unmarshal(body, &record); err != nil {
		return "", false, err
	}
	if err = validateJournal(record); err != nil {
		return "", false, err
	}
	return record.Phase, true, nil
}
