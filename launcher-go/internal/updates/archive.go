// Package updates stages dedicated Order packages without changing installed files.
package updates

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"io"
	"os"
	"strings"
	"unicode/utf8"
)

const (
	maxArchive  = 1 << 30
	maxExpanded = 4 << 30
	maxFile     = 1 << 30
	maxManifest = 4 << 20
	maxEntries  = 10000
	archiveRoot = "The Order 1886/"
)

type Identity struct {
	Size           int64
	SHA256         string
	SourceRevision string
	RuntimeSHA256  string
	ManifestSHA256 string
}

type File struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
}

type RuntimeIdentity struct {
	Profile string `json:"game_profile"`
	ABI     string `json:"runtime_abi"`
	SHA256  string `json:"runtime_sha256"`
}

type Manifest struct {
	SHA256         string          `json:"-"`
	Product        string          `json:"product"`
	Launcher       string          `json:"launcher"`
	UpdateABI      string          `json:"update_abi"`
	SourceRevision string          `json:"source_revision"`
	SourceDirty    *bool           `json:"source_dirty"`
	RuntimeSHA256  string          `json:"runtime_sha256"`
	RuntimeBuild   RuntimeIdentity `json:"runtime_build"`
	Files          []File          `json:"files"`
}

func validHex(value string, size int) bool {
	b, err := hex.DecodeString(value)
	return err == nil && len(b) == size
}

// Windows aliases must be rejected even when validation runs on another OS.
func packagePath(name string) error {
	if name == "" || !utf8.ValidString(name) || strings.ContainsAny(name, `\:<>"|?*`) {
		return fmt.Errorf("unsafe package path %q", name)
	}
	for _, part := range strings.Split(name, "/") {
		if part == "" || part == "." || part == ".." || strings.HasSuffix(part, ".") || strings.HasSuffix(part, " ") {
			return fmt.Errorf("unsafe package component %q", part)
		}
		for _, c := range part {
			if c < 32 || c == 127 {
				return errors.New("control character in package path")
			}
		}
		base := strings.ToUpper(strings.SplitN(part, ".", 2)[0])
		reserved := base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" || base == "CONIN$" || base == "CONOUT$"
		if len(base) > 3 && (strings.HasPrefix(base, "COM") || strings.HasPrefix(base, "LPT")) {
			number := strings.TrimPrefix(strings.TrimPrefix(base, "COM"), "LPT")
			reserved = reserved || strings.Contains("123456789¹²³", number) && len([]rune(number)) == 1
		}
		if reserved {
			return fmt.Errorf("reserved Windows filename %q", part)
		}
	}
	root := strings.SplitN(name, "/", 2)[0]
	switch root {
	case "bin", "_internal", "notices":
		return nil
	case "The Order 1886.exe", "Play The Order 1886.exe", "The Order 1886 Legacy.exe", "LICENSE", "QUICKSTART.txt", "README-Order1886.txt", "package-manifest.json":
		if root == name {
			return nil
		}
	}
	return fmt.Errorf("path is not package-owned: %q", name)
}

type contextReader struct {
	ctx    context.Context
	reader io.Reader
}

func (r contextReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.reader.Read(p)
}

func hashReader(ctx context.Context, reader io.Reader) (string, int64, error) {
	h := sha256.New()
	n, err := io.Copy(h, contextReader{ctx, reader})
	return hex.EncodeToString(h.Sum(nil)), n, err
}

func readEntry(file *zip.File, limit int64) ([]byte, error) {
	r, err := file.Open()
	if err != nil {
		return nil, err
	}
	defer r.Close()
	b, err := io.ReadAll(io.LimitReader(r, limit+1))
	if err == nil && int64(len(b)) > limit {
		err = errors.New("package metadata is too large")
	}
	return b, err
}

func decodeManifest(body []byte, identity Identity) (Manifest, error) {
	var m Manifest
	if err := json.Unmarshal(bytes.TrimPrefix(body, []byte{0xef, 0xbb, 0xbf}), &m); err != nil {
		return m, err
	}
	if m.Product != "The Order: 1886" || !strings.HasPrefix(m.Launcher, "Go / Wails v2.") || m.SourceDirty == nil || *m.SourceDirty {
		return m, errors.New("package is not a clean dedicated Order Go build")
	}
	if m.SourceRevision != identity.SourceRevision || m.RuntimeSHA256 != identity.RuntimeSHA256 || m.RuntimeBuild.SHA256 != m.RuntimeSHA256 || m.RuntimeBuild.Profile != "order1886" || m.RuntimeBuild.ABI != "order1886-native-1" {
		return m, errors.New("package source or runtime does not match the release")
	}
	if len(m.Files) == 0 || len(m.Files) >= maxEntries {
		return m, errors.New("invalid package manifest length")
	}
	return m, nil
}

// StageArchive creates a NEW private stage. It never writes to an existing installation.
// The caller must supply identity obtained from verified release metadata.
func StageArchive(ctx context.Context, archive, destination string, identity Identity) (manifest Manifest, err error) {
	if identity.Size <= 0 || identity.Size > maxArchive || !validHex(identity.SHA256, 32) || !validHex(identity.SourceRevision, 20) || !validHex(identity.RuntimeSHA256, 32) {
		return manifest, errors.New("invalid release identity")
	}
	f, err := os.Open(archive)
	if err != nil {
		return manifest, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return manifest, err
	}
	if !info.Mode().IsRegular() || info.Size() != identity.Size {
		return manifest, errors.New("archive size or type does not match release")
	}
	hash, n, err := hashReader(ctx, io.LimitReader(f, maxArchive+1))
	if err != nil {
		return manifest, err
	}
	if n != identity.Size || hash != identity.SHA256 {
		return manifest, errors.New("archive SHA256 does not match release")
	}
	z, err := zip.NewReader(f, identity.Size)
	if err != nil {
		return manifest, err
	}
	if len(z.File) == 0 || len(z.File) > maxEntries {
		return manifest, errors.New("invalid archive entry count")
	}
	entries := make(map[string]*zip.File)
	seen := make(map[string]bool)
	spellings := make(map[string]string)
	var expanded uint64
	for _, entry := range z.File {
		if err = ctx.Err(); err != nil {
			return manifest, err
		}
		mode := entry.Mode()
		if mode.Type() & ^os.ModeDir != 0 {
			return manifest, fmt.Errorf("special archive file %q", entry.Name)
		}
		if entry.Name == archiveRoot && entry.FileInfo().IsDir() {
			continue
		}
		if !strings.HasPrefix(entry.Name, archiveRoot) {
			return manifest, errors.New("unexpected archive root")
		}
		name := strings.TrimPrefix(entry.Name, archiveRoot)
		if entry.FileInfo().IsDir() {
			name = strings.TrimSuffix(name, "/")
		}
		if err = packagePath(name); err != nil {
			return manifest, err
		}
		parts := strings.Split(name, "/")
		for i := range parts {
			prefix := strings.Join(parts[:i+1], "/")
			folded := strings.ToUpper(prefix)
			if previous := spellings[folded]; previous != "" && previous != prefix {
				return manifest, fmt.Errorf("case-aliased package path %q", name)
			}
			spellings[folded] = prefix
		}
		key := strings.ToUpper(name)
		if seen[key] {
			return manifest, fmt.Errorf("duplicate archive path %q", name)
		}
		seen[key] = true
		if mode.IsDir() {
			continue
		}
		if entry.UncompressedSize64 > maxFile {
			return manifest, errors.New("archive file exceeds size limit")
		}
		expanded += entry.UncompressedSize64
		if expanded > maxExpanded {
			return manifest, errors.New("archive exceeds expanded size limit")
		}
		entries[name] = entry
	}
	metadata := entries["package-manifest.json"]
	if metadata == nil {
		return manifest, errors.New("package manifest is missing")
	}
	body, err := readEntry(metadata, maxManifest)
	if err != nil {
		return manifest, err
	}
	manifest, err = decodeManifest(body, identity)
	if err != nil {
		return manifest, err
	}
	manifest.SHA256 = digestBytes(body)
	if identity.ManifestSHA256 != "" && manifest.SHA256 != identity.ManifestSHA256 {
		return manifest, errors.New("manifest SHA256 differs from verified release metadata")
	}
	owned := make(map[string]string)
	for _, entry := range manifest.Files {
		if err = packagePath(entry.Path); err != nil {
			return manifest, err
		}
		if entry.Path == "package-manifest.json" || !validHex(entry.SHA256, 32) {
			return manifest, errors.New("invalid manifest file identity")
		}
		key := strings.ToUpper(entry.Path)
		if owned[key] != "" {
			return manifest, errors.New("duplicate manifest path")
		}
		owned[key] = entry.SHA256
		if entries[entry.Path] == nil {
			return manifest, fmt.Errorf("manifest file is missing: %s", entry.Path)
		}
	}
	if len(entries) != len(manifest.Files)+1 {
		return manifest, errors.New("archive contains unmanifested files")
	}
	for _, required := range pkgpath.Required() {
		if entries[required] == nil {
			return manifest, fmt.Errorf("required package file is missing: %s", required)
		}
	}
	if owned[strings.ToUpper("bin/order1886-runtime.exe")] != identity.RuntimeSHA256 {
		return manifest, errors.New("runtime hash differs from manifest")
	}
	runtimeBody, err := readEntry(entries["bin/runtime-build.json"], maxManifest)
	if err != nil {
		return manifest, err
	}
	var runtime RuntimeIdentity
	if err = json.Unmarshal(bytes.TrimPrefix(runtimeBody, []byte{0xef, 0xbb, 0xbf}), &runtime); err != nil {
		return manifest, err
	}
	if runtime != manifest.RuntimeBuild {
		return manifest, errors.New("runtime receipt differs from package manifest")
	}
	if err = os.Mkdir(destination, 0700); err != nil {
		return manifest, err
	}
	defer func() {
		if err != nil {
			err = errors.Join(err, os.RemoveAll(destination))
		}
	}()
	root, err := os.OpenRoot(destination)
	if err != nil {
		return manifest, err
	}
	defer root.Close()
	for name, entry := range entries {
		if err = ctx.Err(); err != nil {
			return manifest, err
		}
		if slash := strings.LastIndex(name, "/"); slash >= 0 {
			if err = root.MkdirAll(name[:slash], 0700); err != nil {
				return manifest, err
			}
		}
		var output *os.File
		output, err = root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return manifest, err
		}
		var input io.ReadCloser
		input, err = entry.Open()
		if err != nil {
			output.Close()
			return manifest, err
		}
		h := sha256.New()
		var count int64
		count, err = io.Copy(io.MultiWriter(output, h), contextReader{ctx, io.LimitReader(input, int64(entry.UncompressedSize64)+1)})
		err = errors.Join(err, input.Close(), output.Sync(), output.Close())
		if err != nil {
			return manifest, err
		}
		if uint64(count) != entry.UncompressedSize64 {
			return manifest, errors.New("expanded file size differs from archive metadata")
		}
		if name != "package-manifest.json" && hex.EncodeToString(h.Sum(nil)) != owned[strings.ToUpper(name)] {
			return manifest, fmt.Errorf("package file SHA256 mismatch: %s", name)
		}
	}
	return manifest, nil
}
