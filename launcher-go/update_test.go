package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updates"
)

func writeManifest(t *testing.T, root, body string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, "package-manifest.json"), []byte("\xef\xbb\xbf"+body), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestInstalledIsCurrent(t *testing.T) {
	root := t.TempDir()
	published := time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)
	release := updates.Release{Tag: "v0.2.5", Published: published, Identity: updates.Identity{SourceRevision: "abc"}}
	if installedIsCurrent(root, release) {
		t.Fatal("missing manifest reported current")
	}
	writeManifest(t, root, `{"source_revision":"abc","built_utc":"2026-10-30T00:27:45Z"}`)
	if !installedIsCurrent(root, release) {
		t.Fatal("same revision reported as an update")
	}
	writeManifest(t, root, `{"source_revision":"old","built_utc":"2026-10-20T00:00:00Z"}`)
	if installedIsCurrent(root, release) {
		t.Fatal("older package reported current")
	}
	writeManifest(t, root, `{"source_revision":"dev","built_utc":"2026-10-31T00:00:00Z"}`)
	if !installedIsCurrent(root, release) {
		t.Fatal("package built after the release reported as outdated")
	}
}

func TestDownloadRefusedWhileBusyOrRunning(t *testing.T) {
	app := &App{root: t.TempDir(), state: t.TempDir()}
	app.release = updates.Release{Tag: "v9.9.9"}
	app.update.State = "downloading"
	app.update.Downloaded = 42
	if status := app.UpdateDownload(); status.State != "downloading" || status.Downloaded != 42 {
		t.Fatalf("second download disturbed the first: %+v", status)
	}
	app.update.State = "available"
	app.busy = true
	if status := app.UpdateDownload(); status.State != "failed" || status.Error == "" {
		t.Fatalf("download allowed during a session: %+v", status)
	}
	app.busy = false
	app.update.State = "current"
	if status := app.UpdateDownload(); status.State != "failed" {
		t.Fatalf("download of the installed version allowed: %+v", status)
	}
}
