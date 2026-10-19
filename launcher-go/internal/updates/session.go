package updates

import (
	"errors"
	"fmt"
	"os"
	"path"
	"path/filepath"
)

// LockSession uses the existing Python backend's OS-owned session.lock. Keep the
// returned file open across process handoff, replacement and rollback.
func LockSession(state string) (*os.File, error) {
	if state == "" {
		return nil, errors.New("player state directory is required")
	}
	absolute, err := filepath.Abs(state)
	if err != nil {
		return nil, err
	}
	parent := absolute
	for {
		_, err = os.Lstat(parent)
		if !os.IsNotExist(err) {
			break
		}
		next := filepath.Dir(parent)
		if next == parent {
			return nil, err
		}
		parent = next
	}
	if err != nil {
		return nil, err
	}
	root, err := unlinkedDirectory(parent)
	if err != nil {
		return nil, err
	}
	defer root.Close()
	relative, err := filepath.Rel(parent, absolute)
	if err != nil {
		return nil, err
	}
	relative = filepath.ToSlash(relative)
	name := path.Join(relative, "session.lock")
	if err = noLinks(root, name); err != nil {
		return nil, err
	}
	if err = root.MkdirAll(relative, 0700); err != nil {
		return nil, err
	}
	file, err := root.OpenFile(name, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = lockFile(file); err != nil {
		file.Close()
		return nil, fmt.Errorf("The Order is already running or being prepared: %w", err)
	}
	return file, nil
}
