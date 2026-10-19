package updates

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const workspace = ".order1886-update"
const journalPath = workspace + "/journal.json"
const recoveryABI = "order1886-update-2"
const journalVersion = 2

type change struct {
	Path string `json:"path"`
	Old  string `json:"old_sha256"`
	New  string `json:"new_sha256"`
}

// launchMode records how the launcher that started the update was started, so
// recovery can restore the same entry point without trusting recorded arguments.
type launchMode struct {
	DirectPlay bool `json:"direct_play"`
}

type journal struct {
	Version   int              `json:"version"`
	Directory string           `json:"directory"`
	Phase     string           `json:"phase"`
	Files     []change         `json:"files"`
	Session   *sessionLocation `json:"session,omitempty"`
	Launch    *launchMode      `json:"launch,omitempty"`
}

// Transaction holds the installation lock until Close. The caller must also hold
// the player-session lock and stop the launcher/worker before Apply or Rollback.
type Transaction struct {
	root   *os.Root
	lock   *os.File
	record journal
}

func (t *Transaction) Close() error {
	var err error
	if t.lock != nil {
		err = t.lock.Close()
		t.lock = nil
	}
	if t.root != nil {
		err = errors.Join(err, t.root.Close())
		t.root = nil
	}
	return err
}

func (t *Transaction) Phase() string { return t.record.Phase }

func noLinks(root *os.Root, name string) error {
	parts := strings.Split(name, "/")
	for i := range parts {
		info, err := root.Lstat(strings.Join(parts[:i+1], "/"))
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			return err
		}
		if info.Mode().Type() & ^os.ModeDir != 0 || i < len(parts)-1 && !info.IsDir() {
			return fmt.Errorf("linked or special update path: %s", name)
		}
	}
	return nil
}

func unlinkedDirectory(directory string) (*os.Root, error) {
	absolute, err := filepath.Abs(directory)
	if err != nil {
		return nil, err
	}
	for current := absolute; ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil {
			return nil, err
		}
		if info.Mode().Type() != os.ModeDir {
			return nil, errors.New("updates require an installation without linked directory components")
		}
		if current == filepath.Dir(current) {
			break
		}
	}
	return os.OpenRoot(absolute)
}

func openInstallation(directory string) (_ *Transaction, err error) {
	root, err := unlinkedDirectory(directory)
	if err != nil {
		return nil, err
	}
	t := &Transaction{root: root}
	defer func() {
		if err != nil {
			t.Close()
		}
	}()
	if _, gitErr := root.Lstat(".git"); !os.IsNotExist(gitErr) {
		return nil, errors.New("source checkouts cannot use the portable updater")
	}
	if err = noLinks(root, workspace+"/lock"); err != nil {
		return nil, err
	}
	if err = root.Mkdir(workspace, 0700); err != nil && !os.IsExist(err) {
		return nil, err
	}
	t.lock, err = root.OpenFile(workspace+"/lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = lockFile(t.lock); err != nil {
		return nil, fmt.Errorf("another updater is active: %w", err)
	}
	return t, nil
}

func readSmall(root *os.Root, name string) ([]byte, error) {
	if err := noLinks(root, name); err != nil {
		return nil, err
	}
	f, err := root.Open(name)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > maxManifest {
		return nil, errors.New("invalid update metadata size or type")
	}
	data, err := io.ReadAll(io.LimitReader(f, maxManifest+1))
	if len(data) > maxManifest {
		return nil, errors.New("update metadata is too large")
	}
	return data, err
}

func fileHash(ctx context.Context, root *os.Root, name string) (string, error) {
	if err := noLinks(root, name); err != nil {
		return "", err
	}
	f, err := root.Open(name)
	if os.IsNotExist(err) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() || info.Size() > maxFile {
		return "", fmt.Errorf("not a regular package file: %s", name)
	}
	hash, n, err := hashReader(ctx, io.LimitReader(f, maxFile+1))
	if n > maxFile {
		return "", errors.New("package file exceeds size limit")
	}
	return hash, err
}

func directoryFiles(ctx context.Context, root *os.Root, identity *Identity) (Manifest, map[string]string, error) {
	var m Manifest
	body, err := readSmall(root, "package-manifest.json")
	if err != nil {
		return m, nil, err
	}
	if identity != nil && digestBytes(body) != identity.ManifestSHA256 {
		return m, nil, errors.New("stage manifest changed after archive verification")
	}
	clean := strings.TrimPrefix(string(body), "\ufeff")
	if err = json.Unmarshal([]byte(clean), &m); err != nil {
		return m, nil, err
	}
	if !validHex(m.SourceRevision, 20) || !validHex(m.RuntimeSHA256, 32) {
		return m, nil, errors.New("invalid installed build identity")
	}
	if identity == nil {
		identity = &Identity{SourceRevision: m.SourceRevision, RuntimeSHA256: m.RuntimeSHA256}
	}
	m, err = decodeManifest(body, *identity)
	if err != nil {
		return m, nil, err
	}
	files := map[string]string{"package-manifest.json": digestBytes(body)}
	aliases := map[string]bool{}
	for _, entry := range m.Files {
		if err = packagePath(entry.Path); err != nil {
			return m, nil, err
		}
		key := strings.ToUpper(entry.Path)
		if entry.Path == "package-manifest.json" || aliases[key] || !validHex(entry.SHA256, 32) {
			return m, nil, errors.New("invalid directory manifest entry")
		}
		aliases[key] = true
		actual, err := fileHash(ctx, root, entry.Path)
		if err != nil {
			return m, nil, err
		}
		if actual != entry.SHA256 {
			return m, nil, fmt.Errorf("package file is missing or modified: %s", entry.Path)
		}
		files[entry.Path] = entry.SHA256
	}
	for _, name := range []string{"The Order 1886.exe", "Play The Order 1886.exe", "bin/order1886-worker.exe", "bin/order1886-runtime.exe", "bin/runtime-build.json"} {
		if files[name] == "" {
			return m, nil, fmt.Errorf("required installed file is missing: %s", name)
		}
	}
	if files["bin/order1886-runtime.exe"] != m.RuntimeSHA256 {
		return m, nil, errors.New("installed runtime differs from manifest")
	}
	raw, err := readSmall(root, "bin/runtime-build.json")
	if err != nil {
		return m, nil, err
	}
	var runtime RuntimeIdentity
	if err = json.Unmarshal([]byte(strings.TrimPrefix(string(raw), "\ufeff")), &runtime); err != nil {
		return m, nil, err
	}
	if runtime != m.RuntimeBuild {
		return m, nil, errors.New("installed runtime receipt differs from manifest")
	}
	return m, files, nil
}

// orderOf ranks a replacement step. Deletions run after every replacement, so a
// retired entry point never disappears before its replacement exists, and the
// manifest is always the final change.
func orderOf(name string, deletion bool) int {
	switch name {
	case "The Order 1886.exe":
		return 0
	case "Play The Order 1886.exe":
		return 1
	case "package-manifest.json":
		return 4
	}
	if deletion {
		return 3
	}
	return 2
}

func beforeChange(a, b change) bool {
	first, second := orderOf(a.Path, a.New == ""), orderOf(b.Path, b.New == "")
	if first != second {
		return first < second
	}
	return a.Path < b.Path
}

func (t *Transaction) readJournal() error {
	body, err := readSmall(t.root, journalPath)
	if err != nil {
		return err
	}
	if err = json.Unmarshal(body, &t.record); err != nil {
		return err
	}
	if err = validateJournal(t.record); err != nil {
		return err
	}
	return noLinks(t.root, t.record.Directory)
}

func validateJournal(r journal) error {
	if err := validateSessionLocation(r.Session); err != nil {
		return err
	}
	if r.Version != journalVersion || !strings.HasPrefix(r.Directory, workspace+"/txn-") || !validHex(strings.TrimPrefix(r.Directory, workspace+"/txn-"), 16) || len(r.Files) == 0 || len(r.Files) > maxEntries {
		return errors.New("invalid recovery journal")
	}
	switch r.Phase {
	case "prepared", "applying", "applied", "rolling_back", "rolled_back":
	default:
		return errors.New("unknown recovery phase")
	}
	seen := map[string]bool{}
	manifest := false
	for i, entry := range r.Files {
		if err := packagePath(entry.Path); err != nil {
			return err
		}
		key := strings.ToUpper(entry.Path)
		if seen[key] || entry.Old == entry.New || entry.Old != "" && !validHex(entry.Old, 32) || entry.New != "" && !validHex(entry.New, 32) || i > 0 && !beforeChange(r.Files[i-1], entry) {
			return errors.New("invalid recovery file list")
		}
		seen[key] = true
		if entry.Path == "package-manifest.json" {
			manifest = entry.Old != "" && entry.New != ""
		}
	}
	if !manifest {
		return errors.New("recovery manifest identity is missing")
	}
	return nil
}

// OpenTransaction reopens the last journal; pending phases must recover before worker startup.
func OpenTransaction(directory string) (_ *Transaction, err error) {
	t, err := openInstallation(directory)
	if err != nil {
		return nil, err
	}
	if err = t.readJournal(); err != nil {
		t.Close()
		return nil, err
	}
	return t, nil
}

func randomName() (string, error) {
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(bytes[:]), nil
}

func copyVerified(ctx context.Context, source *os.Root, from string, destination *os.Root, to, expected string) (err error) {
	if err = noLinks(source, from); err != nil {
		return err
	}
	if err = noLinks(destination, to); err != nil {
		return err
	}
	input, err := source.Open(from)
	if err != nil {
		return err
	}
	defer input.Close()
	if err = destination.MkdirAll(path.Dir(to), 0700); err != nil {
		return err
	}
	output, err := destination.OpenFile(to, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer func() {
		err = errors.Join(err, output.Close())
		if err != nil {
			err = errors.Join(err, destination.Remove(to))
		}
	}()
	// Rehash while copying, so edits after validation never become trusted backups.
	hash, count, err := hashReader(ctx, io.TeeReader(io.LimitReader(input, maxFile+1), output))
	if err != nil {
		return err
	}
	if count > maxFile || hash != expected {
		return fmt.Errorf("package changed while copying: %s", from)
	}
	return output.Sync()
}

func (t *Transaction) saveJournal(phase string) (err error) {
	record := t.record
	record.Phase = phase
	if err = validateJournal(record); err != nil {
		return err
	}
	body, err := json.Marshal(record)
	if err != nil {
		return err
	}
	if len(body) > maxManifest {
		return errors.New("recovery metadata is too large")
	}
	if err = noLinks(t.root, journalPath); err != nil {
		return err
	}
	name, err := randomName()
	if err != nil {
		return err
	}
	temp := workspace + "/journal-" + name + ".tmp"
	f, err := t.root.OpenFile(temp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	defer func() {
		if err != nil {
			_ = t.root.Remove(temp)
		}
	}()
	_, err = f.Write(body)
	err = errors.Join(err, f.Sync(), f.Close())
	if err != nil {
		return err
	}
	if err = t.root.Rename(temp, journalPath); err != nil {
		return err
	}
	t.record = record
	return nil
}

// PrepareTransaction verifies and backs up only manifest-owned changes. It leaves
// the installation untouched. The trusted stage must advertise the recovery ABI.
func PrepareTransaction(ctx context.Context, directory, stage string, identity Identity) (_ *Transaction, err error) {
	t, err := openInstallation(directory)
	if err != nil {
		return nil, err
	}
	defer func() {
		if err != nil {
			t.Close()
		}
	}()
	if journalErr := t.readJournal(); journalErr == nil {
		if t.Phase() != "applied" && t.Phase() != "rolled_back" {
			return nil, errors.New("recover the pending update before preparing another")
		}
	} else if !os.IsNotExist(journalErr) {
		return nil, journalErr
	}
	stageRoot, err := unlinkedDirectory(stage)
	if err != nil {
		return nil, err
	}
	defer stageRoot.Close()
	newManifest, newFiles, err := directoryFiles(ctx, stageRoot, &identity)
	if err != nil {
		return nil, err
	}
	if newManifest.UpdateABI != recoveryABI {
		return nil, errors.New("new launcher does not advertise compatible update recovery")
	}
	if err = fs.WalkDir(stageRoot.FS(), ".", func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if name == "." {
			return nil
		}
		if err = noLinks(stageRoot, name); err != nil {
			return err
		}
		if !entry.IsDir() && newFiles[name] == "" {
			return fmt.Errorf("unowned file in update stage: %s", name)
		}
		return nil
	}); err != nil {
		return nil, err
	}
	_, oldFiles, err := directoryFiles(ctx, t.root, nil)
	if err != nil {
		return nil, err
	}
	names := map[string]bool{}
	for name := range oldFiles {
		names[name] = true
	}
	for name := range newFiles {
		names[name] = true
	}
	var changes []change
	for name := range names {
		if oldFiles[name] == newFiles[name] {
			continue
		}
		if oldFiles[name] == "" {
			existing, err := fileHash(ctx, t.root, name)
			if err != nil {
				return nil, err
			}
			if existing != "" {
				return nil, fmt.Errorf("new package path contains an unowned file: %s", name)
			}
		}
		changes = append(changes, change{Path: name, Old: oldFiles[name], New: newFiles[name]})
	}
	if len(changes) == 0 {
		return nil, errors.New("this package is already installed")
	}
	sort.Slice(changes, func(i, j int) bool { return beforeChange(changes[i], changes[j]) })
	name, err := randomName()
	if err != nil {
		return nil, err
	}
	folder := workspace + "/txn-" + name
	if err = t.root.Mkdir(folder, 0700); err != nil {
		return nil, err
	}
	defer func() {
		if err != nil {
			err = errors.Join(err, t.root.RemoveAll(folder))
		}
	}()
	for _, entry := range changes {
		if entry.Old != "" {
			if err = copyVerified(ctx, t.root, entry.Path, t.root, folder+"/previous/"+entry.Path, entry.Old); err != nil {
				return nil, err
			}
		}
		if entry.New != "" {
			if err = copyVerified(ctx, stageRoot, entry.Path, t.root, folder+"/next/"+entry.Path, entry.New); err != nil {
				return nil, err
			}
		}
	}
	t.record = journal{Version: journalVersion, Directory: folder, Files: changes}
	if err = t.saveJournal("prepared"); err != nil {
		return nil, err
	}
	return t, nil
}

func (t *Transaction) preflight(ctx context.Context, rollback bool) error {
	for _, entry := range t.record.Files {
		current, err := fileHash(ctx, t.root, entry.Path)
		if err != nil {
			return err
		}
		if current != entry.Old && current != entry.New {
			return fmt.Errorf("package has an unexpected edit: %s", entry.Path)
		}
		if rollback && current == entry.Old {
			continue
		}
		needed := map[string]string{"previous": entry.Old}
		if !rollback {
			needed["next"] = entry.New
		}
		for folder, expected := range needed {
			if expected == "" {
				continue
			}
			actual, err := fileHash(ctx, t.root, t.record.Directory+"/"+folder+"/"+entry.Path)
			if err != nil {
				return err
			}
			if actual != expected {
				return fmt.Errorf("update backup or stage was modified: %s", entry.Path)
			}
		}
	}
	return nil
}

func (t *Transaction) replace(ctx context.Context, entry change, rollback bool) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	current, err := fileHash(ctx, t.root, entry.Path)
	if err != nil {
		return err
	}
	if current != entry.Old && current != entry.New {
		return fmt.Errorf("package changed during update: %s", entry.Path)
	}
	expected, folder := entry.New, "next"
	if rollback {
		expected, folder = entry.Old, "previous"
	}
	if current == expected {
		return nil
	}
	if expected == "" {
		return t.root.Remove(entry.Path)
	}
	name, err := randomName()
	if err != nil {
		return err
	}
	temp := path.Join(path.Dir(entry.Path), ".order1886-"+name+".tmp")
	if err = copyVerified(ctx, t.root, t.record.Directory+"/"+folder+"/"+entry.Path, t.root, temp, expected); err != nil {
		return err
	}
	defer t.root.Remove(temp)
	return t.root.Rename(temp, entry.Path)
}

func (t *Transaction) Apply(ctx context.Context, progress func(int, int)) (err error) {
	if t.Phase() != "prepared" {
		return errors.New("only a prepared update can be installed")
	}
	if t.record.Session == nil {
		return errors.New("record the player state before installing an update")
	}
	if err = t.preflight(ctx, false); err != nil {
		return err
	}
	if err = t.saveJournal("applying"); err != nil {
		return err
	}
	defer func() {
		if err != nil {
			err = errors.Join(err, t.Rollback(context.Background(), nil))
		}
	}()
	for i, entry := range t.record.Files {
		if err = t.replace(ctx, entry, false); err != nil {
			return err
		}
		if progress != nil {
			progress(i+1, len(t.record.Files))
		}
	}
	if err = ctx.Err(); err != nil {
		return err
	}
	return t.saveJournal("applied")
}

func (t *Transaction) Rollback(ctx context.Context, progress func(int, int)) error {
	if t.Phase() == "rolled_back" {
		return nil
	}
	if err := t.preflight(ctx, true); err != nil {
		return err
	}
	if err := t.saveJournal("rolling_back"); err != nil {
		return err
	}
	for i := len(t.record.Files) - 1; i >= 0; i-- {
		if err := t.replace(ctx, t.record.Files[i], true); err != nil {
			return err
		}
		if progress != nil {
			progress(len(t.record.Files)-i, len(t.record.Files))
		}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return t.saveJournal("rolled_back")
}

// BindLaunch records which entry point started the update, so a recovery relaunch
// restores the same one instead of trusting arbitrary recorded arguments.
func (t *Transaction) BindLaunch(directPlay bool) error {
	if t.Phase() != "prepared" {
		return errors.New("choose the relaunch mode before starting the update")
	}
	mode := launchMode{DirectPlay: directPlay}
	if t.record.Launch != nil && *t.record.Launch != mode {
		return errors.New("recovery must keep the original relaunch mode")
	}
	previous := t.record.Launch
	t.record.Launch = &mode
	if err := t.saveJournal("prepared"); err != nil {
		t.record.Launch = previous
		return err
	}
	return nil
}

func (t *Transaction) LaunchMode() (directPlay bool, recorded bool) {
	if t.record.Launch == nil {
		return false, false
	}
	return t.record.Launch.DirectPlay, true
}

// OpenInstallation takes only the installation lock, for work that must run
// before any journal exists, such as retention after a completed update.
func OpenInstallation(directory string) (*Transaction, error) { return openInstallation(directory) }

// Retain removes superseded transaction directories, keeping the transaction the
// current journal describes and the newest completed ones. A journal that cannot
// be read stops retention instead of guessing which directory is live.
func (t *Transaction) Retain(keep int) (_ []string, err error) {
	if keep < 1 {
		return nil, errors.New("retention must keep at least one transaction")
	}
	active := ""
	if _, statErr := t.root.Lstat(journalPath); statErr == nil {
		if err = t.readJournal(); err != nil {
			return nil, err
		}
		if t.record.Phase != "applied" && t.record.Phase != "rolled_back" {
			active = t.record.Directory
		}
	} else if !os.IsNotExist(statErr) {
		return nil, statErr
	}
	type directory struct {
		name   string
		change time.Time
	}
	var directories []directory
	items, err := fs.ReadDir(t.root.FS(), workspace)
	if err != nil {
		return nil, err
	}
	for _, item := range items {
		suffix := strings.TrimPrefix(item.Name(), "txn-")
		if !item.IsDir() || suffix == item.Name() || !validHex(suffix, 16) {
			continue
		}
		info, statErr := fs.Stat(t.root.FS(), workspace+"/"+item.Name())
		if statErr != nil {
			return nil, statErr
		}
		directories = append(directories, directory{workspace + "/" + item.Name(), info.ModTime()})
	}
	sort.Slice(directories, func(i, j int) bool {
		if !directories[i].change.Equal(directories[j].change) {
			return directories[i].change.After(directories[j].change)
		}
		return directories[i].name < directories[j].name
	})
	var removed []string
	kept := 0
	if active != "" {
		kept = 1
	}
	for _, entry := range directories {
		if entry.name == active {
			continue
		}
		if kept < keep {
			kept++
			continue
		}
		if err = t.root.RemoveAll(entry.name); err != nil {
			return removed, err
		}
		removed = append(removed, entry.name)
	}
	return removed, nil
}
