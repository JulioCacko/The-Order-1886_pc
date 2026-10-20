package updates

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"testing"
)

// These tests exercise the ordering the updater claims for a crash: what is on disk
// after a power loss, and what recovery does with it. They use an isolated
// installation and real files, never the player's package.

func journalFile(root string) string {
	return filepath.Join(root, filepath.FromSlash(journalPath))
}

func readJournalBytes(t *testing.T, root string) []byte {
	t.Helper()
	body, err := os.ReadFile(journalFile(root))
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func writeJournalBytes(t *testing.T, root string, body []byte) {
	t.Helper()
	if err := os.WriteFile(journalFile(root), body, 0600); err != nil {
		t.Fatal(err)
	}
}

func transactionDirectory(root, directory string) string {
	return filepath.Join(root, filepath.FromSlash(directory))
}

// A crash between publishing the "applying" journal and replacing the first file
// must recover to the exact previous tree. The second case also truncates and
// removes recorded payloads, which is what payload writes that only partially
// reached the disk leave behind: nothing was replaced yet, so recovery must not
// depend on those payloads and must still restore the tree byte for byte.
func TestCrashBetweenApplyingJournalAndFirstReplacementRecoversExactTree(t *testing.T) {
	for _, partial := range []bool{false, true} {
		name := "intact-payloads"
		if partial {
			name = "partial-payloads"
		}
		t.Run(name, func(t *testing.T) {
			root, stage, identity := transactionFixture(t)
			before := installedSnapshot(t, root)
			tx, err := PrepareTransaction(context.Background(), root, stage, identity)
			if err != nil {
				t.Fatal(err)
			}
			bindSession(t, tx, root)
			// Exactly what Apply records before it touches any installed file.
			if err = tx.saveJournal("applying"); err != nil {
				t.Fatal(err)
			}
			directory := tx.record.Directory
			changes := len(tx.record.Files)
			// The process dies here: no replacement has run.
			tx.Close()

			if partial {
				transaction := transactionDirectory(root, directory)
				for _, payload := range []string{"previous/_internal/library.dll", "previous/" + pkgpath.Launcher()} {
					file := filepath.Join(transaction, filepath.FromSlash(payload))
					body, err := os.ReadFile(file)
					if err != nil {
						t.Fatal(err)
					}
					if len(body) < 4 {
						t.Fatalf("payload too small to truncate: %s", payload)
					}
					if err = os.WriteFile(file, body[:len(body)/2], 0600); err != nil {
						t.Fatal(err)
					}
				}
				if err = os.Remove(filepath.Join(transaction, filepath.FromSlash("next/"+pkgpath.Worker()))); err != nil {
					t.Fatal(err)
				}
			}

			if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
				t.Fatal("crash before the first replacement changed the installed tree")
			}
			pending, state, err := PendingRecovery(root)
			if err != nil || !pending {
				t.Fatalf("startup did not see the pending update: %v", err)
			}
			if want := filepath.Join(root, "user", "order1886"); state != want {
				t.Fatalf("wrong recorded player state: got %q want %q", state, want)
			}

			recovery, err := OpenTransaction(root)
			if err != nil {
				t.Fatalf("journal with %d changes was not readable: %v", changes, err)
			}
			if recovery.Phase() != "applying" {
				t.Fatalf("wrong recovered phase %q", recovery.Phase())
			}
			if err = recovery.Rollback(context.Background(), nil); err != nil {
				t.Fatalf("recovery refused a journal that never replaced a file: %v", err)
			}
			if recovery.Phase() != "rolled_back" {
				t.Fatalf("wrong final phase %q", recovery.Phase())
			}
			if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
				t.Fatal("recovery did not restore the exact previous tree")
			}
			recovery.Close()

			if pending, _, err = PendingRecovery(root); err != nil || pending {
				t.Fatalf("installation still requires recovery: %v", err)
			}
			// The installation must be usable again: a later update starts and applies.
			next, err := PrepareTransaction(context.Background(), root, stage, identity)
			if err != nil {
				t.Fatalf("a recovered installation refused the next update: %v", err)
			}
			bindSession(t, next, root)
			if err = next.Apply(context.Background(), nil); err != nil {
				next.Close()
				t.Fatal(err)
			}
			if err = next.Rollback(context.Background(), nil); err != nil {
				next.Close()
				t.Fatal(err)
			}
			next.Close()
			if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
				t.Fatal("update after recovery lost the previous tree")
			}
		})
	}
}

// A journal is only published by renaming a fully written and flushed temp file, so
// a torn journal can only exist after external damage. Every truncation of that file
// must be refused without changing one byte of the installation, and the journal
// stored before the damage must still recover afterwards.
func TestTornJournalIsRefusedAndLeavesTheInstallationUntouched(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	bindSession(t, tx, root)
	if err = tx.saveJournal("applying"); err != nil {
		t.Fatal(err)
	}
	tx.Close()

	intact := readJournalBytes(t, root)
	if len(intact) < 64 {
		t.Fatalf("journal too short to truncate meaningfully: %d bytes", len(intact))
	}
	// Every proper prefix models a write that stopped at an arbitrary byte.
	for length := 0; length < len(intact); length++ {
		writeJournalBytes(t, root, intact[:length])
		if phase, ok, err := JournalPhase(root); err == nil || ok {
			t.Fatalf("accepted a journal torn to %d of %d bytes as %q", length, len(intact), phase)
		}
		if kept, err := os.ReadFile(journalFile(root)); err != nil || len(kept) != length {
			t.Fatalf("refusing a journal torn to %d bytes rewrote it: %v", length, err)
		}
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("reading torn journals changed the installation")
	}
	// The startup gate and the reopening path refuse the same torn files.
	for _, length := range []int{0, 1, len(intact) / 3, len(intact) / 2, len(intact) - 1} {
		writeJournalBytes(t, root, intact[:length])
		if pending, _, err := PendingRecovery(root); err == nil {
			t.Fatalf("startup accepted a journal torn to %d bytes (pending=%t)", length, pending)
		}
		if reopened, err := OpenTransaction(root); err == nil {
			reopened.Close()
			t.Fatalf("reopened a journal torn to %d bytes", length)
		}
		if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
			t.Fatalf("a journal torn to %d bytes changed the installation", length)
		}
	}

	// The valid journal stored before the damage is still usable.
	writeJournalBytes(t, root, intact)
	if pending, _, err := PendingRecovery(root); err != nil || !pending {
		t.Fatalf("a restored journal no longer requires recovery: %v", err)
	}
	recovery, err := OpenTransaction(root)
	if err != nil {
		t.Fatal(err)
	}
	defer recovery.Close()
	if recovery.Phase() != "applying" {
		t.Fatalf("wrong phase after restoring the journal: %q", recovery.Phase())
	}
	if err = recovery.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("recovery after torn journals did not restore the previous tree")
	}
}

// A failed journal read must not leave the previous record usable: callers branch on
// Transaction state, and a torn journal must never be papered over by what this
// handle happened to hold in memory before the read.
func TestUnreadableJournalLeavesNoUsableTransactionState(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	bindSession(t, tx, root)
	if tx.Phase() != "prepared" {
		t.Fatalf("wrong phase %q", tx.Phase())
	}
	intact := readJournalBytes(t, root)

	for _, damage := range [][]byte{
		intact[:len(intact)/2],
		intact[:0],
		append(append([]byte{}, intact[:len(intact)-1]...), 'x'),
	} {
		writeJournalBytes(t, root, damage)
		if err = tx.readJournal(); err == nil {
			t.Fatalf("read a damaged journal of %d bytes", len(damage))
		}
		if tx.Phase() != "" {
			t.Fatalf("failed journal read kept phase %q in memory", tx.Phase())
		}
		if _, err = tx.SessionDirectory(); err == nil {
			t.Fatal("failed journal read kept a usable player state")
		}
		if len(tx.record.Files) != 0 || tx.record.Directory != "" || tx.record.Session != nil || tx.record.Launch != nil {
			t.Fatal("failed journal read kept a usable record")
		}
		if err = tx.saveJournal("rolling_back"); err == nil {
			t.Fatal("recorded a phase for a journal that could not be read")
		}
		if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
			t.Fatal("a damaged journal changed the installation")
		}
	}

	// The same handle recovers once the journal is readable again.
	writeJournalBytes(t, root, intact)
	if err = tx.readJournal(); err != nil {
		t.Fatal(err)
	}
	if tx.Phase() != "prepared" {
		t.Fatalf("wrong phase after restoring the journal: %q", tx.Phase())
	}
	if err = tx.Rollback(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if tx.Phase() != "rolled_back" {
		t.Fatalf("wrong final phase %q", tx.Phase())
	}
}

// A journal records one promise at a time. Stale in-memory state must never rewind
// the phase that is already durable: a rewind would promise less than the disk
// already claims and hide replacement work that recovery has to undo.
func TestRecordedPhaseOnlyMovesForward(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	bindSession(t, tx, root)
	// Repeating the current phase is how BindSession and BindLaunch update the record.
	if err = tx.saveJournal("prepared"); err != nil {
		t.Fatalf("rewriting the current phase was refused: %v", err)
	}
	if err = tx.saveJournal("applying"); err != nil {
		t.Fatal(err)
	}
	// Model a caller holding a record that no longer matches the durable journal.
	tx.record.Phase = "prepared"
	if err = tx.saveJournal("prepared"); err == nil {
		t.Fatal("rewound the durable journal phase to an earlier promise")
	}
	if phase, ok, err := JournalPhase(root); err != nil || !ok || phase != "applying" {
		t.Fatalf("refused rewind changed the journal: %q %t %v", phase, ok, err)
	}
	// Forward progress is still allowed.
	tx.record.Phase = "applying"
	if err = tx.saveJournal("rolling_back"); err != nil {
		t.Fatalf("refused forward phase: %v", err)
	}
	if err = tx.saveJournal("rolled_back"); err != nil {
		t.Fatal(err)
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("phase bookkeeping changed the installation")
	}
}

// Recovery may only remove a file whose current content is a replacement this
// transaction verified, and may only restore a file it holds a verified backup of.
// Player files the manifest does not own must survive every disagreement between the
// journal and the installation.
func TestRecoveryNeverDeletesPlayerFilesTheManifestDoesNotOwn(t *testing.T) {
	player := map[string]string{
		"user/order1886/savedata/slot1/Save": "chapter-nine",
		"mods/lighting/content.bin":          "player-mod",
		"patches/enabled.json":               "player-patches",
		"player notes.txt":                   "keep-this-file",
	}
	assertPlayerFiles := func(t *testing.T, root string) {
		t.Helper()
		for name, want := range player {
			body, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(name)))
			if err != nil {
				t.Fatalf("player file %s was removed: %v", name, err)
			}
			if string(body) != want {
				t.Fatalf("player file %s was rewritten: %q", name, body)
			}
		}
	}

	t.Run("player-file-at-a-journal-added-path", func(t *testing.T) {
		root, stage, identity := transactionFixture(t)
		tx, err := PrepareTransaction(context.Background(), root, stage, identity)
		if err != nil {
			t.Fatal(err)
		}
		defer tx.Close()
		bindSession(t, tx, root)
		// The journal records this path as a package addition; the player created a
		// different file there after preparation.
		added := filepath.Join(root, "notices", "new-license.txt")
		if err = os.WriteFile(added, []byte("player-wrote-this"), 0600); err != nil {
			t.Fatal(err)
		}
		before := installedSnapshot(t, root)
		if err = tx.Rollback(context.Background(), nil); err == nil {
			t.Fatal("recovery deleted a file it did not add byte for byte")
		}
		if _, err = os.Stat(added); err != nil {
			t.Fatal("recovery removed a player file at an added package path")
		}
		if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
			t.Fatal("refused recovery changed the installation")
		}
		assertPlayerFiles(t, root)
	})

	t.Run("player-edit-of-a-journal-deleted-path", func(t *testing.T) {
		root, stage, identity := transactionFixture(t)
		tx, err := PrepareTransaction(context.Background(), root, stage, identity)
		if err != nil {
			t.Fatal(err)
		}
		defer tx.Close()
		bindSession(t, tx, root)
		// The journal records this package file as a deletion.
		retired := filepath.Join(root, "notices", "LICENSE.txt")
		if err = os.WriteFile(retired, []byte("player-replaced-this"), 0600); err != nil {
			t.Fatal(err)
		}
		before := installedSnapshot(t, root)
		if err = tx.Apply(context.Background(), nil); err == nil {
			t.Fatal("applied an update that would delete an unexpected edit")
		}
		if _, err = os.Stat(retired); err != nil {
			t.Fatal("failed apply removed an unexpected edit")
		}
		if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
			t.Fatal("failed apply changed the installation")
		}
		assertPlayerFiles(t, root)
	})

	t.Run("journal-solely-owns-the-addition", func(t *testing.T) {
		root, stage, identity := transactionFixture(t)
		tx, err := PrepareTransaction(context.Background(), root, stage, identity)
		if err != nil {
			t.Fatal(err)
		}
		defer tx.Close()
		bindSession(t, tx, root)
		// Write the package's own addition, so the installation agrees with the journal.
		added := filepath.Join(root, "notices", "new-license.txt")
		if err = os.WriteFile(added, []byte("new-license"), 0600); err != nil {
			t.Fatal(err)
		}
		if err = tx.Rollback(context.Background(), nil); err != nil {
			t.Fatal(err)
		}
		if _, err = os.Stat(added); !os.IsNotExist(err) {
			t.Fatal("recovery kept the package file this transaction added")
		}
		assertPlayerFiles(t, root)
	})

	// validateJournal confines every recorded path to the package-owned trees, so a
	// journal cannot name player data at all. The control record keeps its recorded
	// order valid, so only the path itself can be the reason for the refusal.
	t.Run("journal-cannot-name-player-data", func(t *testing.T) {
		root, stage, identity := transactionFixture(t)
		tx, err := PrepareTransaction(context.Background(), root, stage, identity)
		if err != nil {
			t.Fatal(err)
		}
		bindSession(t, tx, root)
		record := tx.record
		tx.Close()
		index := repurposableEntry(t, record, "deletion")

		control := record
		control.Files = append([]change{}, record.Files...)
		control.Files[index] = change{Path: "notices/retired-notice.txt", Old: strings.Repeat("a", 64), New: ""}
		sort.Slice(control.Files, func(i, j int) bool { return beforeChange(control.Files[i], control.Files[j]) })
		if err = validateJournal(control); err != nil {
			t.Fatalf("control journal is not valid, so the refusal proves nothing: %v", err)
		}
		for name := range player {
			crafted := record
			crafted.Files = append([]change{}, record.Files...)
			crafted.Files[index] = change{Path: name, Old: digest([]byte(player[name])), New: ""}
			sort.Slice(crafted.Files, func(i, j int) bool { return beforeChange(crafted.Files[i], crafted.Files[j]) })
			if err = validateJournal(crafted); err == nil {
				t.Fatalf("a journal naming player data validated: %s", name)
			}
			body, err := json.Marshal(crafted)
			if err != nil {
				t.Fatal(err)
			}
			writeJournalBytes(t, root, body)
			before := installedSnapshot(t, root)
			if reopened, err := OpenTransaction(root); err == nil {
				_ = reopened.Rollback(context.Background(), nil)
				reopened.Close()
			}
			if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
				t.Fatalf("a journal naming %s changed the installation", name)
			}
			assertPlayerFiles(t, root)
		}
	})

	// A path inside a package-owned directory is still not a licence to delete: the
	// only file recovery may remove is one whose content equals a replacement this
	// transaction verified, and the only file it may overwrite is one it backed up.
	for _, crafted := range []string{"delete", "add"} {
		t.Run("journal-claims-an-unbacked-"+crafted, func(t *testing.T) {
			root, stage, identity := transactionFixture(t)
			tx, err := PrepareTransaction(context.Background(), root, stage, identity)
			if err != nil {
				t.Fatal(err)
			}
			bindSession(t, tx, root)
			record := tx.record
			tx.Close()

			// A player file inside a package-owned tree, which this transaction never
			// recorded, backed up or staged.
			target := filepath.Join(root, "_internal", "player-config.ini")
			if err = os.WriteFile(target, []byte("player-config"), 0600); err != nil {
				t.Fatal(err)
			}
			index := repurposableEntry(t, record, map[string]string{"delete": "deletion", "add": "addition"}[crafted])
			if crafted == "delete" {
				record.Files[index] = change{Path: "_internal/player-config.ini", Old: digest([]byte("player-config")), New: ""}
			} else {
				record.Files[index] = change{Path: "_internal/player-config.ini", Old: "", New: digest([]byte("package-config"))}
			}
			sort.Slice(record.Files, func(i, j int) bool { return beforeChange(record.Files[i], record.Files[j]) })
			if err = validateJournal(record); err != nil {
				t.Fatalf("crafted journal is not valid, so it proves nothing: %v", err)
			}
			body, err := json.Marshal(record)
			if err != nil {
				t.Fatal(err)
			}
			writeJournalBytes(t, root, body)
			before := installedSnapshot(t, root)

			reopened, err := OpenTransaction(root)
			if err != nil {
				if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
					t.Fatal("refused journal changed the installation")
				}
				return
			}
			defer reopened.Close()
			// Installing the claim requires a backup or a stage this transaction does not hold.
			if err = reopened.Apply(context.Background(), nil); err == nil {
				t.Fatal("installed a record whose payloads it does not hold")
			}
			if body, err := os.ReadFile(target); err != nil || string(body) != "player-config" {
				t.Fatalf("recovery removed or rewrote a player file it never backed up: %q %v", body, err)
			}
			if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
				t.Fatal("refused apply changed the installation")
			}
		})
	}
}

// repurposableEntry returns the index of the last recorded deletion or addition, so a
// crafted record can substitute one entry and keep the recorded order valid.
func repurposableEntry(t *testing.T, record journal, kind string) int {
	t.Helper()
	for i := len(record.Files) - 1; i >= 0; i-- {
		deletion := record.Files[i].Old != "" && record.Files[i].New == ""
		addition := record.Files[i].Old == "" && record.Files[i].New != ""
		if kind == "deletion" && deletion || kind == "addition" && addition {
			return i
		}
	}
	t.Fatalf("fixture has no recorded %s to repurpose", kind)
	return -1
}
