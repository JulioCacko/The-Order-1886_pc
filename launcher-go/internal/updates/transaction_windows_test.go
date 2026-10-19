package updates

import (
	"context"
	"os/exec"
	"path/filepath"
	"reflect"
	"testing"

	"golang.org/x/sys/windows"
)

func TestLockedWindowsLibraryAutomaticallyRestoresPreviousVersion(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	before := installedSnapshot(t, root)
	tx, err := PrepareTransaction(context.Background(), root, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	bindSession(t, tx, root)
	name, err := windows.UTF16PtrFromString(filepath.Join(root, "_internal", "library.dll"))
	if err != nil {
		t.Fatal(err)
	}
	handle, err := windows.CreateFile(name, windows.GENERIC_READ, windows.FILE_SHARE_READ, nil, windows.OPEN_EXISTING, windows.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer windows.CloseHandle(handle)
	if err = tx.Apply(context.Background(), nil); err == nil {
		t.Fatal("replaced a library opened without delete sharing")
	}
	if got := installedSnapshot(t, root); !reflect.DeepEqual(got, before) {
		t.Fatal("locked-library failure left mixed versions")
	}
	if tx.Phase() != "rolled_back" {
		t.Fatal("locked-library failure was not rolled back")
	}
}

func TestTransactionRejectsStageJunction(t *testing.T) {
	root, stage, identity := transactionFixture(t)
	link := stage + " junction"
	output, err := exec.Command("cmd.exe", "/d", "/c", "mklink", "/J", link, stage).CombinedOutput()
	if err != nil {
		t.Fatalf("create isolated junction: %s %v", output, err)
	}
	if tx, err := PrepareTransaction(context.Background(), root, link, identity); err == nil {
		tx.Close()
		t.Fatal("accepted a junction as a trusted update stage")
	}
}
