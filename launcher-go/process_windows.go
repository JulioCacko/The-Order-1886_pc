package main

import (
	"os/exec"
	"syscall"
)

func configureWorkerProcess(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
}

func folderOpenCommand(path string) *exec.Cmd {
	return exec.Command("explorer.exe", path)
}
