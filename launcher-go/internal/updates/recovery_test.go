package updates

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestRecoveryRetainsOriginalStateAcrossPortableRelocation(t *testing.T) {
	for _, external := range []bool{false, true} {
		t.Run(map[bool]string{false: "portable", true: "external"}[external], func(t *testing.T) {
			root, stage, identity := transactionFixture(t)
			state := filepath.Join(root, "user", "order1886")
			if external {
				state = filepath.Join(t.TempDir(), "Outro jogador 游戏")
			}
			tx, err := PrepareTransaction(context.Background(), root, stage, identity)
			if err != nil {
				t.Fatal(err)
			}
			if err = tx.BindSession(state); err != nil {
				tx.Close()
				t.Fatal(err)
			}
			tx.Close()
			moved := root + " moved"
			if err = os.Rename(root, moved); err != nil {
				t.Fatal(err)
			}
			pending, got, err := PendingRecovery(moved)
			if err != nil || !pending {
				t.Fatalf("missing pending recovery: %v", err)
			}
			want := filepath.Join(moved, "user", "order1886")
			if external {
				want = state
			}
			if got != want {
				t.Fatalf("wrong player state: got %q want %q", got, want)
			}
			tx, err = OpenTransaction(moved)
			if err != nil {
				t.Fatal(err)
			}
			defer tx.Close()
			if err = tx.BindSession(filepath.Join(t.TempDir(), "different-profile")); err == nil {
				t.Fatal("changed the original recovery profile")
			}
			if err = tx.Rollback(context.Background(), nil); err != nil {
				t.Fatal(err)
			}
			tx.Close()
			if pending, _, err = PendingRecovery(moved); err != nil || pending {
				t.Fatalf("completed rollback still requires recovery: %v", err)
			}
		})
	}
}

func TestRecoveryWithoutJournalDoesNotCreateUpdaterFiles(t *testing.T) {
	root := t.TempDir()
	pending, _, err := PendingRecovery(root)
	if err != nil || pending {
		t.Fatalf("unexpected recovery: %v", err)
	}
	if _, err = os.Stat(filepath.Join(root, workspace)); !os.IsNotExist(err) {
		t.Fatal("startup created updater files")
	}
}

func TestPendingRecoveryRefusesToGuessMissingPlayerState(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	tx.Close()
	if _, _, err = PendingRecovery(root); err == nil {
		t.Fatal("guessed another profile for recovery")
	}
}
