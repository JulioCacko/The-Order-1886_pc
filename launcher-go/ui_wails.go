//go:build !noui

package main

import (
	"embed"
	"io/fs"
	"path/filepath"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
)

//go:embed all:frontend/dist
var assets embed.FS

// runUI opens the launcher window. Only this file links the platform webview (WebView2 on
// Windows, WebKitGTK on Linux); the noui build replaces it with ui_entry.go.
func runUI(app *App) error {
	frontend, err := fs.Sub(assets, "frontend/dist")
	if err != nil {
		return err
	}
	return wails.Run(&options.App{
		Title: "The Order: 1886", Width: 1280, Height: 820, MinWidth: 940, MinHeight: 620,
		BackgroundColour: &options.RGBA{R: 12, G: 14, B: 15, A: 255},
		AssetServer:      &assetserver.Options{Assets: frontend},
		Bind:             []interface{}{app}, OnStartup: app.startup, OnBeforeClose: app.beforeClose,
		OnShutdown: app.shutdown,
		// Separate portable installations must not reuse a live WebView profile.
		Windows: &windows.Options{Theme: windows.SystemDefault,
			WebviewUserDataPath: filepath.Join(app.state, "webview")},
	})
}
