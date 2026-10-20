package updatehost

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"strings"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"testing"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updates"
)

func prepare(t *testing.T, installation string, candidate Candidate) string {
	t.Helper()
	state := filepath.Join(installation, "user", "order1886")
	if err := Prepare(installation, candidate, state, false); err != nil {
		t.Fatal(err)
	}
	// A real installation already has a session lock file from an earlier launch.
	if lock, err := updates.LockSession(state); err == nil {
		lock.Close()
	}
	return state
}

func TestHelperAppliesPreparedUpdateAndRecordsResult(t *testing.T) {
	installation, candidate := TransactionFixture(t)
	state := prepare(t, installation, candidate)
	result, err := Run(context.Background(), Options{
		Installation: installation,
		Action:       ActionApply,
		NoRelaunch:   true,
		Timeout:      DefaultTimeout,
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Phase != "applied" {
		t.Fatalf("wrong phase %q", result.Phase)
	}
	if result.StateDirectory != state {
		t.Fatalf("wrong player state %q", result.StateDirectory)
	}
	if data, err := os.ReadFile(filepath.Join(installation, pkgpath.Launcher())); err != nil || string(data) != "launcher-7" {
		t.Fatalf("update was not applied: %q %v", data, err)
	}
	if _, err := os.Stat(filepath.Join(installation, "The Order 1886 Legacy.exe")); !os.IsNotExist(err) {
		t.Fatal("retired entry point survived the update")
	}
	stored, ok, err := ReadResult(installation)
	if err != nil || !ok {
		t.Fatalf("missing helper result: %v", err)
	}
	if stored.Phase != "applied" || stored.Relaunched {
		t.Fatalf("wrong recorded result %+v", stored)
	}
}

func TestHelperRecoversPendingUpdate(t *testing.T) {
	installation, candidate := TransactionFixture(t)
	prepare(t, installation, candidate)
	before := Snapshot(t, installation)
	if err := InterruptApply(installation); err != nil {
		t.Fatal(err)
	}
	result, err := Run(context.Background(), Options{Installation: installation, Action: ActionRecover, NoRelaunch: true, Timeout: DefaultTimeout})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Recovered || result.Phase != "rolled_back" {
		t.Fatalf("pending update was not rolled back: %+v", result)
	}
	if got := Snapshot(t, installation); !reflect.DeepEqual(got, before) {
		t.Fatalf("recovery did not restore the previous package: %v", snapshotDiff(before, got))
	}
	stored, _, err := ReadResult(installation)
	if err != nil || stored.RecoveryFailed {
		t.Fatalf("successful recovery was recorded as failed: %+v %v", stored, err)
	}
}

func TestHelperRefusesApplyWithoutPreparedTransaction(t *testing.T) {
	installation, _ := TransactionFixture(t)
	if _, err := Run(context.Background(), Options{Installation: installation, Action: ActionApply, NoRelaunch: true, Timeout: DefaultTimeout}); err == nil {
		t.Fatal("applied an update with no prepared transaction")
	}
	if _, err := os.Stat(filepath.Join(installation, workspaceName())); !os.IsNotExist(err) {
		t.Fatal("helper created updater files for a clean installation")
	}
}

func TestHelperCopyIsStoredInsideTheUpdateWorkspace(t *testing.T) {
	installation, _ := TransactionFixture(t)
	copied, err := CopySelf(installation)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(filepath.Clean(copied), filepath.Join(installation, workspaceName())+string(filepath.Separator)) {
		t.Fatalf("helper copy escaped the update workspace: %s", copied)
	}
	if info, err := os.Stat(copied); err != nil || !info.Mode().IsRegular() {
		t.Fatalf("helper copy is not a regular file: %v", err)
	}
	command := Command(copied, Options{Installation: installation, Action: ActionRecover, ParentPID: 4242, NoRelaunch: true})
	if !strings.Contains(strings.Join(command.Args, " "), "--update-helper --update-action recover") {
		t.Fatalf("helper arguments are not an explicit array: %v", command.Args)
	}
}

func TestFailedRecoveryIsRecordedAndNotRepeatedAutomatically(t *testing.T) {
	installation, candidate := TransactionFixture(t)
	prepare(t, installation, candidate)
	if err := InterruptApply(installation); err != nil {
		t.Fatal(err)
	}
	corruptBackups(t, installation)
	if _, err := Run(context.Background(), Options{Installation: installation, Action: ActionRecover, NoRelaunch: true, Timeout: DefaultTimeout}); err == nil {
		t.Fatal("reported success for a rollback that could not complete")
	}
	stored, ok, err := ReadResult(installation)
	if err != nil || !ok || !stored.RecoveryFailed {
		t.Fatalf("failed recovery was not recorded: %+v %v", stored, err)
	}
	if _, err = Run(context.Background(), Options{Installation: installation, Action: ActionRecover, NoRelaunch: true, Timeout: DefaultTimeout}); err == nil {
		t.Fatal("repeated a failed automatic recovery")
	}
	// An explicit restore still reports the real failure instead of pretending.
	if _, err = Run(context.Background(), Options{Installation: installation, Action: ActionRecover, NoRelaunch: true, Timeout: DefaultTimeout, ConfirmRestore: true}); err == nil {
		t.Fatal("confirmed restore hid the real failure")
	}
}

func TestRelaunchUsesTheRecordedEntryPointAndState(t *testing.T) {
	installation := filepath.Join("C:", "Portable 游戏")
	for _, direct := range []bool{false, true} {
		command := relaunchCommand(installation, filepath.Join(installation, "user", "order1886"), direct)
		want := filepath.Join(installation, pkgpath.Launcher())
		if direct {
			want = filepath.Join(installation, pkgpath.Play())
		}
		if command.Path != want {
			t.Fatalf("relaunch used %q, want %q", command.Path, want)
		}
		if command.Args[len(command.Args)-2] != "--state-dir" || command.Dir != installation {
			t.Fatalf("relaunch lost the recorded state or directory: %v %q", command.Args, command.Dir)
		}
	}
}

func TestCleanInstallationHasNoResultAndNeedsNoRecovery(t *testing.T) {
	installation, _ := TransactionFixture(t)
	if _, ok, err := ReadResult(installation); err != nil || ok {
		t.Fatalf("clean installation reported an update result: %v", err)
	}
	result, err := Run(context.Background(), Options{Installation: installation, Action: ActionRecover, NoRelaunch: true, Timeout: DefaultTimeout})
	if err != nil {
		t.Fatalf("recovery on a clean installation failed: %v", err)
	}
	if result.Recovered {
		t.Fatal("clean installation reported a recovery")
	}
}
