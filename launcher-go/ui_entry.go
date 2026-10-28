//go:build noui

package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
)

// The Linux entry points are this WebKit-free build (#114). The launcher window is a separate
// binary that links WebKitGTK 4.1; on a system without it (SteamOS, for one) the dynamic linker
// refuses to start that binary, so this entry says what is missing and plays the saved settings.

var missingLibrary = regexp.MustCompile(`error while loading shared libraries: (\S+): cannot open shared object file`)

const setupHint = `Set the game folder once with: "Play The Order 1886" --game-dir /path/to/your/game ` +
	`(in Steam, add it to the launch options). See QUICKSTART.txt.`

func runUI(app *App) error {
	if app.startupError != "" {
		report(app, app.startupError+"\n\n"+setupHint)
	}
	missing, err := startUI(app)
	if err == nil {
		return nil
	}
	if missing == "" {
		return err
	}
	report(app, fmt.Sprintf("The launcher window needs WebKitGTK 4.1, which this system does not have "+
		"(%s is missing). Starting the game with its saved settings instead. To change settings, "+
		"install WebKitGTK 4.1; see QUICKSTART.txt.", missing))
	if app.direct || app.startupError != "" {
		os.Exit(1) // Direct play was already tried and reported.
	}
	code, playErr := app.playDirect("")
	if playErr != nil {
		report(app, "Direct play needs setup: "+playErr.Error()+"\n\n"+setupHint)
		os.Exit(1)
	}
	os.Exit(code)
	return nil
}

// startUI runs the launcher window and waits for it. It returns the shared library the dynamic
// linker could not find when that is why the window did not start, and "" otherwise.
func startUI(app *App) (string, error) {
	command := exec.Command(filepath.Join(app.root, filepath.FromSlash(pkgpath.UI())),
		"--project-root", app.root, "--state-dir", app.state)
	tail := &diagnosticTail{}
	command.Stdin, command.Stdout, command.Stderr = os.Stdin, os.Stdout, io.MultiWriter(os.Stderr, tail)
	err := command.Run()
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		if library := loaderMissing(tail.String()); library != "" {
			return library, err
		}
		os.Exit(exit.ExitCode()) // The window ran and ended on its own terms.
	}
	return "", err
}

func loaderMissing(stderr string) string {
	if match := missingLibrary.FindStringSubmatch(stderr); match != nil {
		return match[1]
	}
	return ""
}

// report reaches a player who may have no terminal (Steam Game Mode): stderr, a log in the
// state folder, and a desktop dialog or notification when the system has one.
func report(app *App, message string) {
	fmt.Fprintln(os.Stderr, message)
	logs := filepath.Join(app.state, "logs")
	if os.MkdirAll(logs, 0o755) == nil {
		if file, err := os.OpenFile(filepath.Join(logs, "launcher-entry.log"),
			os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644); err == nil {
			fmt.Fprintf(file, "%s %s\n", time.Now().Format(time.RFC3339), strings.ReplaceAll(message, "\n", " "))
			file.Close()
		}
	}
	// The dialog never holds up the game, and its text is shown literally (a path may hold & or <).
	var command *exec.Cmd
	if zenity, err := exec.LookPath("zenity"); err == nil {
		command = exec.Command(zenity, "--warning", "--no-wrap", "--no-markup", "--timeout=60",
			"--title=The Order: 1886", "--text="+message)
	} else if notify, err := exec.LookPath("notify-send"); err == nil {
		command = exec.Command(notify, "The Order: 1886", message)
	}
	if command != nil && command.Start() == nil {
		go func() { _ = command.Wait() }()
	}
}
