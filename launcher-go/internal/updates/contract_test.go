package updates

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"testing"
	"time"
)

// The Go-only package retires the legacy launcher. Existing installations still
// contain it, so the update must delete it after the new entry points exist and
// rollback must restore it byte for byte.
func TestRetiredLauncherIsDeletedAfterReplacementsAndRestored(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	if _, ok := before["The Order 1886 Legacy.exe"]; !ok {
		t.Fatal("installed fixture lost the retired entry point")
	}
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	deletion := -1
	for i, entry := range tx.record.Files {
		if entry.Path != "The Order 1886 Legacy.exe" {
			continue
		}
		if entry.New != "" || entry.Old == "" {
			t.Fatalf("retired entry point is not recorded as a deletion: %+v", entry)
		}
		deletion = i
	}
	if deletion < 0 {
		t.Fatal("update does not delete the retired entry point")
	}
	if last := len(tx.record.Files) - 1; tx.record.Files[last].Path != "package-manifest.json" {
		t.Fatalf("manifest is not replaced last: %s", tx.record.Files[last].Path)
	}
	firstDeletion := -1
	for i, entry := range tx.record.Files[:len(tx.record.Files)-1] {
		if entry.New == "" {
			if firstDeletion < 0 {
				firstDeletion = i
			}
			continue
		}
		if firstDeletion >= 0 {
			t.Fatalf("replacement %s is ordered after a deletion", entry.Path)
		}
	}
	if firstDeletion < 0 || deletion < firstDeletion {
		t.Fatal("deletions are not ordered after every replacement")
	}
	applied := false
	bindSession(t, tx, root)
	if err = tx.Apply(context.Background(), func(done, total int) {
		snapshot := installedSnapshot(t, root)
		if done <= deletion {
			if _, ok := snapshot["The Order 1886 Legacy.exe"]; !ok {
				t.Fatal("retired entry point was deleted before replacements finished")
			}
			if snapshot[pkgpath.Launcher()] != "launcher-7" {
				t.Fatal("primary entry point was not replaced before the deletion")
			}
		}
		if done == deletion+1 {
			if _, ok := snapshot["The Order 1886 Legacy.exe"]; ok {
				t.Fatal("retired entry point survived its deletion step")
			}
			applied = true
		}
	}); err != nil {
		t.Fatal(err)
	}
	if !applied {
		t.Fatal("deletion step never reported progress")
	}
	after := installedSnapshot(t, root)
	if _, ok := after["The Order 1886 Legacy.exe"]; ok {
		t.Fatal("applied update kept the retired entry point")
	}
	for _, name := range []string{pkgpath.Launcher(), pkgpath.Play()} {
		if after[name] != "launcher-7" {
			t.Fatalf("missing Go entry point %s after update", name)
		}
	}
	if err = tx.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("rollback did not restore the retired entry point and previous package")
	}
}

func TestApplyRequiresTheRecordedPlayerState(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	before := installedSnapshot(t, root)
	if err = tx.Apply(context.Background(), nil); err == nil {
		t.Fatal("applied an update that cannot identify the player profile for recovery")
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("refused apply still changed the installation")
	}
	if err = tx.BindSession(filepath.Join(root, "user", "order1886")); err != nil {
		t.Fatal(err)
	}
	if err = tx.Apply(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
}

func TestJournalRecordsRelaunchModeAndRejectsOlderVersions(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	body, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(journalPath)))
	if err != nil {
		t.Fatal(err)
	}
	var record map[string]any
	if err = json.Unmarshal(body, &record); err != nil {
		t.Fatal(err)
	}
	if record["version"] != float64(journalVersion) {
		t.Fatalf("wrong journal version %v", record["version"])
	}
	if _, ok := record["launch"]; ok {
		t.Fatal("journal recorded a relaunch mode before it was chosen")
	}
	if err = tx.BindSession(filepath.Join(root, "user", "order1886")); err != nil {
		t.Fatal(err)
	}
	if err = tx.BindLaunch(true); err != nil {
		t.Fatal(err)
	}
	if direct, ok := tx.LaunchMode(); !ok || !direct {
		t.Fatal("relaunch mode was not recorded")
	}
	tx.Close()
	tx, err = OpenTransaction(root)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	if direct, ok := tx.LaunchMode(); !ok || !direct {
		t.Fatal("relaunch mode was lost across recovery")
	}
	if err = tx.BindLaunch(false); err == nil {
		t.Fatal("changed the recorded relaunch mode")
	}
	if err = tx.Apply(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if err = tx.BindLaunch(true); err == nil {
		t.Fatal("changed the relaunch mode after applying")
	}
	tx.Close()

	older := filepath.Join(root, filepath.FromSlash(journalPath))
	raw, err := os.ReadFile(older)
	if err != nil {
		t.Fatal(err)
	}
	var tampered map[string]any
	if err = json.Unmarshal(raw, &tampered); err != nil {
		t.Fatal(err)
	}
	tampered["version"] = 1
	raw, err = json.Marshal(tampered)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(older, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if reopened, err := OpenTransaction(root); err == nil {
		reopened.Close()
		t.Fatal("accepted a recovery journal from an incompatible updater")
	}
}

func TestRetainKeepsInFlightAndNewestCompletedTransaction(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	first, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	if err = first.BindSession(filepath.Join(root, "user", "order1886")); err != nil {
		t.Fatal(err)
	}
	if err = first.Apply(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if err = first.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	completed := first.record.Directory
	first.Close()

	installed, err := OpenInstallation(root)
	if err != nil {
		t.Fatal(err)
	}
	stale := workspace + "/txn-" + strings.Repeat("0", 32)
	older := workspace + "/txn-" + strings.Repeat("1", 32)
	for name, age := range map[string]time.Duration{stale: time.Hour, older: 2 * time.Hour} {
		if err = installed.root.MkdirAll(name+"/previous/bin", 0700); err != nil {
			t.Fatal(err)
		}
		if err = installed.root.WriteFile(name+"/previous/bin/old.dll", []byte("old"), 0600); err != nil {
			t.Fatal(err)
		}
		when := time.Now().Add(-age)
		if err = os.Chtimes(filepath.Join(root, filepath.FromSlash(name)), when, when); err != nil {
			t.Fatal(err)
		}
	}
	if err = installed.root.WriteFile("player notes.txt", []byte("keep-this-file"), 0600); err != nil {
		t.Fatal(err)
	}
	if removed, err := installed.Retain(2); err != nil {
		t.Fatal(err)
	} else if len(removed) != 1 || removed[0] != older {
		t.Fatalf("wrong retention result: %v", removed)
	}
	for _, name := range []string{completed, stale} {
		if _, err = installed.root.Lstat(name); err != nil {
			t.Fatalf("retention removed a transaction it should keep: %s", name)
		}
	}
	if _, err = installed.root.Lstat(older); !os.IsNotExist(err) {
		t.Fatal("retention kept a superseded transaction")
	}
	installed.Close()

	pending, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer pending.Close()
	if err = pending.BindSession(filepath.Join(root, "user", "order1886")); err != nil {
		t.Fatal(err)
	}
	if removed, err := pending.Retain(1); err != nil {
		t.Fatal(err)
	} else if len(removed) != 2 || removed[0] != completed || removed[1] != stale {
		t.Fatalf("retention kept completed transactions while one is in flight: %v", removed)
	}
	if _, err = pending.root.Lstat(pending.record.Directory); err != nil {
		t.Fatal("retention removed the in-flight transaction")
	}
	if _, err = pending.root.Lstat("player notes.txt"); err != nil {
		t.Fatal("retention removed a player file")
	}
}
