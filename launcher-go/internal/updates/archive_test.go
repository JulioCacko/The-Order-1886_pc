package updates

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"testing"
)

// These fixtures exercise the actual archive parser and filesystem, not an installer mock.
func digest(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func packageFixture(t *testing.T, change func(map[string][]byte, map[string]any)) (string, Identity) {
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
	var entries []map[string]string
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
	path := filepath.Join(t.TempDir(), "package.zip")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	w := zip.NewWriter(f)
	for name, data := range files {
		entry, err := w.Create("The Order 1886/" + name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = entry.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err = w.Close(); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return path, Identity{Size: int64(len(data)), SHA256: digest(data), SourceRevision: strings.Repeat("a", 40), RuntimeSHA256: digest(runtime)}
}

func TestStageVerifiedPackageAtUnicodePath(t *testing.T) {
	archive, identity := packageFixture(t, nil)
	dest := filepath.Join(t.TempDir(), "Atualização 游戏")
	manifest, err := StageArchive(context.Background(), archive, dest, identity)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.SourceRevision != identity.SourceRevision {
		t.Fatal("lost source identity")
	}
	got, err := os.ReadFile(filepath.Join(dest, filepath.FromSlash(pkgpath.Runtime())))
	if err != nil || string(got) != "runtime-6" {
		t.Fatalf("wrong runtime: %q %v", got, err)
	}
	got, err = os.ReadFile(filepath.Join(dest, "package-manifest.json"))
	if err != nil || !strings.Contains(string(got), identity.SourceRevision) {
		t.Fatal("manifest not retained")
	}
}

func TestRejectArchiveIntegrityOrProvenanceMismatch(t *testing.T) {
	for _, kind := range []string{"digest", "size", "source", "runtime", "dirty", "product", "abi", "payload", "missing", "extra", "duplicate-manifest", "protected"} {
		t.Run(kind, func(t *testing.T) {
			archive, identity := packageFixture(t, func(files map[string][]byte, m map[string]any) {
				switch kind {
				case "dirty":
					m["source_dirty"] = true
				case "product":
					m["product"] = "Other game"
				case "abi":
					m["runtime_build"].(map[string]any)["runtime_abi"] = "other-1"
				case "payload":
					files["_internal/library.dll"] = []byte("tampered")
				case "missing":
					delete(files, pkgpath.Worker())
				case "extra":
					files["unexpected.exe"] = []byte("unowned")
				case "duplicate-manifest":
					m["files"] = append(m["files"].([]map[string]string), map[string]string{"path": "BIN/order1886-worker.exe", "sha256": digest(files[pkgpath.Worker()])})
				case "protected":
					files["user/order1886/settings.json"] = []byte("{}")
				}
			})
			switch kind {
			case "digest":
				identity.SHA256 = strings.Repeat("0", 64)
			case "size":
				identity.Size++
			case "source":
				identity.SourceRevision = strings.Repeat("b", 40)
			case "runtime":
				identity.RuntimeSHA256 = strings.Repeat("0", 64)
			}
			dest := filepath.Join(t.TempDir(), "staged")
			if _, err := StageArchive(context.Background(), archive, dest, identity); err == nil {
				t.Fatal("accepted invalid package")
			}
			if _, err := os.Lstat(dest); !os.IsNotExist(err) {
				t.Fatalf("failed stage left payload: %v", err)
			}
		})
	}
}

func TestRejectWindowsArchiveAliasesAndLinks(t *testing.T) {
	for _, name := range []string{"../outside.exe", "/absolute.exe", "C:/drive.exe", "bin\\escape.exe", "bin/../escape.exe", "bin/file:stream", "bin/file.", "bin/file ", "bin/CON.txt", "bin/COM1", "bin/COM¹.txt", "bin//empty.exe", "bin/./dot.exe", "USER/settings.json", "mods/config.json", "patches/config.json", ".order1886-update/journal.json"} {
		t.Run(name, func(t *testing.T) {
			archive, identity := packageFixture(t, func(files map[string][]byte, _ map[string]any) { files[name] = []byte("bad") })
			if _, err := StageArchive(context.Background(), archive, filepath.Join(t.TempDir(), "stage"), identity); err == nil {
				t.Fatalf("accepted %q", name)
			}
		})
	}
	for _, mode := range []os.FileMode{os.ModeSymlink | 0777, os.ModeNamedPipe | 0600} {
		t.Run(mode.String(), func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "link.zip")
			f, _ := os.Create(path)
			w := zip.NewWriter(f)
			h := &zip.FileHeader{Name: "The Order 1886/bin/link"}
			h.SetMode(mode)
			entry, err := w.CreateHeader(h)
			if err != nil {
				t.Fatal(err)
			}
			entry.Write([]byte("../../outside"))
			w.Close()
			f.Close()
			data, _ := os.ReadFile(path)
			if _, err := StageArchive(context.Background(), path, filepath.Join(t.TempDir(), "stage"), Identity{Size: int64(len(data)), SHA256: digest(data), SourceRevision: strings.Repeat("a", 40), RuntimeSHA256: strings.Repeat("b", 64)}); err == nil {
				t.Fatal("accepted special file")
			}
		})
	}
}

func TestStageNeverOverwritesExistingDirectoryAndHonorsCancellation(t *testing.T) {
	archive, identity := packageFixture(t, nil)
	dest := t.TempDir()
	keep := filepath.Join(dest, "player-data")
	os.WriteFile(keep, []byte("keep"), 0600)
	if _, err := StageArchive(context.Background(), archive, dest, identity); err == nil {
		t.Fatal("accepted existing stage")
	}
	if got, _ := os.ReadFile(keep); string(got) != "keep" {
		t.Fatal("overwrote existing files")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := StageArchive(ctx, archive, filepath.Join(t.TempDir(), "stage"), identity); err == nil {
		t.Fatal("ignored cancellation")
	}
}

func TestStageRejectsCaseAliasedDirectories(t *testing.T) {
	archive, identity := packageFixture(t, func(files map[string][]byte, m map[string]any) {
		files["bin/Library/a.dll"] = []byte("a")
		files["bin/library/b.dll"] = []byte("b")
		m["files"] = append(m["files"].([]map[string]string),
			map[string]string{"path": "bin/Library/a.dll", "sha256": digest([]byte("a"))},
			map[string]string{"path": "bin/library/b.dll", "sha256": digest([]byte("b"))})
	})
	if _, err := StageArchive(context.Background(), archive, filepath.Join(t.TempDir(), "stage"), identity); err == nil {
		t.Fatal("accepted Windows directory aliases")
	}
}

func TestStageRejectsSymlinkMarkedAsDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "link.zip")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	w := zip.NewWriter(f)
	h := &zip.FileHeader{Name: "The Order 1886/"}
	h.SetMode(os.ModeSymlink | 0777)
	h.ExternalAttrs |= 0x10
	entry, err := w.CreateHeader(h)
	if err != nil {
		t.Fatal(err)
	}
	entry.Write([]byte("../outside"))
	w.Close()
	f.Close()
	data, _ := os.ReadFile(path)
	if _, err := StageArchive(context.Background(), path, filepath.Join(t.TempDir(), "stage"), Identity{Size: int64(len(data)), SHA256: digest(data), SourceRevision: strings.Repeat("a", 40), RuntimeSHA256: strings.Repeat("b", 64)}); err == nil || !strings.Contains(err.Error(), "special") {
		t.Fatalf("directory symlink was not rejected as a special file: %v", err)
	}
}

func TestStageRejectsOversizedExpandedPayloadBeforeExtraction(t *testing.T) {
	for _, total := range []bool{false, true} {
		t.Run(map[bool]string{false: "one-file", true: "total-size"}[total], func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "large.zip")
			f, err := os.Create(path)
			if err != nil {
				t.Fatal(err)
			}
			w := zip.NewWriter(f)
			count, size := 1, uint64(maxFile+1)
			if total {
				count, size = 5, maxFile
			}
			for i := 0; i < count; i++ {
				h := &zip.FileHeader{Name: archiveRoot + "bin/large" + string(rune('a'+i)), Method: zip.Store, UncompressedSize64: size}
				if _, err = w.CreateRaw(h); err != nil {
					t.Fatal(err)
				}
			}
			w.Close()
			f.Close()
			data, _ := os.ReadFile(path)
			dest := filepath.Join(t.TempDir(), "stage")
			_, err = StageArchive(context.Background(), path, dest, Identity{Size: int64(len(data)), SHA256: digest(data), SourceRevision: strings.Repeat("a", 40), RuntimeSHA256: strings.Repeat("b", 64)})
			if err == nil || !strings.Contains(err.Error(), "size limit") {
				t.Fatalf("did not reject oversized payload: %v", err)
			}
			if _, err = os.Stat(dest); !os.IsNotExist(err) {
				t.Fatal("created stage for oversized payload")
			}
		})
	}
}
