// Package updatehost runs a packaged update outside the launcher that started it.
//
// Windows cannot replace the running launcher executable or the worker libraries it
// has loaded, so the launcher copies itself into the update workspace, hands the
// prepared transaction to that copy, and exits. The copy holds both locks, performs
// the replacement or the recovery, records the outcome and relaunches the launcher.
package updatehost

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updates"
)

const (
	// ActionApply installs a prepared transaction.
	ActionApply = "apply"
	// ActionRecover rolls back an interrupted transaction before the worker loads.
	ActionRecover = "recover"
	// ActionRollback restores the previous package after a completed update.
	ActionRollback = "rollback"

	// DefaultTimeout bounds waiting for the initiating processes and the locks.
	DefaultTimeout = 90 * time.Second

	workspace     = ".order1886-update"
	resultName    = "last-result.json"
	maxResultSize = 64 << 10
)

// Candidate is a verified update stage and the identity that produced it.
type Candidate struct {
	Stage    string
	Identity updates.Identity
}

// Options describes one helper run.
type Options struct {
	Installation string
	Action       string
	// ParentPID and ParentClock identify the process that must exit first. The
	// creation time prevents a reused process id from matching.
	ParentPID   int
	ParentClock time.Time
	// NoRelaunch keeps the helper from starting the launcher again; isolated
	// tests and packaged smoke checks use it.
	NoRelaunch bool
	// ConfirmRestore marks an explicit user request to retry a failed recovery.
	ConfirmRestore bool
	Timeout        time.Duration
}

// Result is the recorded outcome of a helper run.
type Result struct {
	Action         string `json:"action"`
	Phase          string `json:"phase,omitempty"`
	StateDirectory string `json:"state_directory,omitempty"`
	Recovered      bool   `json:"recovered"`
	Relaunched     bool   `json:"relaunched"`
	RecoveryFailed bool   `json:"recovery_failed"`
	Message        string `json:"message,omitempty"`
	When           string `json:"when"`
}

// Prepare verifies the staged candidate and records the player state and relaunch
// mode a later recovery needs. It leaves the installation untouched.
func Prepare(installation string, candidate Candidate, state string, directPlay bool) error {
	tx, err := updates.PrepareTransaction(context.Background(), installation, candidate.Stage, candidate.Identity)
	if err != nil {
		return err
	}
	defer tx.Close()
	if err = tx.BindSession(state); err != nil {
		return err
	}
	return tx.BindLaunch(directPlay)
}

// CopySelf writes the running executable into the update workspace so that the
// launcher's own file and loaded libraries stay replaceable.
func CopySelf(installation string) (_ string, err error) {
	executable, err := os.Executable()
	if err != nil {
		return "", err
	}
	source, err := os.Open(executable)
	if err != nil {
		return "", err
	}
	defer source.Close()
	target := filepath.Join(installation, filepath.FromSlash(workspace), "helper"+executableSuffix())
	if err = os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
		return "", err
	}
	copyFile, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o700)
	if err != nil {
		return "", err
	}
	defer func() {
		err = errors.Join(err, copyFile.Close())
		if err != nil {
			err = errors.Join(err, os.Remove(target))
		}
	}()
	if _, err = io.Copy(copyFile, source); err != nil {
		return "", err
	}
	return target, copyFile.Sync()
}

// Command builds the helper invocation. Arguments stay an array: nothing here is
// ever interpreted by a shell.
func Command(helper string, options Options) *exec.Cmd {
	command := exec.Command(helper,
		"--update-helper",
		"--update-action", options.Action,
		"--update-installation", options.Installation,
	)
	if options.ParentPID > 0 {
		command.Args = append(command.Args, "--update-parent-pid", fmt.Sprint(options.ParentPID))
		if !options.ParentClock.IsZero() {
			command.Args = append(command.Args, "--update-parent-clock", options.ParentClock.UTC().Format(time.RFC3339Nano))
		}
	}
	if options.NoRelaunch {
		command.Args = append(command.Args, "--no-relaunch")
	}
	if options.ConfirmRestore {
		command.Args = append(command.Args, "--confirm-restore")
	}
	command.Dir = options.Installation
	configureHelperProcess(command)
	return command
}

// Run performs one helper action in the current process.
func Run(ctx context.Context, options Options) (Result, error) {
	installation, err := filepath.Abs(options.Installation)
	if err != nil {
		return Result{}, err
	}
	if options.Timeout <= 0 {
		options.Timeout = DefaultTimeout
	}
	result := Result{Action: options.Action, When: time.Now().UTC().Format(time.RFC3339)}
	deadline := time.Now().Add(options.Timeout)
	if options.ParentPID > 0 {
		if err = waitForExit(ctx, options.ParentPID, options.ParentClock, deadline); err != nil {
			result.Message = err.Error()
			result.RecoveryFailed = options.Action != ActionApply
			writeResult(installation, result)
			return result, err
		}
	}
	switch options.Action {
	case ActionApply:
		return runApply(ctx, installation, options, deadline, result)
	case ActionRecover, ActionRollback:
		return runRecovery(ctx, installation, options, deadline, result)
	default:
		return result, fmt.Errorf("unsupported update action %q", options.Action)
	}
}

func runApply(ctx context.Context, installation string, options Options, deadline time.Time, result Result) (Result, error) {
	phase, exists, err := updates.JournalPhase(installation)
	if err != nil {
		return result, err
	}
	if !exists || phase != "prepared" {
		// Nothing was staged: leave the installation without updater files.
		result.Message = "no prepared update is waiting to be installed"
		return result, errors.New(result.Message)
	}
	tx, err := openPending(ctx, installation, deadline)
	if err != nil {
		result.Message = err.Error()
		writeResult(installation, result)
		return result, err
	}
	defer tx.Close()
	state, err := tx.SessionDirectory()
	if err != nil {
		result.Message = err.Error()
		writeResult(installation, result)
		return result, err
	}
	result.StateDirectory = state
	session, err := lockSession(ctx, state, deadline)
	if err != nil {
		// The game still holds the session lock: nothing was touched, so this is not
		// a failed update and must not block a later attempt.
		result.Message = err.Error()
		writeResult(installation, result)
		return result, err
	}
	defer session.Close()
	if err = tx.Apply(ctx, nil); err != nil {
		result.Phase = tx.Phase()
		result.Message = err.Error()
		result.RecoveryFailed = tx.Phase() != "rolled_back"
		writeResult(installation, result)
		return result, err
	}
	result.Phase = tx.Phase()
	// Retention never runs before a successful apply, so a failed update keeps
	// every byte its rollback needs.
	_, _ = tx.Retain(2)
	return finish(installation, state, tx, session, options, result)
}

// finish records the outcome, releases both locks, and only then starts the
// launcher again: the new process takes the same installation lock at startup, so
// relaunching while this one still holds it would race into "updater busy".
func finish(installation, state string, tx *updates.Transaction, session *os.File, options Options, result Result) (Result, error) {
	direct, _ := tx.LaunchMode()
	result.StateDirectory = state
	writeResult(installation, result)
	if session != nil {
		_ = session.Close()
	}
	_ = tx.Close()
	result.Relaunched = relaunch(installation, state, options.NoRelaunch, direct)
	if result.Relaunched || options.NoRelaunch {
		// Record the relaunch attempt too, so the next start can report it.
		writeResult(installation, result)
	}
	return result, nil
}

func runRecovery(ctx context.Context, installation string, options Options, deadline time.Time, result Result) (Result, error) {
	phase, exists, err := updates.JournalPhase(installation)
	if err != nil {
		result.Message = err.Error()
		result.RecoveryFailed = true
		writeResult(installation, result)
		return result, err
	}
	if !exists {
		result.Message = "no interrupted update needs recovery"
		writeResult(installation, result)
		return result, nil
	}
	if phase == "rolled_back" {
		// The previous version is already restored; nothing to do.
		result.Message = "the previous version is already restored"
		result.Recovered = true
		writeResult(installation, result)
		return result, nil
	}
	if options.Action == ActionRecover && phase == "applied" {
		// A completed update is not an interrupted one; rolling it back is an
		// explicit action, not startup recovery.
		result.Message = "no interrupted update needs recovery"
		writeResult(installation, result)
		return result, nil
	}
	if options.Action == ActionRecover && !options.ConfirmRestore {
		if previous, ok, previousErr := ReadResult(installation); previousErr == nil && ok && previous.RecoveryFailed {
			result.Message = "the previous recovery attempt failed; choose restore manually"
			result.RecoveryFailed = true
			writeResult(installation, result)
			return result, errors.New(result.Message)
		}
	}
	tx, err := openPending(ctx, installation, deadline)
	if err != nil {
		result.Message = err.Error()
		result.RecoveryFailed = true
		writeResult(installation, result)
		return result, err
	}
	defer tx.Close()
	state, stateErr := tx.SessionDirectory()
	if stateErr != nil {
		result.Message = stateErr.Error()
		result.RecoveryFailed = true
		writeResult(installation, result)
		return result, stateErr
	}
	result.StateDirectory = state
	session, err := lockSession(ctx, state, deadline)
	if err != nil {
		// Nothing was touched: a busy session must not be recorded as a failed
		// recovery that blocks the next attempt.
		result.Message = err.Error()
		writeResult(installation, result)
		return result, err
	}
	defer session.Close()
	if err = tx.Rollback(ctx, nil); err != nil {
		result.Phase = tx.Phase()
		result.Message = err.Error()
		result.RecoveryFailed = true
		writeResult(installation, result)
		return result, err
	}
	result.Phase = tx.Phase()
	result.Recovered = true
	_, _ = tx.Retain(2)
	return finish(installation, state, tx, session, options, result)
}

func openPending(ctx context.Context, installation string, deadline time.Time) (*updates.Transaction, error) {
	for {
		tx, err := updates.OpenTransaction(installation)
		if err == nil {
			return tx, nil
		}
		if !errors.Is(err, updates.ErrUpdaterBusy) || time.Now().After(deadline) {
			return nil, err
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(200 * time.Millisecond):
		}
	}
}

func lockSession(ctx context.Context, state string, deadline time.Time) (*os.File, error) {
	for {
		lock, err := updates.LockSession(state)
		if err == nil {
			return lock, nil
		}
		if !errors.Is(err, updates.ErrSessionBusy) || time.Now().After(deadline) {
			return nil, err
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(200 * time.Millisecond):
		}
	}
}

// relaunchCommand builds the restart invocation for the entry point that started
// the update, with the recorded player state and nothing else.
func relaunchCommand(installation, state string, direct bool) *exec.Cmd {
	name := "The Order 1886.exe"
	if direct {
		name = "Play The Order 1886.exe"
	}
	command := exec.Command(filepath.Join(installation, name), "--state-dir", state)
	command.Dir = installation
	return command
}

// relaunch starts the launcher again. Callers pass the recorded relaunch mode and
// must already have released both locks: the new process takes the installation
// lock as it starts.
func relaunch(installation, state string, skip bool, direct bool) bool {
	if skip {
		return false
	}
	command := relaunchCommand(installation, state, direct)
	configureHelperProcess(command)
	return command.Start() == nil
}

// ReadResult returns the last recorded helper outcome.
func ReadResult(installation string) (Result, bool, error) {
	file, err := os.Open(filepath.Join(installation, filepath.FromSlash(workspace), resultName))
	if os.IsNotExist(err) {
		return Result{}, false, nil
	}
	if err != nil {
		return Result{}, false, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return Result{}, false, err
	}
	if !info.Mode().IsRegular() || info.Size() > maxResultSize {
		return Result{}, false, errors.New("invalid update result file")
	}
	body, err := io.ReadAll(io.LimitReader(file, maxResultSize+1))
	if err != nil {
		return Result{}, false, err
	}
	if len(body) > maxResultSize {
		return Result{}, false, errors.New("update result file is too large")
	}
	var result Result
	if err = json.Unmarshal(body, &result); err != nil {
		return Result{}, false, err
	}
	return result, true, nil
}

func writeResult(installation string, result Result) {
	body, err := json.Marshal(result)
	if err != nil {
		return
	}
	directory := filepath.Join(installation, filepath.FromSlash(workspace))
	if err = os.MkdirAll(directory, 0o700); err != nil {
		return
	}
	name := filepath.Join(directory, resultName+".tmp")
	if err = os.WriteFile(name, body, 0o600); err != nil {
		return
	}
	_ = os.Rename(name, filepath.Join(directory, resultName))
}
