//go:build !windows

package main

import "os/exec"

func configureWorkerProcess(command *exec.Cmd) {}

func folderOpenCommand(path string) *exec.Cmd {
	return exec.Command("xdg-open", path)
}
