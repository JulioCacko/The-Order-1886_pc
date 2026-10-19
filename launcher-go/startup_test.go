package main

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"
)

type shutdownInput struct{ closed chan struct{} }

func (input *shutdownInput) Write(data []byte) (int, error) { return len(data), nil }
func (input *shutdownInput) Close() error                   { close(input.closed); return nil }

func TestShutdownClosesWorkerStartedDuringInitialization(t *testing.T) {
	app := &App{}
	app.connectMu.Lock()
	done := make(chan struct{})
	go func() { app.shutdown(context.Background()); close(done) }()
	select {
	case <-done:
		t.Error("shutdown skipped pending worker initialization")
	case <-time.After(50 * time.Millisecond):
	}
	input := &shutdownInput{closed: make(chan struct{})}
	app.worker = &workerClient{input: input}
	app.connectMu.Unlock()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("shutdown did not finish")
	}
	select {
	case <-input.closed:
	default:
		t.Fatal("worker input remained open after shutdown")
	}
}

func TestShutdownPreventsLateWorkerCreation(t *testing.T) {
	app := &App{}
	app.shutdown(context.Background())
	if err := app.connect(); err == nil || err.Error() != "Launcher is closing." {
		t.Fatalf("late connection was not refused: %v", err)
	}
}

func TestRecoveredConnectionDoesNotKeepObsoleteStartupError(t *testing.T) {
	app := &App{root: t.TempDir()}
	app.startup(context.Background()) // The worker is initially missing.
	app.connectMu.Lock()
	app.worker = &workerClient{} // A later connection has completed successfully.
	app.connectMu.Unlock()
	if message := app.StartupError(); message != "" {
		t.Fatalf("recovered connection retained an error: %s", message)
	}
	app.connectMu.Lock()
	app.startupError = "Direct play needs setup: select the game folder"
	app.connectMu.Unlock()
	if message := app.StartupError(); message != "Direct play needs setup: select the game folder" {
		t.Fatalf("intentional direct-play notice was lost: %s", message)
	}
}

func TestFrontendWaitsForWorkerConnection(t *testing.T) {
	for _, operation := range []string{"startup status", "state request"} {
		t.Run(operation, func(t *testing.T) {
			app := &App{startupError: "not connected yet"}
			app.connectMu.Lock()
			done := make(chan string, 1)
			started := make(chan struct{})
			go func() {
				close(started)
				if operation == "startup status" {
					done <- app.StartupError()
				} else {
					_, err := app.Call("state.get", json.RawMessage("{}"))
					if err == nil {
						done <- "missing error"
					} else {
						done <- err.Error()
					}
				}
			}()
			<-started
			premature := false
			select {
			case result := <-done:
				t.Errorf("frontend returned before connection completed: %s", result)
				premature = true
			case <-time.After(50 * time.Millisecond):
			}
			app.worker = &workerClient{failure: errors.New("connected worker")}
			app.startupError = "connected status"
			app.connectMu.Unlock()
			if premature {
				return
			}
			want := "connected status"
			if operation == "state request" {
				want = "connected worker"
			}
			select {
			case result := <-done:
				if result != want {
					t.Fatalf("got %q, want %q", result, want)
				}
			case <-time.After(time.Second):
				t.Fatal("frontend did not resume after connection")
			}
		})
	}
}
