package pkgpath

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestNoPlatformNamesOutsideThisPackage keeps the class of defect that broke the Linux package from
// coming back: four separate places spelled out `bin/order1886-worker.exe` and the entry points, so a
// Linux installation could not start its worker, refused its own package during an update, and
// relaunched a file that does not exist. Every such name must come from here.
func TestNoPlatformNamesOutsideThisPackage(t *testing.T) {
	root, err := moduleRoot()
	if err != nil {
		t.Fatal(err)
	}
	forbidden := []string{`"The Order 1886.exe"`, `"Play The Order 1886.exe"`, `"bin/order1886-worker.exe"`,
		`"bin/order1886-runtime.exe"`}
	thisFile := filepath.Join(root, "internal", "pkgpath", "pkgpath.go")
	var offenders []string
	err = filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			if entry.Name() == "frontend" || entry.Name() == "node_modules" || entry.Name() == "build" {
				return fs.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		if path == thisFile {
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		text := string(data)
		for _, needle := range forbidden {
			if strings.Contains(text, needle) {
				relative, _ := filepath.Rel(root, path)
				offenders = append(offenders, relative+": "+needle)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(offenders) > 0 {
		t.Fatalf("platform file names outside internal/pkgpath:\n%s", strings.Join(offenders, "\n"))
	}
}

func moduleRoot() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if _, statErr := os.Stat(filepath.Join(dir, "go.mod")); statErr == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", os.ErrNotExist
		}
		dir = parent
	}
}
