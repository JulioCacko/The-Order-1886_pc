package updates

import "errors"

// ErrUpdaterBusy reports that another updater holds the installation lock.
var ErrUpdaterBusy = errors.New("another updater is active")

// ErrSessionBusy reports that the game or another launcher holds the player
// session lock, so the update must not touch the installation yet.
var ErrSessionBusy = errors.New("The Order is already running or being prepared")
