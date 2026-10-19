package updates

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type routedTransport struct {
	target    *url.URL
	transport http.RoundTripper
}

func (r routedTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	copy := request.Clone(request.Context())
	target := *copy.URL
	target.Scheme = r.target.Scheme
	target.Host = r.target.Host
	copy.URL = &target
	return r.transport.RoundTrip(copy)
}

func releaseServer(t *testing.T, damage string) (*http.Client, []byte) {
	t.Helper()
	archive, identity := packageFixture(t, nil)
	payload, err := os.ReadFile(archive)
	if err != nil {
		t.Fatal(err)
	}
	receipt := map[string]any{"source_revision": identity.SourceRevision, "runtime_build": map[string]any{"game_profile": "order1886", "runtime_abi": "order1886-native-1", "runtime_sha256": identity.RuntimeSHA256}, "archive": "order1886-go-windows.zip", "archive_sha256": identity.SHA256, "archive_bytes": identity.Size}
	if damage == "receipt" {
		receipt["archive_sha256"] = strings.Repeat("0", 64)
	}
	raw, _ := json.Marshal(receipt)
	prefix := "https://github.com/JulioCacko/The-Order-1886_pc/releases/download/v0.1.0-go-preview.6/"
	asset := func(name string, data []byte) map[string]any {
		return map[string]any{"name": name, "size": len(data), "digest": "sha256:" + digest(data), "browser_download_url": prefix + name}
	}
	zipAsset := asset("order1886-go-windows.zip", payload)
	if damage == "url" {
		zipAsset["browser_download_url"] = "https://evil.invalid/order1886-go-windows.zip"
	}
	if damage == "missing-digest" {
		delete(zipAsset, "digest")
	}
	assets := []any{zipAsset, asset("release-verification.json", raw)}
	if damage == "duplicate" {
		assets = append(assets, zipAsset)
	}
	releases := []any{map[string]any{"tag_name": "v0.1.0-go-preview.6", "published_at": "2026-10-19T08:00:00Z", "prerelease": true, "draft": false, "assets": assets}, map[string]any{"tag_name": "v99.0.0", "published_at": "2026-10-20T08:00:00Z", "assets": []any{asset("order1886-windows.zip", payload)}}}
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/releases"):
			if damage == "offline" {
				http.Error(w, "offline", 503)
				return
			}
			json.NewEncoder(w).Encode(releases)
		case strings.HasSuffix(r.URL.Path, "/release-verification.json"):
			if damage == "receipt-bytes" {
				w.Write([]byte("tampered"))
				return
			}
			w.Write(raw)
		case strings.HasSuffix(r.URL.Path, "/order1886-go-windows.zip"):
			if damage == "download" {
				w.Write(payload[:len(payload)/2])
				return
			}
			if damage == "payload" {
				w.Write(append([]byte("!"), payload[1:]...))
				return
			}
			if damage == "oversized" {
				w.Write(append(payload, '!'))
				return
			}
			w.Write(payload)
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(server.Close)
	target, _ := url.Parse(server.URL)
	client := *server.Client()
	client.Transport = routedTransport{target, client.Transport}
	return &client, payload
}

func TestCheckSelectsDedicatedGoPreviewAndBindsReceipt(t *testing.T) {
	client, payload := releaseServer(t, "")
	release, err := checkRelease(context.Background(), client)
	if err != nil {
		t.Fatal(err)
	}
	if release.Tag != "v0.1.0-go-preview.6" || release.Identity.SHA256 != digest(payload) || release.Identity.SourceRevision != strings.Repeat("a", 40) {
		t.Fatalf("wrong release: %+v", release)
	}
	file := filepath.Join(t.TempDir(), "download.zip")
	var progress int64
	if err = downloadRelease(context.Background(), client, release, file, func(done, total int64) {
		if done > total {
			t.Fatal("progress exceeds size")
		}
		progress = done
	}); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(file); string(got) != string(payload) || progress != int64(len(payload)) {
		t.Fatal("download or progress incorrect")
	}
	if _, err = StageArchive(context.Background(), file, filepath.Join(t.TempDir(), "verified"), release.Identity); err != nil {
		t.Fatal(err)
	}
}

func TestReleaseRejectsBadMetadataAndDownload(t *testing.T) {
	for _, damage := range []string{"receipt", "receipt-bytes", "url", "missing-digest", "duplicate", "offline", "download", "payload", "oversized"} {
		t.Run(damage, func(t *testing.T) {
			client, _ := releaseServer(t, damage)
			release, err := checkRelease(context.Background(), client)
			if damage != "download" && damage != "payload" && damage != "oversized" {
				if err == nil {
					t.Fatal("accepted bad release metadata")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			dest := filepath.Join(t.TempDir(), "download.zip")
			if err = downloadRelease(context.Background(), client, release, dest, nil); err == nil {
				t.Fatal("accepted broken download")
			}
			if _, err = os.Stat(dest); !os.IsNotExist(err) {
				t.Fatal("broken download remains")
			}
		})
	}
}

func TestDownloadPreservesExistingFileAndCancels(t *testing.T) {
	client, _ := releaseServer(t, "")
	release, err := checkRelease(context.Background(), client)
	if err != nil {
		t.Fatal(err)
	}
	dest := filepath.Join(t.TempDir(), "player.zip")
	os.WriteFile(dest, []byte("keep"), 0600)
	if err = downloadRelease(context.Background(), client, release, dest, nil); err == nil {
		t.Fatal("overwrote existing file")
	}
	if data, _ := os.ReadFile(dest); string(data) != "keep" {
		t.Fatal("damaged existing file")
	}
	ctx, cancel := context.WithCancel(context.Background())
	dest = filepath.Join(t.TempDir(), "cancelled.zip")
	err = downloadRelease(ctx, client, release, dest, func(done, total int64) { cancel() })
	if err == nil {
		t.Fatal("ignored cancellation")
	}
	if _, err = os.Stat(dest); !os.IsNotExist(err) {
		t.Fatal("cancelled download remains")
	}
}

func TestRedirectsCannotLeaveGitHubAssetHosts(t *testing.T) {
	client := releaseClient(nil)
	for _, location := range []string{"http://github.com/file", "https://evil.invalid/file", "https://user:pass@github.com/file", "https://github.com:8443/file"} {
		request, _ := http.NewRequest("GET", location, nil)
		if err := client.CheckRedirect(request, []*http.Request{{}}); err == nil {
			t.Fatalf("accepted %s", location)
		}
	}
	request, _ := http.NewRequest("GET", "https://release-assets.githubusercontent.com/signed?token=example", nil)
	if err := client.CheckRedirect(request, []*http.Request{{}}); err != nil {
		t.Fatal(err)
	}
	if err := client.CheckRedirect(request, make([]*http.Request, 11)); err == nil {
		t.Fatal("unlimited redirects")
	}
}

func TestReceiptReadIsBounded(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		io.Copy(w, strings.NewReader(strings.Repeat("x", maxManifest+1)))
	}))
	defer server.Close()
	target, _ := url.Parse(server.URL)
	client := *server.Client()
	client.Transport = routedTransport{target, client.Transport}
	if _, err := fetchMetadata(context.Background(), releaseClient(&client), "https://api.github.com/repos/JulioCacko/The-Order-1886_pc/releases", maxManifest); err == nil {
		t.Fatal(fmt.Sprintf("accepted metadata exceeding %d bytes", maxManifest))
	}
}
