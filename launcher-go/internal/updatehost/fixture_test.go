package updatehost

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"testing"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updates"
)

func digest(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func workspaceName() string { return workspace }

// TransactionFixture builds an installed Go package that still contains the
// retired legacy entry point, plus a staged replacement that removes it.
func TransactionFixture(t *testing.T) (string, Candidate) {
	t.Helper()
	base := t.TempDir()
	installation := filepath.Join(base, "Instalação 游戏")
	stage := filepath.Join(base, "stage")
	installedZip, identity := buildPackage(t, nil)
	if _, err := updates.StageArchive(context.Background(), installedZip, installation, identity); err != nil {
		t.Fatal(err)
	}
	stagedZip, staged := buildPackage(t, func(files map[string][]byte, manifest map[string]any) {
		manifest["source_revision"] = strings.Repeat("b", 40)
		manifest["update_abi"] = "order1886-update-2"
		files[pkgpath.Launcher()] = []byte("launcher-7")
		files[pkgpath.Play()] = []byte("launcher-7")
		files[pkgpath.Worker()] = []byte("worker-7")
		files["_internal/library.dll"] = []byte("library-7")
		delete(files, "The Order 1886 Legacy.exe")
		delete(files, "notices/LICENSE.txt")
		files["notices/new-license.txt"] = []byte("new-license")
		var list []map[string]string
		for name, data := range files {
			list = append(list, map[string]string{"path": name, "sha256": digest(data)})
		}
		manifest["files"] = list
	})
	staged.SourceRevision = strings.Repeat("b", 40)
	verified, err := updates.StageArchive(context.Background(), stagedZip, stage, staged)
	if err != nil {
		t.Fatal(err)
	}
	staged.ManifestSHA256 = verified.SHA256
	for name, data := range map[string]string{
		"user/order1886/settings.json":          `{"future":73,"mods_enabled":false}`,
		"user/order1886/savedata/slot1/Profile": "complete-profile",
		"mods/lighting/content.bin":             "player-mod",
		"player notes.txt":                      "keep-this-file",
	} {
		path := filepath.Join(installation, filepath.FromSlash(name))
		if err = os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(path, []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return installation, Candidate{Stage: stage, Identity: staged}
}

func buildPackage(t *testing.T, change func(map[string][]byte, map[string]any)) (string, updates.Identity) {
	t.Helper()
	runtime := []byte("runtime-6")
	files := map[string][]byte{
		pkgpath.Launcher():          []byte("launcher-6"),
		pkgpath.Play():              []byte("launcher-6"),
		"The Order 1886 Legacy.exe": []byte("legacy-6"),
		pkgpath.Worker():            []byte("worker-6"),
		pkgpath.Runtime():           runtime,
		"bin/runtime-build.json":    []byte(`{"runtime_abi":"order1886-native-1","game_profile":"order1886","runtime_sha256":"` + digest(runtime) + `"}`),
		"_internal/library.dll":     []byte("library-6"),
		"notices/LICENSE.txt":       []byte("license"),
	}
	manifest := map[string]any{
		"product": "The Order: 1886", "launcher": "Go / Wails v2.17.0",
		"source_revision": strings.Repeat("a", 40), "source_dirty": false,
		"runtime_sha256": digest(runtime),
		"runtime_build":  map[string]any{"runtime_abi": "order1886-native-1", "game_profile": "order1886", "runtime_sha256": digest(runtime)},
	}
	entries := make([]map[string]string, 0, len(files))
	for name, data := range files {
		entries = append(entries, map[string]string{"path": name, "sha256": digest(data)})
	}
	manifest["files"] = entries
	if change != nil {
		change(files, manifest)
	}
	body, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	files["package-manifest.json"] = append([]byte{0xef, 0xbb, 0xbf}, body...)
	name := filepath.Join(t.TempDir(), "package.zip")
	file, err := os.Create(name)
	if err != nil {
		t.Fatal(err)
	}
	writer := zip.NewWriter(file)
	for entry, data := range files {
		target, err := writer.Create("The Order 1886/" + entry)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = target.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err = writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err = file.Close(); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(name)
	if err != nil {
		t.Fatal(err)
	}
	return name, updates.Identity{
		Size:           int64(len(raw)),
		SHA256:         digest(raw),
		SourceRevision: strings.Repeat("a", 40),
		RuntimeSHA256:  digest(runtime),
	}
}

// Snapshot records the whole installation except the updater workspace.
func Snapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	files := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			if entry.Name() == workspace {
				return filepath.SkipDir
			}
			return nil
		}
		name, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		files[filepath.ToSlash(name)] = string(data)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return files
}

// InterruptApply replaces files and stops before the journal records completion,
// which is the state a real power loss or kill leaves behind.
func InterruptApply(installation string) error {
	tx, err := updates.OpenTransaction(installation)
	if err != nil {
		return err
	}
	defer tx.Close()
	interrupted := false
	func() {
		defer func() {
			if recover() != nil {
				interrupted = true
			}
		}()
		_ = tx.Apply(context.Background(), func(done, total int) {
			if done == 2 {
				panic("interrupted")
			}
		})
	}()
	if !interrupted {
		return errors.New("update completed instead of being interrupted")
	}
	return nil
}

// snapshotDiff lists the files that differ between two recorded installations.
func snapshotDiff(before, after map[string]string) []string {
	var changed []string
	for name, want := range before {
		if got, ok := after[name]; !ok {
			changed = append(changed, "missing "+name)
		} else if got != want {
			changed = append(changed, "changed "+name)
		}
	}
	for name := range after {
		if _, ok := before[name]; !ok {
			changed = append(changed, "extra "+name)
		}
	}
	sort.Strings(changed)
	return changed
}

// corruptBackups makes the retained previous payload unusable, which is how a
// rollback legitimately fails.
func corruptBackups(t *testing.T, installation string) {
	t.Helper()
	body, err := os.ReadFile(filepath.Join(installation, workspace, "journal.json"))
	if err != nil {
		t.Fatal(err)
	}
	var journal struct {
		Directory string `json:"directory"`
	}
	if err = json.Unmarshal(body, &journal); err != nil {
		t.Fatal(err)
	}
	previous := filepath.Join(installation, filepath.FromSlash(journal.Directory), "previous", pkgpath.Launcher())
	if err = os.WriteFile(previous, []byte("broken-backup"), 0o600); err != nil {
		t.Fatal(err)
	}
}
