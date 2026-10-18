package main

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
	desktop "github.com/wailsapp/wails/v2/pkg/runtime"
)

//go:embed all:frontend/dist
var assets embed.FS

type App struct {
	directDone   chan int
	ctx          context.Context
	worker       *workerClient
	root         string
	state        string
	python       string
	mu           sync.Mutex
	busy         bool
	closing      bool
	startupError string
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
	workerPath := filepath.Join(app.root, "bin", "order1886-worker.exe")
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
	if app.worker == nil {
		if err := app.connect(); err != nil {
			app.startupError = err.Error()
		}
	}
}

func (app *App) Call(method string, params json.RawMessage) (string, error) {
	if app.worker == nil {
		return "", errors.New(app.startupError)
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

func (app *App) StartupError() string { return app.startupError }

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
	paths := map[string]string{"installation": app.root, "state": app.state, "logs": filepath.Join(app.state, "logs")}
	path, ok := paths[kind]
	if !ok {
		return errors.New("unknown installation location")
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
	probe := flag.Bool("worker-smoke", false, "Check the bundled worker without starting the game")
	flag.Parse()
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
	app := &App{root: root, state: stateDir, python: *python}
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
		app.directDone = make(chan int, 1)
		if err = app.connect(); err == nil {
			_, err = app.Call("session.start", json.RawMessage("{\"mode\":\"play\"}"))
			if err == nil {
				select {
				case code := <-app.directDone:
					app.worker.Close()
					<-app.worker.done
					os.Exit(code)
				case <-app.worker.done:
					os.Exit(1)
				}
			}
		}
		app.startupError = "Direct play needs setup: " + err.Error()
	}
	frontend, err := fs.Sub(assets, "frontend/dist")
	if err != nil {
		panic(err)
	}
	err = wails.Run(&options.App{
		Title: "The Order: 1886", Width: 1280, Height: 820, MinWidth: 940, MinHeight: 620,
		BackgroundColour: &options.RGBA{R: 12, G: 14, B: 15, A: 255},
		AssetServer:      &assetserver.Options{Assets: frontend},
		Bind:             []interface{}{app}, OnStartup: app.startup, OnBeforeClose: app.beforeClose,
		OnShutdown: func(context.Context) {
			if app.worker != nil {
				app.worker.Close()
			}
		},
		Windows: &windows.Options{Theme: windows.SystemDefault},
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
