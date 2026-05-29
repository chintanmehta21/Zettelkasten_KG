## Overview
- In this tutorial, The speaker argues that the video demonstrates how to successfully compile and execute a go "hello world" application within a web browser using webassembly.

### Format and speakers
- Format: tutorial.
- Speakers: The speaker.

### Core argument
- The video demonstrates how to successfully compile and execute a Go "Hello World" application within a web browser using WebAssembly. It outlines the specific files, compilation steps, and JavaScript integration required to achieve this functionality.

## Chapter walkthrough

### Initial Project Setup
- Building a "Hello World" application in Go for browser execution via WebAssembly requires Go version 1.11 or later.
- The speaker specifically uses Go version 1.12 for the demonstration.
- The project necessitates four core files: `main.go`, `index.html`, the compiled `main.wasm`, and a JavaScript support file.
- The `wasm_exec.js` file is crucial for WebAssembly execution and is found within the Go installation at `$GOROOT/misc/wasm/`.
- A simple web server is needed to serve these files for browser access.

### Writing the Go Code
- The `main.go` file contains the primary `main` function for the application.
- Output to the browser's developer console is achieved using `fmt.Println`.
- To prevent the Go program from immediately exiting after execution, an empty channel is used to block the main goroutine.
- The blocking mechanism is implemented with `<-make(chan bool)`.
- This ensures the Wasm module remains active in the browser environment.

### Compiling Go to Wasm
- Go code is compiled into a WebAssembly module using a specific command.
- The compilation command is `GOOS=js GOARCH=wasm go build -o main.wasm`.
- `GOOS=js` targets the JavaScript environment, and `GOARCH=wasm` specifies the WebAssembly architecture.
- The output file, `main.wasm`, is generated from the Go source.
- A simple "Hello World" `main.wasm` file is approximately 2 MB due to the inclusion of the Go runtime.

### Loading Wasm in HTML
- The `index.html` file must first include the `wasm_exec.js` script to provide necessary WebAssembly support.
- A script within the HTML instantiates the Wasm module using `WebAssembly.instantiateStreaming`.
- This instantiation fetches the `main.wasm` file from the server.
- It also passes `go.importObject` from a new `Go()` instance, which handles Go-specific imports.
- Finally, `go.run(result.instance)` executes the compiled Go WebAssembly code within the browser.

### DOM Interaction
- The `syscall/js` package in Go enables direct interaction with the browser's Document Object Model (DOM).
- The global document object can be accessed via `js.Global().Get("document")`.
- New HTML elements are created using `document.Call("createElement", "h2")`.
- Properties of elements, such as `innerHTML`, are set using `element.Set(...)`.
- Elements are appended to the DOM, for example, to the body, using `document.Get("body").Call("appendChild", element)`.
- This package allows Go code to dynamically manipulate web page content.

## Demonstrations
- A "Hello World" application demonstrating basic Go code execution in a browser.
- An example of Go code interacting with the browser's DOM to create and append HTML elements.

## Closing remarks
- Recap: Go can be effectively compiled to WebAssembly, allowing developers to run Go applications directly in web browsers. This capability opens up new possibilities for web development by leveraging Go's performance and concurrency features on the client side.