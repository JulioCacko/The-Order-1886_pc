//go:build !windows

package updatehost

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"syscall"
	"time"
)

func executableSuffix() string { return "" }

func configureHelperProcess(*exec.Cmd) {}

// ProcessStartTime is unavailable without process creation times; the zero time
// makes the helper compare nothing.
func ProcessStartTime(int) (time.Time, error) { return time.Time{}, nil }

// waitForExit polls until the initiating process is gone. Creation times are not
// compared here because the portable updater only ships on Windows.
func waitForExit(ctx context.Context, pid int, _ time.Time, deadline time.Time) error {
	for {
		process, err := os.FindProcess(pid)
		if err != nil {
			return nil
		}
		if err = process.Signal(syscall.Signal(0)); err != nil {
			return nil
		}
		if time.Now().After(deadline) {
			return errors.New("the launcher did not exit before the update timeout")
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(200 * time.Millisecond):
		}
	}
}
