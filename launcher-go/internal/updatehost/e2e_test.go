//go:build e2e

package updatehost

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updates"
)

// This test only runs with -tags e2e and two real package paths, because it must
// replace real launcher binaries and read a real populated player directory:
//
//	ORDER1886_E2E_OLD        full copy of an installed package (preview.6 layout)
//	ORDER1886_E2E_CANDIDATE  the newly built package ZIP (Go only, ABI 2)
//	ORDER1886_E2E_WORK       an empty directory the test may use
//
// The source directories are never modified; every action happens on a copy.
func TestPackagedUpdatePreservesPlayerDataAndRollsBack(t *testing.T) {
	oldPackage := os.Getenv("ORDER1886_E2E_OLD")
	candidateZip := os.Getenv("ORDER1886_E2E_CANDIDATE")
	work := os.Getenv("ORDER1886_E2E_WORK")
	if oldPackage == "" || candidateZip == "" || work == "" {
		t.Skip("set ORDER1886_E2E_OLD, ORDER1886_E2E_CANDIDATE and ORDER1886_E2E_WORK")
	}
	if err := os.MkdirAll(work, 0o700); err != nil {
		t.Fatal(err)
	}
	installation := filepath.Join(work, "Instalação de teste")
	if err := copyTree(oldPackage, installation); err != nil {
		t.Fatal(err)
	}
	before := Snapshot(t, installation)
	if _, ok := before["The Order 1886 Legacy.exe"]; !ok {
		t.Fatal("the old package does not contain the retired launcher; this is not an upgrade test")
	}
	playerFiles := 0
	for name := range before {
		if strings.HasPrefix(name, "user/") {
			playerFiles++
		}
	}
	if playerFiles < 10 {
		t.Fatalf("the copied installation has only %d player files; it is not populated", playerFiles)
	}

	hash := sha256.Sum256(mustRead(t, candidateZip))
	identity := updates.Identity{
		Size:           int64(len(mustRead(t, candidateZip))),
		SHA256:         hex.EncodeToString(hash[:]),
		SourceRevision: manifestString(t, candidateZip, "source_revision"),
		RuntimeSHA256:  manifestString(t, candidateZip, "runtime_sha256"),
	}
	if abi := manifestString(t, candidateZip, "update_abi"); abi != "order1886-update-2" {
		t.Fatalf("candidate does not advertise the recovery ABI: %q", abi)
	}
	stage := filepath.Join(work, "stage")
	manifest, err := updates.StageArchive(context.Background(), candidateZip, stage, identity)
	if err != nil {
		t.Fatal(err)
	}
	identity.ManifestSHA256 = manifest.SHA256
	state := filepath.Join(installation, "user", "order1886")
	if err := Prepare(installation, Candidate{Stage: stage, Identity: identity}, state, false); err != nil {
		t.Fatal(err)
	}
	applied, err := Run(context.Background(), Options{Installation: installation, Action: ActionApply, NoRelaunch: true, Timeout: 2 * time.Minute})
	if err != nil {
		t.Fatalf("apply failed and was rolled back: %v", err)
	}
	if applied.Phase != "applied" {
		t.Fatalf("wrong phase after apply: %s", applied.Phase)
	}
	after := Snapshot(t, installation)
	if _, ok := after["The Order 1886 Legacy.exe"]; ok {
		t.Fatal("the retired launcher survived the update")
	}
	for _, name := range []string{"The Order 1886.exe", "Play The Order 1886.exe"} {
		if data, ok := after[name]; !ok || data == "" {
			t.Fatalf("missing entry point after update: %s", name)
		}
	}
	changed := 0
	for name, want := range before {
		if !strings.HasPrefix(name, "user/") {
			continue
		}
		if after[name] != want {
			t.Fatalf("player file changed during the update: %s", name)
		}
		changed++
	}
	// The helper must create nothing under the player profile except the OS-owned
	// session lock it has to hold while it replaces files.
	allowed := "user/order1886/session.lock"
	for name := range after {
		if _, existed := before[name]; strings.HasPrefix(name, "user/") && !existed && name != allowed {
			t.Fatalf("update created a player file: %s", name)
		}
	}
	// The updated installation must actually start its own worker. The worker may
	// create its own player-side notices, which are not package files.
	smoke := exec.Command(filepath.Join(installation, "The Order 1886.exe"), "--worker-smoke", "--state-dir", state)
	smoke.Dir = installation
	if output, err := smoke.CombinedOutput(); err != nil {
		t.Fatalf("updated package failed its worker smoke: %v %s", err, output)
	}
	rolledBack, err := Run(context.Background(), Options{Installation: installation, Action: ActionRollback, NoRelaunch: true, Timeout: 2 * time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if !rolledBack.Recovered || rolledBack.Phase != "rolled_back" {
		t.Fatalf("rollback did not complete: %+v", rolledBack)
	}
	restored := Snapshot(t, installation)
	for name, want := range before {
		if got, ok := restored[name]; !ok || got != want {
			t.Fatalf("rollback did not restore %s", name)
		}
	}
	for name := range restored {
		if _, existed := before[name]; existed || strings.HasPrefix(name, "user/") {
			continue
		}
		t.Fatalf("rollback left a package file behind: %s", name)
	}
	changedPackage := 0
	for name, want := range before {
		if strings.HasPrefix(name, "user/") {
			continue
		}
		if after[name] != want {
			changedPackage++
		}
	}
	t.Logf("updated %d player files and %d package files; apply and rollback preserved every player byte",
		changed, changedPackage)
}

func mustRead(t *testing.T, name string) []byte {
	t.Helper()
	body, err := os.ReadFile(name)
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func manifestString(t *testing.T, archive, key string) string {
	t.Helper()
	reader, err := zip.OpenReader(archive)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	for _, file := range reader.File {
		if !strings.HasSuffix(file.Name, "package-manifest.json") {
			continue
		}
		body, err := file.Open()
		if err != nil {
			t.Fatal(err)
		}
		defer body.Close()
		raw, err := io.ReadAll(io.LimitReader(body, 4<<20))
		if err != nil {
			t.Fatal(err)
		}
		var manifest map[string]any
		if err = json.Unmarshal([]byte(strings.TrimPrefix(string(raw), "\ufeff")), &manifest); err != nil {
			t.Fatal(err)
		}
		value, _ := manifest[key].(string)
		return value
	}
	t.Fatalf("candidate archive has no package manifest: %s", archive)
	return ""
}

func copyTree(source, destination string) error {
	return filepath.Walk(source, func(name string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(source, name)
		if err != nil {
			return err
		}
		target := filepath.Join(destination, relative)
		if info.IsDir() {
			return os.MkdirAll(target, 0o700)
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		input, err := os.Open(name)
		if err != nil {
			return err
		}
		defer input.Close()
		output, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
		if err != nil {
			return err
		}
		if _, err = io.Copy(output, input); err != nil {
			output.Close()
			return err
		}
		return output.Close()
	})
}
