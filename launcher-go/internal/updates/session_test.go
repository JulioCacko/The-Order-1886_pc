package updates

import (
	"bufio"
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const pythonSession = `import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from order1886 import session_lock
try:
    with session_lock(Path(sys.argv[2])):
        print("LOCKED", flush=True)
        sys.stdin.read(1)
except RuntimeError:
    print("BUSY", flush=True)
    sys.exit(73)
`

func pythonLockCommand(t *testing.T, state string) *exec.Cmd {
	t.Helper()
	python, err := exec.LookPath("python")
	if err != nil {
		t.Fatal("Python worker runtime is required for lock interoperability tests:", err)
	}
	repo, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	t.Cleanup(cancel)
	return exec.CommandContext(ctx, python, "-c", pythonSession, repo, state)
}

func TestGoSessionLockExcludesGoAndReleases(t *testing.T) {
	state := filepath.Join(t.TempDir(), "Novo jogador 游戏", "order1886")
	lock, err := LockSession(state)
	if err != nil {
		t.Fatal(err)
	}
	if other, err := LockSession(state); err == nil {
		other.Close()
		lock.Close()
		t.Fatal("two sessions acquired the same lock")
	}
	if err = lock.Close(); err != nil {
		t.Fatal(err)
	}
	lock, err = LockSession(state)
	if err != nil {
		t.Fatal(err)
	}
	lock.Close()
}

func TestGoSessionLockBlocksActualPythonBackendLock(t *testing.T) {
	state := t.TempDir()
	lock, err := LockSession(state)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Close()
	command := pythonLockCommand(t, state)
	command.Stdin = strings.NewReader("")
	output, err := command.CombinedOutput()
	var exit *exec.ExitError
	if err == nil {
		t.Fatalf("Python acquired Go's session lock: %s", output)
	}
	if !strings.Contains(string(output), "BUSY") {
		t.Fatalf("Python failed outside session-lock refusal: %s %v", output, err)
	}
	if value, ok := err.(*exec.ExitError); ok {
		exit = value
	}
	if exit == nil || exit.ExitCode() != 73 {
		t.Fatalf("wrong backend refusal: %s %v", output, err)
	}
}

func TestActualPythonBackendLockBlocksGoUntilRelease(t *testing.T) {
	state := t.TempDir()
	command := pythonLockCommand(t, state)
	stdin, err := command.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	defer stdin.Close()
	stdout, err := command.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	var diagnostics bytes.Buffer
	command.Stderr = &diagnostics
	if err = command.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		stdin.Close()
		if command.ProcessState == nil {
			command.Process.Kill()
			command.Wait()
		}
	})
	scanner := bufio.NewScanner(stdout)
	if !scanner.Scan() || scanner.Text() != "LOCKED" {
		command.Wait()
		t.Fatalf("Python lock not ready: %s %s", scanner.Text(), diagnostics.String())
	}
	if lock, err := LockSession(state); err == nil {
		lock.Close()
		t.Fatal("Go ignored Python's active session lock")
	}
	stdin.Close()
	if err = command.Wait(); err != nil {
		t.Fatal(err)
	}
	lock, err := LockSession(state)
	if err != nil {
		t.Fatal(err)
	}
	lock.Close()
}

func TestSessionLockPreservesExistingBytes(t *testing.T) {
	state := t.TempDir()
	file := filepath.Join(state, "session.lock")
	before := []byte("0 existing marker")
	if err := os.WriteFile(file, before, 0600); err != nil {
		t.Fatal(err)
	}
	lock, err := LockSession(state)
	if err != nil {
		t.Fatal(err)
	}
	lock.Close()
	if after, _ := os.ReadFile(file); !bytes.Equal(after, before) {
		t.Fatal("lock acquisition changed existing state bytes")
	}
}
