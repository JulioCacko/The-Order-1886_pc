package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	desktop "github.com/wailsapp/wails/v2/pkg/runtime"

	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/pkgpath"
	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updatehost"
	"github.com/JulioCacko/The-Order-1886_pc/launcher-go/internal/updates"
)

type App struct {
	directDone      chan int
	ctx             context.Context
	worker          *workerClient
	root            string
	state           string
	python          string
	mu              sync.Mutex
	busy            bool
	closing         bool
	startupError    string
	connectMu       sync.Mutex
	shutdownStarted bool
	direct          bool

	updateMu     sync.Mutex
	update       UpdateStatus
	release      updates.Release
	updateCh     string
	updateStage  string
	candidate    updatehost.Candidate
	cancelUpdate context.CancelFunc
	autoUpdates  bool
}

func (app *App) event(name string, data json.RawMessage) {
	app.mu.Lock()
	if name == "started" {
		app.busy = true
	}
	if name == "done" {
		app.busy = false
		if app.directDone != nil {
			var result []json.RawMessage
			code := 1
			if json.Unmarshal(data, &result) == nil && len(result) > 0 {
				_ = json.Unmarshal(result[0], &code)
			}
			select {
			case app.directDone <- code:
			default:
			}
		}
	}
	if name == "disconnected" {
		app.busy = false
		app.closing = false
	}
	closing := app.closing && !app.busy
	ctx := app.ctx
	app.mu.Unlock()
	if ctx != nil {
		desktop.EventsEmit(ctx, "worker", map[string]any{"event": name, "data": data})
		if closing {
			desktop.Quit(ctx)
		}
	}
}

func (app *App) connect() error {
	app.connectMu.Lock()
	defer app.connectMu.Unlock()
	if app.shutdownStarted {
		return errors.New("Launcher is closing.")
	}
	if pending, _, _ := pendingRecovery(app.root); pending {
		// Never load a worker beside unrecovered package files.
		return errors.New("An update is waiting to be recovered. Restart the launcher.")
	}
	if app.worker != nil {
		return nil
	}
	workerPath := filepath.Join(app.root, filepath.FromSlash(pkgpath.Worker()))
	var command *exec.Cmd
	if _, err := os.Stat(workerPath); err == nil {
		command = exec.Command(workerPath, "--state-dir", app.state, "--installation-root", app.root)
	} else {
		script := filepath.Join(app.root, "launcher", "order1886_worker.py")
		if _, err := os.Stat(script); err != nil {
			return errors.New("Order worker is missing. Repair the portable installation.")
		}
		command = exec.Command(app.python, script, "--state-dir", app.state, "--installation-root", app.root)
	}
	command.Dir = app.root
	configureWorkerProcess(command)
	client, err := startWorker(command, app.event)
	if err != nil {
		return fmt.Errorf("cannot start Order worker: %w", err)
	}
	app.worker = client
	return nil
}

func (app *App) startup(ctx context.Context) {
	app.mu.Lock()
	app.ctx = ctx
	app.mu.Unlock()
	// Frontend calls report the current connection error and can retry after repair.
	if app.connect() == nil {
		app.startupUpdateCheck()
	}
}

func (app *App) Call(method string, params json.RawMessage) (string, error) {
	if err := app.connect(); err != nil {
		return "", err
	}
	if len(params) == 0 || string(params) == "null" {
		params = json.RawMessage("{}")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	if method == "session.start" {
		app.mu.Lock()
		if app.busy {
			app.mu.Unlock()
			return "", errors.New("A session is already starting or running.")
		}
		app.busy = true
		app.mu.Unlock()
	}
	result, err := app.worker.Request(ctx, method, params)
	if err != nil {
		if method == "session.start" {
			app.mu.Lock()
			app.busy = false
			app.mu.Unlock()
		}
		return "", err
	}
	return string(result), nil
}

// Request runs one worker call without the session bookkeeping Call performs.
func (app *App) Request(ctx context.Context, method string, params json.RawMessage) (json.RawMessage, error) {
	if err := app.connect(); err != nil {
		return nil, err
	}
	if len(params) == 0 || string(params) == "null" {
		params = json.RawMessage("{}")
	}
	return app.worker.Request(ctx, method, params)
}

func (app *App) StartupError() string {
	if err := app.connect(); err != nil {
		app.connectMu.Lock()
		blocked := app.startupError
		app.connectMu.Unlock()
		if blocked != "" {
			return blocked
		}
		return err.Error()
	}
	app.connectMu.Lock()
	defer app.connectMu.Unlock()
	return app.startupError
}

func quitApp(ctx context.Context) { desktop.Quit(ctx) }

func (app *App) shutdown(context.Context) {
	app.connectMu.Lock()
	app.shutdownStarted = true
	worker := app.worker
	app.connectMu.Unlock()
	if worker != nil {
		worker.Close()
	}
}

func (app *App) Browse(kind string) (string, error) {
	if kind == "directory" {
		return desktop.OpenDirectoryDialog(app.ctx, desktop.OpenDialogOptions{Title: "Select folder"})
	}
	if kind == "file" {
		return desktop.OpenFileDialog(app.ctx, desktop.OpenDialogOptions{Title: "Select Order runtime", Filters: []desktop.FileFilter{{DisplayName: "Executable", Pattern: "*.exe"}}})
	}
	return "", errors.New("unsupported chooser")
}

func (app *App) OpenLink(name string) error {
	links := map[string]string{
		"releases": "https://github.com/JulioCacko/The-Order-1886_pc/releases",
		"issues":   "https://github.com/JulioCacko/The-Order-1886_pc/issues",
	}
	url, ok := links[name]
	if !ok {
		return errors.New("unknown support link")
	}
	desktop.BrowserOpenURL(app.ctx, url)
	return nil
}

func (app *App) OpenLocation(kind string) error {
	paths := map[string]string{"installation": app.root, "state": app.state, "logs": filepath.Join(app.state, "logs"),
		"saves": filepath.Join(app.state, "savedata")}
	path, ok := paths[kind]
	if !ok {
		return errors.New("unknown installation location")
	}
	if kind == "saves" {
		// Players copy saves in here before the game has made any.
		if err := os.MkdirAll(path, 0o755); err != nil {
			return err
		}
	}
	if _, err := os.Stat(path); err != nil {
		return fmt.Errorf("location is not available yet: %w", err)
	}
	slash := filepath.ToSlash(path)
	if !strings.HasPrefix(slash, "/") {
		slash = "/" + slash
	}
	desktop.BrowserOpenURL(app.ctx, (&url.URL{Scheme: "file", Path: slash}).String())
	return nil
}

func (app *App) beforeClose(ctx context.Context) bool {
	app.mu.Lock()
	busy := app.busy
	app.mu.Unlock()
	if busy {
		desktop.EventsEmit(ctx, "close-requested")
		return true
	}
	return false
}

func (app *App) ConfirmClose() error {
	app.mu.Lock()
	app.closing = true
	busy := app.busy
	app.mu.Unlock()
	if !busy {
		desktop.Quit(app.ctx)
		return nil
	}
	_, err := app.Call("session.stop", json.RawMessage("{}"))
	if err != nil {
		app.mu.Lock()
		app.closing = false
		app.mu.Unlock()
	}
	return err
}

func main() {
	executable, err := os.Executable()
	if err != nil {
		panic(err)
	}
	project := flag.String("project-root", filepath.Dir(executable), "Source or portable installation directory")
	state := flag.String("state-dir", "", "Portable title state directory")
	python := flag.String("python", "python", "Python executable for source development only")
	direct := flag.Bool("direct-play", strings.HasPrefix(strings.ToLower(filepath.Base(executable)), "play "), "Launch saved configuration")
	gameDir := flag.String("game-dir", "", "Direct play: validate and save this game folder first")
	probe := flag.Bool("worker-smoke", false, "Check the bundled worker without starting the game")
	helper := flag.Bool("update-helper", false, "Internal: run one packaged update action")
	action := flag.String("update-action", "", "Internal: apply, recover or rollback")
	installed := flag.String("update-installation", "", "Internal: installation to update")
	parentPID := flag.Int("update-parent-pid", 0, "Internal: launcher process that must exit first")
	parentClock := flag.String("update-parent-clock", "", "Internal: launcher start time")
	noRelaunch := flag.Bool("no-relaunch", false, "Internal: do not start the launcher again")
	confirmRestore := flag.Bool("confirm-restore", false, "Internal: user requested a restore after a failed recovery")
	flag.Parse()
	if *helper {
		run := helperRun{action: *action, installation: *installed, parentPID: *parentPID, noRelaunch: *noRelaunch, confirmRestore: *confirmRestore}
		if run.installation == "" {
			run.installation = filepath.Dir(executable)
		}
		if *parentClock != "" {
			if run.parentClock, err = time.Parse(time.RFC3339Nano, *parentClock); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
		}
		os.Exit(runUpdateHelper(run))
	}
	root, err := filepath.Abs(*project)
	if err != nil {
		panic(err)
	}
	stateDir := *state
	if stateDir == "" {
		stateDir = filepath.Join(root, "user", "order1886")
	}
	stateDir, err = filepath.Abs(stateDir)
	if err != nil {
		panic(err)
	}
	// Recovery runs before Wails and before any Python worker: a mixed package must
	// never load. The helper performs it, because this executable may be the file
	// that has to be replaced.
	pending, blocked, blockedReason := pendingRecovery(root)
	if pending && !blocked {
		if err = startRecovery(root); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	app := &App{root: root, state: stateDir, python: *python, direct: *direct}
	if blocked {
		app.startupError = blockedReason
	}
	if *probe {
		if err = app.connect(); err == nil {
			_, err = app.Call("state.get", json.RawMessage("{}"))
			app.worker.Close()
		}
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Println("Go launcher worker smoke passed")
		return
	}
	if *direct {
		code, playErr := app.playDirect(*gameDir)
		if playErr == nil {
			os.Exit(code)
		}
		app.startupError = "Direct play needs setup: " + playErr.Error()
	}
	if err = runUI(app); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

// playDirect starts the saved configuration and waits for the game to end. A game folder given
// on the command line (a Steam launch option, for one) is saved first, so a machine without the
// launcher window can still be set up once; a folder the session then refuses is not kept.
func (app *App) playDirect(gameDir string) (int, error) {
	app.directDone = make(chan int, 1)
	if err := app.connect(); err != nil {
		return 1, err
	}
	previous := ""
	if gameDir != "" {
		folder, err := filepath.Abs(gameDir)
		if err != nil {
			return 1, err
		}
		if previous, err = app.savedGameDir(); err != nil {
			return 1, err
		}
		if err = app.setGameDir(folder); err != nil {
			return 1, fmt.Errorf("cannot use --game-dir %s: %w", folder, err)
		}
	}
	if _, err := app.Call("session.start", json.RawMessage("{\"mode\":\"play\"}")); err != nil {
		if gameDir != "" {
			_ = app.setGameDir(previous)
		}
		return 1, err
	}
	select {
	case code := <-app.directDone:
		app.worker.Close()
		<-app.worker.done
		return code, nil
	case <-app.worker.done:
		return 1, nil
	}
}

func (app *App) savedGameDir() (string, error) {
	state, err := app.Call("state.get", json.RawMessage("{}"))
	if err != nil {
		return "", err
	}
	var snapshot struct {
		Settings struct {
			GameDir string `json:"game_dir"`
		} `json:"settings"`
	}
	if err = json.Unmarshal([]byte(state), &snapshot); err != nil {
		return "", fmt.Errorf("cannot read the saved game folder: %w", err)
	}
	return snapshot.Settings.GameDir, nil
}

func (app *App) setGameDir(folder string) error {
	params, _ := json.Marshal(map[string]any{"values": map[string]string{"game_dir": folder}})
	_, err := app.Call("settings.set", params)
	return err
}
