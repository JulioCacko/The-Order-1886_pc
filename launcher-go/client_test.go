package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"testing"
	"time"
)

func TestProtocolHelper(t *testing.T) {
	if os.Getenv("ORDER_LAUNCHER_PROTOCOL_TEST") != "1" {
		return
	}
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		var request struct {
			ID     int64  `json:"id"`
			Method string `json:"method"`
		}
		_ = json.Unmarshal(scanner.Bytes(), &request)
		if request.Method == "exit" {
			os.Exit(7)
		}
		if request.Method == "fail" {
			fmt.Printf("{\"version\":1,\"id\":%d,\"error\":{\"message\":\"rejected\"}}\n", request.ID)
		} else {
			fmt.Println("{\"version\":1,\"event\":\"line\",\"data\":\"hello\"}")
			fmt.Printf("{\"version\":1,\"id\":%d,\"result\":{\"ok\":true}}\n", request.ID)
		}
	}
	os.Exit(0)
}

func helperClient(t *testing.T) *workerClient {
	t.Helper()
	command := exec.Command(os.Args[0], "-test.run=TestProtocolHelper")
	command.Env = append(os.Environ(), "ORDER_LAUNCHER_PROTOCOL_TEST=1")
	client, err := startWorker(command, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { client.Close() })
	return client
}

func TestWorkerResponseAndRejection(t *testing.T) {
	client := helperClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	got, err := client.Request(ctx, "state.get", map[string]any{})
	if err != nil || string(got) != "{\"ok\":true}" {
		t.Fatalf("%s %v", got, err)
	}
	if _, err = client.Request(ctx, "fail", nil); err == nil || err.Error() != "rejected" {
		t.Fatalf("lost worker rejection: %v", err)
	}
}

func TestWorkerExitUnblocksRequests(t *testing.T) {
	client := helperClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if _, err := client.Request(ctx, "exit", nil); err == nil {
		t.Fatal("worker death was hidden")
	}
	if _, err := client.Request(ctx, "state.get", nil); err == nil {
		t.Fatal("dead worker accepted a request")
	}
}

func TestWorkerRejectsOversizeBeforeWriting(t *testing.T) {
	client := helperClient(t)
	_, err := client.Request(context.Background(), "state.get", string(make([]byte, 70000)))
	if err == nil {
		t.Fatal("oversized request accepted")
	}
}

func TestUnknownLocationCannotReachShell(t *testing.T) {
	app := &App{}
	if err := app.OpenLocation("../outside"); err == nil {
		t.Fatal("arbitrary location accepted")
	}
}
