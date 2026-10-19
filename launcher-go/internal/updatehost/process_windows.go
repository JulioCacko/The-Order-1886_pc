//go:build windows

package updatehost

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
)

func executableSuffix() string { return ".exe" }

// configureHelperProcess keeps the helper and the relaunched launcher hidden and
// outside the console session of whatever started them.
func configureHelperProcess(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
}

// ProcessStartTime reports when a process started, so a helper can tell the
// launcher it must wait for from an unrelated process that reuses the id.
func ProcessStartTime(pid int) (time.Time, error) {
	handle, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return time.Time{}, err
	}
	defer windows.CloseHandle(handle)
	var creation, exit, kernel, user windows.Filetime
	if err = windows.GetProcessTimes(handle, &creation, &exit, &kernel, &user); err != nil {
		return time.Time{}, err
	}
	return time.Unix(0, creation.Nanoseconds()).UTC(), nil
}

// waitForExit waits until the process that started the update has exited. The
// creation time is compared as well, so a recycled process id is never mistaken
// for the launcher that is still running.
func waitForExit(ctx context.Context, pid int, created time.Time, deadline time.Time) error {
	handle, err := windows.OpenProcess(windows.SYNCHRONIZE|windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		if errors.Is(err, windows.ERROR_INVALID_PARAMETER) {
			// The launcher already exited.
			return nil
		}
		return fmt.Errorf("cannot watch the launcher process: %w", err)
	}
	defer windows.CloseHandle(handle)
	if !created.IsZero() {
		var creation, exit, kernel, user windows.Filetime
		if err = windows.GetProcessTimes(handle, &creation, &exit, &kernel, &user); err != nil {
			return fmt.Errorf("cannot read the launcher start time: %w", err)
		}
		actual := time.Unix(0, creation.Nanoseconds())
		if actual.Sub(created) > time.Second || created.Sub(actual) > time.Second {
			// The id now belongs to another process, not the launcher.
			return nil
		}
	}
	for {
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return errors.New("the launcher did not exit before the update timeout")
		}
		poll := remaining
		if poll > 200*time.Millisecond {
			poll = 200 * time.Millisecond
		}
		status, waitErr := windows.WaitForSingleObject(handle, uint32(poll/time.Millisecond))
		if waitErr != nil {
			return fmt.Errorf("waiting for the launcher failed: %w", waitErr)
		}
		if status == uint32(windows.WAIT_OBJECT_0) {
			return nil
		}
		if status != uint32(windows.WAIT_TIMEOUT) {
			return fmt.Errorf("unexpected wait status %#x", status)
		}
		if err = ctx.Err(); err != nil {
			return err
		}
	}
}
