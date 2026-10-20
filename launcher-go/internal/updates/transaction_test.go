package updates

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"sort"
	"strings"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"testing"
	"time"
)

func transactionFixture(t *testing.T) (string, string, Identity) {
	t.Helper()
	archive, identity := packageFixture(t, nil)
	base := t.TempDir()
	installed := filepath.Join(base, "Instalação 游戏")
	stage := filepath.Join(base, "new")
	if _, err := StageArchive(context.Background(), archive, installed, identity); err != nil {
		t.Fatal(err)
	}
	archive, identity = packageFixture(t, func(files map[string][]byte, m map[string]any) {
		m["source_revision"] = strings.Repeat("b", 40)
		m["update_abi"] = "order1886-update-2"
		files[pkgpath.Launcher()] = []byte("launcher-7")
		files[pkgpath.Play()] = []byte("launcher-7")
		files[pkgpath.Worker()] = []byte("worker-7")
		files["_internal/library.dll"] = []byte("library-7")
		delete(files, "notices/LICENSE.txt")
		delete(files, "The Order 1886 Legacy.exe")
		files["notices/new-license.txt"] = []byte("new-license")
		var list []map[string]string
		for name, data := range files {
			list = append(list, map[string]string{"path": name, "sha256": digest(data)})
		}
		m["files"] = list
	})
	identity.SourceRevision = strings.Repeat("b", 40)
	verified, err := StageArchive(context.Background(), archive, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	identity.ManifestSHA256 = verified.SHA256
	for name, data := range map[string]string{
		"user/order1886/settings.json":          `{"future":73,"mods_enabled":false}`,
		"user/order1886/savedata/slot1/Profile": "complete-profile",
		"user/order1886/savedata/slot1/Save":    "chapter-nine",
		"user/order1886/backups/old/Profile":    "older-profile",
		"mods/lighting/content.bin":             "player-mod", "patches/enabled.json": "player-patches",
		"CUSA00076/eboot.bin": "original-game", "player notes.txt": "keep-this-file",
	} {
		path := filepath.Join(installed, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return installed, stage, identity
}

// bindSession records the player profile a prepared update must recover into. Every
// installable transaction requires it, so tests that apply an update bind one.
func bindSession(t *testing.T, tx *Transaction, root string) {
	t.Helper()
	if err := tx.BindSession(filepath.Join(root, "user", "order1886")); err != nil {
		tx.Close()
		t.Fatal(err)
	}
}

func TestJournalNeverCommitsMetadataItCannotRead(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { tx.Close() })
	file := filepath.Join(root, filepath.FromSlash(journalPath))
	before, _ := os.ReadFile(file)
	for i := 0; i < 7000; i++ {
		tx.record.Files = append(tx.record.Files, change{Path: "bin/" + strings.Repeat("long/", 120) + fmt.Sprintf("%05d.dll", i), Old: strings.Repeat("0", 64), New: strings.Repeat("1", 64)})
	}
	sort.Slice(tx.record.Files, func(i, j int) bool { return beforeChange(tx.record.Files[i], tx.record.Files[j]) })
	if err = tx.saveJournal("applying"); err == nil {
		t.Fatal("committed journal exceeding recovery parser limit")
	}
	if got, _ := os.ReadFile(file); string(got) != string(before) {
		t.Fatal("oversized journal replaced recoverable state")
	}
	tx.Close()
	tx, err = OpenTransaction(root)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	if err = tx.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
}

func TestTransactionProcessCrashHelper(t *testing.T) {
	if os.Getenv("ORDER1886_UPDATE_TEST_CHILD") != "1" {
		return
	}
	var identity Identity
	if err := json.Unmarshal([]byte(os.Getenv("ORDER1886_UPDATE_TEST_IDENTITY")), &identity); err != nil {
		t.Fatal(err)
	}
	tx, err := PrepareTransaction(context.Background(), os.Getenv("ORDER1886_UPDATE_TEST_ROOT"), os.Getenv("ORDER1886_UPDATE_TEST_STAGE"), identity)
	if err != nil {
		t.Fatal(err)
	}
	bindSession(t, tx, os.Getenv("ORDER1886_UPDATE_TEST_ROOT"))
	err = tx.Apply(context.Background(), func(done, total int) {
		if done == 3 {
			os.Stdout.WriteString("UPDATE-INTERRUPTION-READY\n")
			var wait [1]byte
			os.Stdin.Read(wait[:])
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Fatal("child updater unexpectedly completed")
}

func TestActualProcessTerminationReleasesLockAndRecovers(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	raw, _ := json.Marshal(identity)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	child := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestTransactionProcessCrashHelper$", "-test.timeout=45s")
	child.Env = append(os.Environ(), "ORDER1886_UPDATE_TEST_CHILD=1", "ORDER1886_UPDATE_TEST_ROOT="+root, "ORDER1886_UPDATE_TEST_STAGE="+stage, "ORDER1886_UPDATE_TEST_IDENTITY="+string(raw))
	var stderr bytes.Buffer
	child.Stderr = &stderr
	stdin, err := child.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	defer stdin.Close()
	stdout, err := child.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err = child.Start(); err != nil {
		t.Fatal(err)
	}
	scanner := bufio.NewScanner(stdout)
	if !scanner.Scan() || scanner.Text() != "UPDATE-INTERRUPTION-READY" {
		child.Process.Kill()
		child.Wait()
		t.Fatalf("child did not reach interruption point: %s %s", scanner.Text(), stderr.String())
	}
	if err = child.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	if err = child.Wait(); err == nil {
		t.Fatal("child did not terminate abnormally")
	}
	tx, err := OpenTransaction(root)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	if tx.Phase() != "applying" {
		t.Fatal("process termination lost pending journal")
	}
	if err = tx.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("process termination lost previous package/player files")
	}
}

func installedSnapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	files := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		name, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		if name == ".order1886-update" {
			return filepath.SkipDir
		}
		if entry.IsDir() {
			return nil
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

func TestTransactionUpdatesAndRollsBackOnlyPackageFiles(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("preparing changed the installation")
	}
	bindSession(t, tx, root)
	if err = tx.Apply(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if tx.Phase() != "applied" {
		t.Fatalf("wrong phase %s", tx.Phase())
	}
	after := installedSnapshot(t, root)
	for name, want := range map[string]string{pkgpath.Launcher(): "launcher-7", pkgpath.Play(): "launcher-7", pkgpath.Worker(): "worker-7", "_internal/library.dll": "library-7", "notices/new-license.txt": "new-license"} {
		if after[name] != want {
			t.Fatalf("wrong %s: %q", name, after[name])
		}
	}
	if _, ok := after["notices/LICENSE.txt"]; ok {
		t.Fatal("obsolete owned file remains")
	}
	if _, ok := after["The Order 1886 Legacy.exe"]; ok {
		t.Fatal("retired entry point remains in a Go-only package")
	}
	for name, want := range before {
		if strings.HasPrefix(name, "user/") || strings.HasPrefix(name, "mods/") || strings.HasPrefix(name, "patches/") || strings.HasPrefix(name, "CUSA") || name == "player notes.txt" {
			if after[name] != want {
				t.Fatalf("changed player file %s", name)
			}
		}
	}
	tx.Close()
	tx, err = OpenTransaction(root)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	if err = tx.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("rollback did not restore exact previous installation")
	}
	if tx.Phase() != "rolled_back" {
		t.Fatal("rollback phase not saved")
	}
}

func TestInterruptedTransactionRecoversAtEveryFileBoundary(t *testing.T) {
	for boundary := 1; boundary <= 8; boundary++ {
		t.Run(string(rune('0'+boundary)), func(t *testing.T) {
			root, stage, identity := transactionFixture(t)
			before := installedSnapshot(t, root)
			tx, err := PrepareTransaction(context.Background(), root, stage, identity)
			if err != nil {
				t.Fatal(err)
			}
			bindSession(t, tx, root)
			interrupted := false
			func() {
				defer func() {
					if value := recover(); value != "interrupted" {
						t.Fatalf("wrong interruption %v", value)
					}
				}()
				tx.Apply(context.Background(), func(done, total int) {
					if done == boundary {
						interrupted = true
						panic("interrupted")
					}
				})
			}()
			if !interrupted {
				t.Fatal("did not reach requested boundary")
			}
			tx.Close()
			tx, err = OpenTransaction(root)
			if err != nil {
				t.Fatal(err)
			}
			defer tx.Close()
			if tx.Phase() != "applying" {
				t.Fatal("no pending journal after interruption")
			}
			if err = tx.Rollback(context.Background(), nil); err != nil {
				t.Fatal(err)
			}
			if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
				t.Fatal("interrupted replacement lost previous files")
			}
		})
	}
}

func TestCancellationRollsBackAndNewAttemptWorks(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	bindSession(t, tx, root)
	ctx, cancel := context.WithCancel(context.Background())
	if err = tx.Apply(ctx, func(done, total int) { cancel() }); err == nil {
		t.Fatal("ignored cancellation")
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("cancellation did not restore previous version")
	}
	tx.Close()
	tx, err = PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	bindSession(t, tx, root)
	if err = tx.Apply(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
}

func TestTransactionRefusesModifiedFilesAndUnownedCollisions(t *testing.T) {
	for _, when := range []string{"old-modified", "new-collision", "after-prepare", "rollback-edit", "backup-corrupt", "staged-corrupt", "stage-rehashed"} {
		t.Run(when, func(t *testing.T) {
			root, stage, identity := transactionFixture(t)
			if when == "old-modified" {
				os.WriteFile(filepath.Join(root, pkgpath.Launcher()), []byte("player-edit"), 0600)
			}
			if when == "new-collision" {
				os.WriteFile(filepath.Join(root, "notices", "new-license.txt"), []byte("player-file"), 0600)
			}
			if when == "staged-corrupt" {
				os.WriteFile(filepath.Join(stage, pkgpath.Launcher()), []byte("broken-download"), 0600)
			}
			if when == "stage-rehashed" {
				os.WriteFile(filepath.Join(stage, filepath.FromSlash(pkgpath.Worker())), []byte("replaced-worker"), 0600)
				manifestPath := filepath.Join(stage, "package-manifest.json")
				body, _ := os.ReadFile(manifestPath)
				var m map[string]any
				json.Unmarshal([]byte(strings.TrimPrefix(string(body), "\ufeff")), &m)
				for _, entry := range m["files"].([]any) {
					row := entry.(map[string]any)
					if row["path"] == pkgpath.Worker() {
						row["sha256"] = digest([]byte("replaced-worker"))
					}
				}
				body, _ = json.Marshal(m)
				os.WriteFile(manifestPath, body, 0600)
			}
			before := installedSnapshot(t, root)
			tx, err := PrepareTransaction(context.Background(), root, stage, identity)
			if when == "old-modified" || when == "new-collision" || when == "staged-corrupt" || when == "stage-rehashed" {
				if err == nil {
					tx.Close()
					t.Fatal("prepared unsafe update")
				}
				if !reflect.DeepEqual(installedSnapshot(t, root), before) {
					t.Fatal("failed preparation changed installation")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			defer tx.Close()
			bindSession(t, tx, root)
			if when == "after-prepare" {
				os.WriteFile(filepath.Join(root, "_internal", "library.dll"), []byte("new-user-edit"), 0600)
				before = installedSnapshot(t, root)
				if err = tx.Apply(context.Background(), nil); err == nil {
					t.Fatal("overwrote edit after preparation")
				}
			} else {
				if err = tx.Apply(context.Background(), nil); err != nil {
					t.Fatal(err)
				}
				if when == "rollback-edit" {
					os.WriteFile(filepath.Join(root, "_internal", "library.dll"), []byte("new-user-edit"), 0600)
				} else {
					os.WriteFile(filepath.Join(root, filepath.FromSlash(tx.record.Directory), "previous", "_internal", "library.dll"), []byte("broken-backup"), 0600)
				}
				before = installedSnapshot(t, root)
				if err = tx.Rollback(context.Background(), nil); err == nil {
					t.Fatal("accepted unsafe rollback")
				}
			}
			if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
				t.Fatal("conflict overwrote an unexpected file")
			}
		})
	}
}

func TestRollbackDoesNotRequireUnusedNewPayload(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	bindSession(t, tx, root)
	if err = tx.Apply(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if err = os.Remove(filepath.Join(root, filepath.FromSlash(tx.record.Directory), "next", "bin", "order1886-worker.exe")); err != nil {
		t.Fatal(err)
	}
	if err = tx.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("rollback lost files after new stage was removed")
	}
}

func TestUpdaterLockAndPendingTransactionRefuseCompetingUpdate(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	if other, err := OpenTransaction(root); err == nil {
		other.Close()
		t.Fatal("two updater locks acquired")
	}
	tx.Close()
	if other, err := PrepareTransaction(context.Background(), root, stage, identity); err == nil {
		other.Close()
		t.Fatal("overwrote pending recovery journal")
	}
	tx, err = OpenTransaction(root)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	if err = tx.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
}

func TestRecoveryRejectsJournalPathsOutsideOwnedPackage(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	tx.record.Files[0].Path = "user/order1886/settings.json"
	body, _ := json.Marshal(tx.record)
	tx.Close()
	if err = os.WriteFile(filepath.Join(root, ".order1886-update", "journal.json"), body, 0600); err != nil {
		t.Fatal(err)
	}
	before := installedSnapshot(t, root)
	if recovery, err := OpenTransaction(root); err == nil {
		recovery.Close()
		t.Fatal("accepted journal targeting player data")
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("invalid journal changed files")
	}
}

func TestSourceCheckoutAndUnsupportedBootstrapAreRefused(t *testing.T) {
	t.Run("checkout", func(t *testing.T) {
		root, stage, identity := transactionFixture(t)
		if err := os.WriteFile(filepath.Join(root, ".git"), []byte("gitdir: protected-worktree"), 0600); err != nil {
			t.Fatal(err)
		}
		before := installedSnapshot(t, root)
		if tx, err := PrepareTransaction(context.Background(), root, stage, identity); err == nil {
			tx.Close()
			t.Fatal("accepted source checkout")
		}
		if !reflect.DeepEqual(installedSnapshot(t, root), before) {
			t.Fatal("changed source checkout")
		}
		if _, err := os.Stat(filepath.Join(root, workspace)); !os.IsNotExist(err) {
			t.Fatal("created updater state in source checkout")
		}
	})
	t.Run("unsupported-bootstrap", func(t *testing.T) {
		root, _, _ := transactionFixture(t)
		archive, identity := packageFixture(t, nil)
		stage := filepath.Join(t.TempDir(), "unsupported")
		verified, err := StageArchive(context.Background(), archive, stage, identity)
		if err != nil {
			t.Fatal(err)
		}
		identity.ManifestSHA256 = verified.SHA256
		before := installedSnapshot(t, root)
		if tx, err := PrepareTransaction(context.Background(), root, stage, identity); err == nil {
			tx.Close()
			t.Fatal("accepted package without recovery bootstrap ABI")
		} else if !strings.Contains(err.Error(), "recovery") {
			t.Fatalf("wrong refusal: %v", err)
		}
		if !reflect.DeepEqual(installedSnapshot(t, root), before) {
			t.Fatal("unsupported bootstrap changed installation")
		}
	})
}

func TestRecoveryBootstrapsAreReplacedBeforeWorkerLibraries(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	bindSession(t, tx, root)
	if err = tx.Apply(context.Background(), func(done, total int) {
		got := installedSnapshot(t, root)
		if done == 1 && (got[pkgpath.Launcher()] != "launcher-7" || got["_internal/library.dll"] != "library-6") {
			t.Fatal("primary bootstrap was not installed first")
		}
		if done == 2 && (got[pkgpath.Play()] != "launcher-7" || got["_internal/library.dll"] != "library-6") {
			t.Fatal("direct bootstrap was not installed before libraries")
		}
	}); err != nil {
		t.Fatal(err)
	}
	if err = tx.Rollback(context.Background(), func(done, total int) {
		got := installedSnapshot(t, root)
		if got[pkgpath.Play()] == "launcher-6" && got["_internal/library.dll"] != "library-6" {
			t.Fatal("removed recovery bootstrap before restoring old libraries")
		}
	}); err != nil {
		t.Fatal(err)
	}
}
