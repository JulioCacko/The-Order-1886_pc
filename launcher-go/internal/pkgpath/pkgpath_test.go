package pkgpath

import (
	"runtime"
	"testing"
)

func TestNamesMatchThePlatformLayout(t *testing.T) {
	windows := runtime.GOOS == "windows"
	cases := map[string]struct{ got, wantWindows, wantOther string }{
		"launcher": {Launcher(), "The Order 1886.exe", "The Order 1886"},
		"play":     {Play(), "Play The Order 1886.exe", "Play The Order 1886"},
		"worker":   {Worker(), "bin/order1886-worker.exe", "bin/order1886-worker/order1886-worker"},
		"runtime":  {Runtime(), "bin/order1886-runtime.exe", "bin/order1886-runtime"},
	}
	for name, c := range cases {
		want := c.wantOther
		if windows {
			want = c.wantWindows
		}
		if c.got != want {
			t.Fatalf("%s = %q, want %q", name, c.got, want)
		}
	}
}

func TestRequiredKeepsEveryEntryPoint(t *testing.T) {
	required := Required()
	if len(required) != 5 {
		t.Fatalf("Required() has %d entries, want 5", len(required))
	}
	for _, want := range []string{Launcher(), Play(), Worker(), Runtime(), Receipt()} {
		found := false
		for _, name := range required {
			if name == want {
				found = true
				break
			}
		}
		if !found {
			t.Fatalf("Required() is missing %q", want)
		}
	}
	if Worker() == "bin/order1886-worker.exe" && !windows() {
		t.Fatalf("a non-Windows build must not look for the .exe worker")
	}
}

func windows() bool {
	return runtime.GOOS == "windows"
}
