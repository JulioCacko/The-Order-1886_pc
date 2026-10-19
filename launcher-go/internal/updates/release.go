package updates

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"
)

const repository = "JulioCacko/The-Order-1886_pc"
const goAsset = "order1886-go-windows.zip"

var releaseTag = regexp.MustCompile(`^v[0-9]+\.[0-9]+\.[0-9]+(-go-preview\.[0-9]+)?$`)

type Asset struct {
	Name   string `json:"name"`
	Size   int64  `json:"size"`
	Digest string `json:"digest"`
	URL    string `json:"browser_download_url"`
}

type githubRelease struct {
	Tag       string    `json:"tag_name"`
	Draft     bool      `json:"draft"`
	Published time.Time `json:"published_at"`
	Assets    []Asset   `json:"assets"`
}

type Release struct {
	Tag       string
	Published time.Time
	URL       string
	Identity  Identity
}

func releaseClient(base *http.Client) *http.Client {
	client := http.Client{Timeout: 10 * time.Minute}
	if base != nil {
		client = *base
	}
	client.CheckRedirect = func(request *http.Request, via []*http.Request) error {
		if len(via) >= 10 {
			return errors.New("too many update redirects")
		}
		return trustedURL(request.URL)
	}
	return &client
}

func trustedURL(u *url.URL) error {
	if u.Scheme != "https" || u.User != nil || u.Port() != "" {
		return errors.New("updates require HTTPS without credentials or a custom port")
	}
	switch u.Host {
	case "api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com":
		return nil
	}
	return errors.New("update URL is outside GitHub release hosts")
}

func get(ctx context.Context, client *http.Client, address string) (*http.Response, error) {
	u, err := url.Parse(address)
	if err != nil {
		return nil, err
	}
	if err = trustedURL(u); err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, "GET", address, nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("User-Agent", "Order1886-Go-Updater/1")
	request.Header.Set("Accept", "application/vnd.github+json")
	response, err := client.Do(request)
	if err != nil {
		return nil, err
	}
	if response.StatusCode != http.StatusOK {
		response.Body.Close()
		return nil, fmt.Errorf("update request returned HTTP %d", response.StatusCode)
	}
	return response, nil
}

func fetchMetadata(ctx context.Context, client *http.Client, address string, limit int64) ([]byte, error) {
	response, err := get(ctx, client, address)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if err == nil && int64(len(body)) > limit {
		err = errors.New("release metadata exceeds size limit")
	}
	return body, err
}

// CheckRelease selects the newest published dedicated Go package, including Go previews.
func CheckRelease(ctx context.Context) (Release, error) { return checkRelease(ctx, nil) }

// Update channels. Only the selected channel may offer a release to a player.
const (
	ChannelPreview = "preview"
	ChannelStable  = "stable"
)

// CheckReleaseOn reports the newest release on one channel.
func CheckReleaseOn(ctx context.Context, channel string) (Release, error) {
	return checkReleaseChannel(ctx, nil, channel)
}

func checkRelease(ctx context.Context, base *http.Client) (Release, error) {
	return checkReleaseChannel(ctx, base, ChannelPreview)
}

func checkReleaseChannel(ctx context.Context, base *http.Client, channel string) (Release, error) {
	if channel != ChannelPreview && channel != ChannelStable {
		return Release{}, errors.New("unknown update channel")
	}
	client := releaseClient(base)
	body, err := fetchMetadata(ctx, client, "https://api.github.com/repos/"+repository+"/releases?per_page=100", maxManifest)
	if err != nil {
		return Release{}, err
	}
	var releases []githubRelease
	if err = json.Unmarshal(body, &releases); err != nil {
		return Release{}, err
	}
	var selected *githubRelease
	for i := range releases {
		release := &releases[i]
		if release.Draft || release.Published.IsZero() {
			continue
		}
		if channel == ChannelStable && strings.Contains(release.Tag, "-go-preview.") {
			continue
		}
		for _, asset := range release.Assets {
			if asset.Name == goAsset && (selected == nil || release.Published.After(selected.Published)) {
				selected = release
				break
			}
		}
	}
	if selected == nil {
		return Release{}, errors.New("no dedicated Go Windows release is available")
	}
	if !releaseTag.MatchString(selected.Tag) {
		return Release{}, errors.New("unrecognized update release tag")
	}
	var archive, receipt Asset
	for _, asset := range selected.Assets {
		switch asset.Name {
		case goAsset:
			if archive.Name != "" {
				return Release{}, errors.New("duplicate release archive")
			}
			archive = asset
		case "release-verification.json":
			if receipt.Name != "" {
				return Release{}, errors.New("duplicate release receipt")
			}
			receipt = asset
		}
	}
	for _, asset := range []Asset{archive, receipt} {
		limit := int64(maxArchive)
		if asset.Name == "release-verification.json" {
			limit = maxManifest
		}
		expected := "https://github.com/" + repository + "/releases/download/" + selected.Tag + "/" + asset.Name
		if asset.Name == "" || asset.URL != expected || asset.Size <= 0 || asset.Size > limit || !strings.HasPrefix(asset.Digest, "sha256:") || !validHex(strings.TrimPrefix(asset.Digest, "sha256:"), 32) {
			return Release{}, errors.New("release asset URL, size or SHA256 is invalid")
		}
	}
	body, err = fetchMetadata(ctx, client, receipt.URL, maxManifest)
	if err != nil {
		return Release{}, err
	}
	if int64(len(body)) != receipt.Size || "sha256:"+digestBytes(body) != receipt.Digest {
		return Release{}, errors.New("release receipt integrity check failed")
	}
	var verification struct {
		SourceRevision string          `json:"source_revision"`
		Runtime        RuntimeIdentity `json:"runtime_build"`
		Archive        string          `json:"archive"`
		SHA256         string          `json:"archive_sha256"`
		Bytes          int64           `json:"archive_bytes"`
	}
	if err = json.Unmarshal(bytes.TrimPrefix(body, []byte{0xef, 0xbb, 0xbf}), &verification); err != nil {
		return Release{}, err
	}
	if verification.Archive != goAsset || verification.Bytes != archive.Size || "sha256:"+verification.SHA256 != archive.Digest || !validHex(verification.SourceRevision, 20) || !validHex(verification.Runtime.SHA256, 32) || verification.Runtime.Profile != "order1886" || verification.Runtime.ABI != "order1886-native-1" {
		return Release{}, errors.New("release receipt does not identify this Order package")
	}
	return Release{Tag: selected.Tag, Published: selected.Published, URL: archive.URL, Identity: Identity{Size: archive.Size, SHA256: verification.SHA256, SourceRevision: verification.SourceRevision, RuntimeSHA256: verification.Runtime.SHA256}}, nil
}

func digestBytes(body []byte) string { sum := sha256.Sum256(body); return hex.EncodeToString(sum[:]) }

type progressWriter struct {
	hash        io.Writer
	done, total int64
	progress    func(int64, int64)
}

func (w *progressWriter) Write(p []byte) (int, error) {
	n, err := w.hash.Write(p)
	w.done += int64(n)
	if w.progress != nil {
		w.progress(w.done, w.total)
	}
	return n, err
}

// DownloadRelease writes only to a new file and removes it on cancellation or error.
func DownloadRelease(ctx context.Context, release Release, destination string, progress func(int64, int64)) error {
	return downloadRelease(ctx, nil, release, destination, progress)
}

func downloadRelease(ctx context.Context, base *http.Client, release Release, destination string, progress func(int64, int64)) (err error) {
	if !releaseTag.MatchString(release.Tag) || release.URL != "https://github.com/"+repository+"/releases/download/"+release.Tag+"/"+goAsset || release.Identity.Size <= 0 || release.Identity.Size > maxArchive || !validHex(release.Identity.SHA256, 32) {
		return errors.New("invalid update download identity")
	}
	f, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer func() {
		closeErr := f.Close()
		err = errors.Join(err, closeErr)
		if err != nil {
			err = errors.Join(err, os.Remove(destination))
		}
	}()
	response, err := get(ctx, releaseClient(base), release.URL)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	h := sha256.New()
	writer := &progressWriter{hash: io.MultiWriter(f, h), total: release.Identity.Size, progress: progress}
	n, err := io.Copy(writer, contextReader{ctx, io.LimitReader(response.Body, release.Identity.Size+1)})
	if err != nil {
		return err
	}
	if err = ctx.Err(); err != nil {
		return err
	}
	if n != release.Identity.Size || hex.EncodeToString(h.Sum(nil)) != release.Identity.SHA256 {
		return errors.New("download size or SHA256 verification failed")
	}
	return f.Sync()
}
