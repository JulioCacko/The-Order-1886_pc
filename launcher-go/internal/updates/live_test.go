//go:build live

package updates

import (
	"context"
	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestPublishedPreviewStages runs against the real GitHub release. It is opt-in
// because it needs the network and the published asset:
//
//	go test -tags live ./internal/updates -run TestPublishedPreviewStages -count=1 -v
func TestPublishedPreviewStages(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	release, err := CheckReleaseOn(ctx, ChannelPreview)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("release %s published %s", release.Tag, release.Published.UTC().Format(time.RFC3339))
	work := t.TempDir()
	archive := filepath.Join(work, "package.zip")
	if err = DownloadRelease(ctx, release, archive, nil); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(archive)
	if err != nil {
		t.Fatal(err)
	}
	if info.Size() != release.Identity.Size {
		t.Fatalf("downloaded %d bytes, receipt says %d", info.Size(), release.Identity.Size)
	}
	stage := filepath.Join(work, "stage")
	manifest, err := StageArchive(ctx, archive, stage, release.Identity)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.UpdateABI != recoveryABI {
		t.Fatalf("published package advertises %q, this launcher needs %q", manifest.UpdateABI, recoveryABI)
	}
	if _, err = os.Stat(filepath.Join(stage, "The Order 1886 Legacy.exe")); !os.IsNotExist(err) {
		t.Fatal("published package still ships the retired launcher")
	}
	for _, name := range []string{pkgpath.Launcher(), pkgpath.Play()} {
		if _, statErr := os.Stat(filepath.Join(stage, name)); statErr != nil {
			t.Fatalf("published package is missing %s: %v", name, statErr)
		}
	}
	t.Logf("staged %s: %d files, archive %d bytes, source %s", release.Tag, len(manifest.Files), info.Size(), manifest.SourceRevision)
}
