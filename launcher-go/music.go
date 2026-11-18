package main

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

// Launcher background music. The track is not embedded: the launcher plays the first audio
// file (by name) in <installation>/music, so players choose their own and the package ships
// none. Volume and mute are saved in the state folder beside the other launcher settings.

const (
	defaultMusicVolume = 20
	musicRoute         = "/music/theme"
)

var musicTypes = map[string]string{
	".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
	".flac": "audio/flac", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac",
}

type MusicState struct {
	Available bool   `json:"available"`
	Track     string `json:"track"`
	Volume    int    `json:"volume"`
	Muted     bool   `json:"muted"`
}

type musicPrefs struct {
	Volume int  `json:"volume"`
	Muted  bool `json:"muted"`
}

var musicMu sync.Mutex

// musicTrack returns the file the launcher plays, or "" when the music folder has none.
func musicTrack(root string) string {
	dir := filepath.Join(root, "music")
	entries, err := os.ReadDir(dir)
	if err != nil {
		return ""
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		if _, ok := musicTypes[strings.ToLower(filepath.Ext(entry.Name()))]; ok && entry.Type().IsRegular() {
			names = append(names, entry.Name())
		}
	}
	if len(names) == 0 {
		return ""
	}
	sort.Strings(names)
	return filepath.Join(dir, names[0])
}

func clampVolume(volume int) int {
	return min(max(volume, 0), 100)
}

func (app *App) musicPrefsPath() string { return filepath.Join(app.state, "launcher-music.json") }

func (app *App) loadMusicPrefs() musicPrefs {
	prefs := musicPrefs{Volume: defaultMusicVolume}
	if data, err := os.ReadFile(app.musicPrefsPath()); err == nil {
		_ = json.Unmarshal(data, &prefs)
	}
	prefs.Volume = clampVolume(prefs.Volume)
	return prefs
}

func (app *App) saveMusicPrefs(prefs musicPrefs) error {
	if err := os.MkdirAll(app.state, 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(prefs, "", "  ")
	if err != nil {
		return err
	}
	// Write then rename so a crash never leaves a half-written file.
	temp := app.musicPrefsPath() + ".tmp"
	if err := os.WriteFile(temp, append(data, '\n'), 0o644); err != nil {
		return err
	}
	return os.Rename(temp, app.musicPrefsPath())
}

// MusicState reports whether a track is available and the saved volume (0-100) and mute.
func (app *App) MusicState() MusicState {
	musicMu.Lock()
	defer musicMu.Unlock()
	prefs := app.loadMusicPrefs()
	state := MusicState{Volume: prefs.Volume, Muted: prefs.Muted}
	if track := musicTrack(app.root); track != "" {
		state.Available = true
		state.Track = strings.TrimSuffix(filepath.Base(track), filepath.Ext(track))
	}
	return state
}

func (app *App) SetMusicVolume(volume int) error {
	musicMu.Lock()
	defer musicMu.Unlock()
	prefs := app.loadMusicPrefs()
	prefs.Volume = clampVolume(volume)
	return app.saveMusicPrefs(prefs)
}

func (app *App) SetMusicMuted(muted bool) error {
	musicMu.Lock()
	defer musicMu.Unlock()
	prefs := app.loadMusicPrefs()
	prefs.Muted = muted
	return app.saveMusicPrefs(prefs)
}

// musicHandler serves the track to the launcher window at musicRoute. The asset server only
// reaches it for paths the embedded frontend does not have.
type musicHandler struct{ app *App }

func (handler musicHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != musicRoute {
		http.NotFound(w, r)
		return
	}
	track := musicTrack(handler.app.root)
	if track == "" {
		http.NotFound(w, r)
		return
	}
	file, err := os.Open(track)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", musicTypes[strings.ToLower(filepath.Ext(track))])
	w.Header().Set("Cache-Control", "no-store")
	http.ServeContent(w, r, info.Name(), info.ModTime(), file)
}
