// Package pkgpath names the files of a portable installation that differ by platform.
//
// The Windows package has always shipped `The Order 1886.exe` and `bin/order1886-worker.exe`. The
// Linux package ships the same launcher without the extension and the PyInstaller one-directory
// worker under `bin/order1886-worker/`, so every place that looked for the Windows spelling has to
// ask this package instead of hard-coding it.
package pkgpath

import "runtime"

// Launcher is the primary entry point of a portable installation.
func Launcher() string {
	if runtime.GOOS == "windows" {
		return "The Order 1886.exe"
	}
	return "The Order 1886"
}

// Play is the entry point a desktop shortcut or Steam entry starts.
func Play() string {
	if runtime.GOOS == "windows" {
		return "Play The Order 1886.exe"
	}
	return "Play The Order 1886"
}

// Worker is the frozen Python worker the launcher drives over stdio. PyInstaller's one-directory
// mode nests the binary inside a folder named after it, which is the layout the Linux packager ships.
func Worker() string {
	if runtime.GOOS == "windows" {
		return "bin/order1886-worker.exe"
	}
	return "bin/order1886-worker/order1886-worker"
}

// Runtime is the native runtime executable.
func Runtime() string {
	if runtime.GOOS == "windows" {
		return "bin/order1886-runtime.exe"
	}
	return "bin/order1886-runtime"
}

// Receipt is the runtime build identity the launcher verifies before playing.
func Receipt() string {
	return "bin/runtime-build.json"
}

// Required lists the files an installation must contain to be updatable and playable.
func Required() []string {
	return []string{Launcher(), Play(), Worker(), Runtime(), Receipt()}
}
