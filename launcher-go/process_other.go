//go:build !windows

package main

import "os/exec"

func configureWorkerProcess(command *exec.Cmd) {}
