package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	desktop "github.com/wailsapp/wails/v2/pkg/runtime"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updatehost"
	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updates"
)

// UpdateStatus is what the Home and System pages render.
type UpdateStatus struct {
	State           string `json:"state"`
	Version         string `json:"version"`
	Downloaded      int64  `json:"downloaded"`
	Total           int64  `json:"total"`
	Channel         string `json:"channel"`
	Automatic       bool   `json:"automatic"`
	Error           string `json:"error"`
	RecoveryPending bool   `json:"recovery_pending"`
	RecoveryBlocked bool   `json:"recovery_blocked"`
	// InstallAvailable gates the destructive actions. A package may only replace
	// itself when the helper exists in this build and no update is in flight.
	InstallAvailable bool   `json:"install_available"`
	InstallReason    string `json:"install_reason"`
}

// helperRun is the parsed helper invocation, before any window or worker exists.
type helperRun struct {
	action         string
	installation   string
	parentPID      int
	parentClock    time.Time
	noRelaunch     bool
	confirmRestore bool
}

func (run helperRun) options() updatehost.Options {
	return updatehost.Options{
		Installation:   run.installation,
		Action:         run.action,
		ParentPID:      run.parentPID,
		ParentClock:    run.parentClock,
		NoRelaunch:     run.noRelaunch,
		ConfirmRestore: run.confirmRestore,
		Timeout:        updatehost.DefaultTimeout,
	}
}

// runUpdateHelper performs one helper action and never starts a window or the
// Python worker: Windows cannot replace files the launcher has loaded.
func runUpdateHelper(run helperRun) int {
	result, err := updatehost.Run(context.Background(), run.options())
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	fmt.Printf("update %s finished: phase=%s recovered=%t relaunched=%t\n", result.Action, result.Phase, result.Recovered, result.Relaunched)
	return 0
}

// pendingRecovery reports whether an interrupted update must be recovered before
// the worker may load. It creates no files.
func pendingRecovery(installation string) (bool, bool, string) {
	pending, _, err := updates.PendingRecovery(installation)
	if err != nil {
		return true, true, "An update cannot be verified: " + err.Error()
	}
	if !pending {
		return false, false, ""
	}
	if result, ok, readErr := updatehost.ReadResult(installation); readErr == nil && ok && result.RecoveryFailed {
		return true, true, "The previous update could not be completed. Restore the previous version to continue. Logs: " +
			filepath.Join(installation, ".order1886-update", "last-result.json")
	}
	return true, false, ""
}

// startRecovery hands an interrupted update to a helper copy and returns; the
// launcher process must exit so its own file becomes replaceable.
func startRecovery(installation string) error {
	helper, err := updatehost.CopySelf(installation)
	if err != nil {
		return err
	}
	started, err := updatehost.ProcessStartTime(os.Getpid())
	if err != nil {
		return err
	}
	command := updatehost.Command(helper, updatehost.Options{
		Installation: installation,
		Action:       updatehost.ActionRecover,
		ParentPID:    os.Getpid(),
		ParentClock:  started,
		Timeout:      updatehost.DefaultTimeout,
	})
	if err = command.Start(); err != nil {
		return err
	}
	return command.Process.Release()
}

func (app *App) updateChannel() string {
	callCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	body, err := app.Request(callCtx, "state.get", json.RawMessage("{}"))
	if err != nil {
		return updates.ChannelPreview
	}
	var state struct {
		Settings map[string]any `json:"settings"`
	}
	if json.Unmarshal(body, &state) != nil {
		return updates.ChannelPreview
	}
	channel, _ := state.Settings["update_channel"].(string)
	if channel != updates.ChannelStable {
		return updates.ChannelPreview
	}
	return channel
}

func (app *App) automaticUpdates() bool {
	callCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	body, err := app.Request(callCtx, "state.get", json.RawMessage("{}"))
	if err != nil {
		return false
	}
	var state struct {
		Settings map[string]any `json:"settings"`
	}
	if json.Unmarshal(body, &state) != nil {
		return false
	}
	enabled, _ := state.Settings["automatic_updates"].(bool)
	return enabled
}

func (app *App) updateStatus() UpdateStatus {
	app.updateMu.Lock()
	defer app.updateMu.Unlock()
	status := app.update
	if status.State == "" {
		status.State = "idle"
	}
	status.Automatic = app.autoUpdates
	pending, blocked, _ := pendingRecovery(app.root)
	status.RecoveryPending = pending
	status.RecoveryBlocked = blocked
	status.Channel = app.updateCh
	if status.Channel == "" {
		status.Channel = updates.ChannelPreview
	}
	status.InstallAvailable = app.updateStage != "" && !blocked && !app.busy
	if !status.InstallAvailable {
		switch {
		case blocked:
			status.InstallReason = "Recover the interrupted update first."
		case app.busy:
			status.InstallReason = "Stop the running session before installing an update."
		default:
			status.InstallReason = "Download an update before installing it."
		}
	}
	return status
}

// UpdateState is the read-only surface the pages poll.
func (app *App) UpdateState() UpdateStatus { return app.updateStatus() }

// startupUpdateCheck honours automatic_updates as a background version check: it
// never downloads, never installs and never blocks the window.
func (app *App) startupUpdateCheck() {
	app.updateCh = app.updateChannel()
	app.autoUpdates = app.automaticUpdates()
	app.updateMu.Lock()
	app.update.Automatic = app.autoUpdates
	app.updateMu.Unlock()
	if !app.autoUpdates {
		return
	}
	go func() {
		status := app.UpdateCheck()
		app.mu.Lock()
		ctx := app.ctx
		app.mu.Unlock()
		if ctx != nil {
			desktop.EventsEmit(ctx, "update", status)
		}
	}()
}

// UpdateCheck looks for a newer release on the configured channel.
func (app *App) UpdateCheck() UpdateStatus {
	app.updateMu.Lock()
	app.setUpdateLocked("checking")
	app.updateMu.Unlock()
	channel := app.updateChannel()
	app.updateCh = channel
	callCtx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	release, err := updates.CheckReleaseOn(callCtx, channel)
	if err != nil {
		app.updateMu.Lock()
		app.update.State = "failed"
		app.update.Error = err.Error()
		app.updateMu.Unlock()
		return app.updateStatus()
	}
	app.updateMu.Lock()
	app.release = release
	app.update.Version = release.Tag
	app.update.Error = ""
	app.update.State = "available"
	app.updateMu.Unlock()
	return app.updateStatus()
}

// UpdateDownload fetches and verifies the release into a private stage.
func (app *App) UpdateDownload() UpdateStatus {
	app.updateMu.Lock()
	release := app.release
	app.updateMu.Unlock()
	if release.Tag == "" {
		app.updateMu.Lock()
		app.update.State = "failed"
		app.update.Error = "check for an update before downloading it"
		app.updateMu.Unlock()
		return app.updateStatus()
	}
	app.updateMu.Lock()
	app.update.State = "downloading"
	app.update.Total = release.Identity.Size
	app.update.Downloaded = 0
	app.update.Error = ""
	app.updateMu.Unlock()
	callCtx, cancel := context.WithCancel(context.Background())
	app.cancelUpdate = cancel
	defer cancel()
	directory := filepath.Join(app.state, "updates")
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return app.failUpdate(err)
	}
	archive := filepath.Join(directory, sanitizeTag(release.Tag)+".zip")
	_ = os.Remove(archive)
	if err := updates.DownloadRelease(callCtx, release, archive, func(done, total int64) {
		app.updateMu.Lock()
		app.update.Downloaded = done
		app.update.Total = total
		app.updateMu.Unlock()
	}); err != nil {
		_ = os.Remove(archive)
		return app.failUpdate(err)
	}
	stage := filepath.Join(directory, sanitizeTag(release.Tag)+"-"+strconv.FormatInt(time.Now().UnixNano(), 36))
	identity := release.Identity
	manifest, err := updates.StageArchive(callCtx, archive, stage, identity)
	if err != nil {
		_ = os.Remove(archive)
		return app.failUpdate(err)
	}
	identity.ManifestSHA256 = manifest.SHA256
	_ = os.Remove(archive)
	app.updateMu.Lock()
	app.updateStage = stage
	app.candidate = updatehost.Candidate{Stage: stage, Identity: identity}
	app.update.State = "staged"
	app.updateMu.Unlock()
	return app.updateStatus()
}

// UpdateCancel stops an in-flight download.
func (app *App) UpdateCancel() UpdateStatus {
	app.updateMu.Lock()
	cancel := app.cancelUpdate
	app.updateMu.Unlock()
	if cancel != nil {
		cancel()
	}
	return app.updateStatus()
}

// UpdateInstall prepares the replacement, starts the helper copy and closes the
// launcher. The helper waits for this process, holds the locks and relaunches.
func (app *App) UpdateInstall() error {
	app.updateMu.Lock()
	candidate := app.candidate
	app.updateMu.Unlock()
	if candidate.Stage == "" {
		return errors.New("download an update before installing it")
	}
	if _, err := app.Call("updates.preflight", json.RawMessage("{}")); err != nil {
		return err
	}
	if err := updatehost.Prepare(app.root, candidate, app.state, app.direct); err != nil {
		return err
	}
	helper, err := updatehost.CopySelf(app.root)
	if err != nil {
		return err
	}
	started, err := updatehost.ProcessStartTime(os.Getpid())
	if err != nil {
		return err
	}
	command := updatehost.Command(helper, updatehost.Options{
		Installation: app.root,
		Action:       updatehost.ActionApply,
		ParentPID:    os.Getpid(),
		ParentClock:  started,
		Timeout:      updatehost.DefaultTimeout,
	})
	if err = command.Start(); err != nil {
		return err
	}
	if err = command.Process.Release(); err != nil {
		return err
	}
	return app.closeForUpdate()
}

// UpdateRestore asks for an explicit recovery after an automatic one failed.
func (app *App) UpdateRestore() error {
	helper, err := updatehost.CopySelf(app.root)
	if err != nil {
		return err
	}
	started, err := updatehost.ProcessStartTime(os.Getpid())
	if err != nil {
		return err
	}
	command := updatehost.Command(helper, updatehost.Options{
		Installation:   app.root,
		Action:         updatehost.ActionRecover,
		ParentPID:      os.Getpid(),
		ParentClock:    started,
		ConfirmRestore: true,
		Timeout:        updatehost.DefaultTimeout,
	})
	if err = command.Start(); err != nil {
		return err
	}
	if err = command.Process.Release(); err != nil {
		return err
	}
	return app.closeForUpdate()
}

func (app *App) setUpdateLocked(state string) {
	app.update.State = state
	app.update.Error = ""
}

func (app *App) failUpdate(err error) UpdateStatus {
	app.updateMu.Lock()
	app.update.State = "failed"
	app.update.Error = err.Error()
	app.updateMu.Unlock()
	return app.updateStatus()
}

// closeForUpdate stops the worker and closes the window so the helper can replace
// this executable. It refuses while a session is busy.
func (app *App) closeForUpdate() error {
	app.mu.Lock()
	busy := app.busy
	app.closing = true
	app.mu.Unlock()
	if busy {
		app.mu.Lock()
		app.closing = false
		app.mu.Unlock()
		return errors.New("stop the running session before installing an update")
	}
	app.connectMu.Lock()
	worker := app.worker
	app.shutdownStarted = true
	app.connectMu.Unlock()
	if worker != nil {
		worker.Close()
		select {
		case <-worker.done:
		case <-time.After(15 * time.Second):
			return errors.New("the Order worker did not stop in time")
		}
	}
	if app.ctx != nil {
		quitApp(app.ctx)
	}
	return nil
}

func sanitizeTag(tag string) string {
	return strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '-' {
			return r
		}
		return '-'
	}, tag)
}
