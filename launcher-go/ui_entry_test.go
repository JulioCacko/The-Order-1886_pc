//go:build noui

package main

import "testing"

func TestLoaderMissingNamesTheLibrary(t *testing.T) {
	// What glibc's dynamic linker prints on SteamOS for the WebKitGTK-linked launcher window (#114).
	stderr := "/opt/o1886/bin/order1886-launcher: error while loading shared libraries: " +
		"libwebkit2gtk-4.1.so.0: cannot open shared object file: No such file or directory\n"
	if got := loaderMissing(stderr); got != "libwebkit2gtk-4.1.so.0" {
		t.Fatalf("loaderMissing = %q", got)
	}
	if got := loaderMissing("Gtk-WARNING: cannot open display\n"); got != "" {
		t.Fatalf("an ordinary failure was taken for a missing library: %q", got)
	}
}
