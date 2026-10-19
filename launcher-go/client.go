package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"sync"
	"sync/atomic"
)

type response struct {
	Version int             `json:"version"`
	ID      int64           `json:"id"`
	Event   string          `json:"event"`
	Data    json.RawMessage `json:"data"`
	Result  json.RawMessage `json:"result"`
	Error   *struct {
		Message string `json:"message"`
	} `json:"error"`
}

type workerClient struct {
	cmd           *exec.Cmd
	input         io.WriteCloser
	writeMu       sync.Mutex
	mu            sync.Mutex
	pending       map[int64]chan response
	nextID        atomic.Int64
	done          chan struct{}
	failure       error
	event         func(string, json.RawMessage)
	closeOnce     sync.Once
	expectedClose atomic.Bool
}

func startWorker(command *exec.Cmd, event func(string, json.RawMessage)) (*workerClient, error) {
	input, err := command.StdinPipe()
	if err != nil {
		return nil, err
	}
	output, err := command.StdoutPipe()
	if err != nil {
		input.Close()
		return nil, err
	}
	// Diagnostics never share the protocol pipe; keep only a bounded tail.
	diagnostics := &diagnosticTail{}
	command.Stderr = diagnostics
	if err = command.Start(); err != nil {
		input.Close()
		return nil, err
	}
	client := &workerClient{cmd: command, input: input, pending: make(map[int64]chan response), done: make(chan struct{}), event: event}
	go func() {
		scanner := bufio.NewScanner(output)
		scanner.Buffer(make([]byte, 4096), 2*1024*1024)
		var protocolError error
		for scanner.Scan() {
			var item response
			if err := json.Unmarshal(scanner.Bytes(), &item); err != nil || item.Version != 1 {
				protocolError = errors.New("worker returned an invalid protocol response")
				input.Close()
				break
			}
			if item.Event != "" {
				if client.event != nil {
					client.event(item.Event, item.Data)
				}
				continue
			}
			client.mu.Lock()
			channel := client.pending[item.ID]
			delete(client.pending, item.ID)
			client.mu.Unlock()
			if channel != nil {
				channel <- item
			}
		}
		if scanner.Err() != nil {
			protocolError = scanner.Err()
		}
		// Drain before Wait: Wait closes the command's stdout pipe.
		waitError := command.Wait()
		if protocolError != nil {
			waitError = protocolError
		}
		if waitError == nil {
			waitError = errors.New("worker closed")
		}
		if detail := diagnostics.String(); detail != "" {
			waitError = fmt.Errorf("%w: %s", waitError, detail)
		}
		client.mu.Lock()
		client.failure = waitError
		client.pending = make(map[int64]chan response)
		client.mu.Unlock()
		if client.event != nil && !client.expectedClose.Load() {
			message, _ := json.Marshal(waitError.Error())
			client.event("disconnected", message)
		}
		close(client.done)
	}()
	return client, nil
}

func (client *workerClient) Request(ctx context.Context, method string, params any) (json.RawMessage, error) {
	id := client.nextID.Add(1)
	data, err := json.Marshal(map[string]any{"version": 1, "id": id, "method": method, "params": params})
	if err != nil {
		return nil, err
	}
	if len(data)+1 > 64*1024 {
		return nil, errors.New("worker request exceeds 64 KiB")
	}
	channel := make(chan response, 1)
	client.mu.Lock()
	if client.failure != nil {
		err = client.failure
		client.mu.Unlock()
		return nil, err
	}
	client.pending[id] = channel
	client.mu.Unlock()
	defer func() { client.mu.Lock(); delete(client.pending, id); client.mu.Unlock() }()
	client.writeMu.Lock()
	_, err = client.input.Write(append(data, '\n'))
	client.writeMu.Unlock()
	if err != nil {
		return nil, fmt.Errorf("cannot send worker request: %w", err)
	}
	select {
	case reply := <-channel:
		if reply.Error != nil {
			return nil, errors.New(reply.Error.Message)
		}
		return reply.Result, nil
	case <-client.done:
		client.mu.Lock()
		err = client.failure
		client.mu.Unlock()
		return nil, err
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (client *workerClient) Close() {
	client.closeOnce.Do(func() { client.expectedClose.Store(true); client.input.Close() })
}

type diagnosticTail struct {
	mu   sync.Mutex
	text []byte
}

func (tail *diagnosticTail) Write(p []byte) (int, error) {
	tail.mu.Lock()
	defer tail.mu.Unlock()
	tail.text = append(tail.text, p...)
	if len(tail.text) > 32768 {
		tail.text = append([]byte(nil), tail.text[len(tail.text)-32768:]...)
	}
	return len(p), nil
}
func (tail *diagnosticTail) String() string {
	tail.mu.Lock()
	defer tail.mu.Unlock()
	return string(tail.text)
}
