## Overview
- OnionShare is predominantly a Python application (~95%) designed for secure and anonymous communication over the Tor network.

### Core argument
- OnionShare is predominantly a Python application (~95%) designed for secure and anonymous communication over the Tor network.

### Architecture
- Its architecture integrates Python for core logic, click for command-line interface parsing, and flask for serving temporary web services, which are rendered using JavaScript and HTML.
- This setup allows it to provide functionalities like anonymous file sharing, temporary website hosting, and private chat, all routed through Tor to ensure user privacy and censorship circum.

### Stack
- Python, JavaScript, HTML, click, flask.

## Features and modules

### Overview
- OnionShare is an open-source, cross-platform tool for secure and anonymous file sharing, website hosting, and chat using the Tor network.
- Available for Windows, macOS (direct download or Homebrew), and Linux (Flatpak or Snap package).
- Documentation built with Poetry and Sphinx, with translations managed on Weblate (requiring >90% completion for release inclusion).
- Usability signals: poetry install.

### Architecture / Modules
- Primarily written in Python (~95%).
- Utilizes the Tor network for secure and anonymous communication.
- Web interfaces likely use JavaScript and HTML.
- The CLI is built with click.

### Public API / Interfaces
- The tool is a command-line interface.
- Notable flags and paths include: `/OpenBSD`, `/.cache/onionshare`, `--cask`, `--log-filenames`, `--persistent`.
- Public surface: /OpenBSD, /.cache/onionshare, --cask, --log-filenames, --persistent.

### Operational Guidance
- Installation via `poetry install` is documented.
- Supports Python versions `>=3.10,<3.13`.
- Recent releases (v2.6.x) introduced a 'Quickstart' screen and automated censorship circumvention by fetching Tor bridges via an API.
- Version 2.6.3 added Gaeilge, Slovenčina, and Tamil locales and updated Snap packaging for Ubuntu 24.04, dropping armhf support while retaining ARM64.
- Version 2.6.2 set a 524,288-character limit for chat messages and restricted usernames to specific ASCII characters.
- Version 2.6.1 automated builds via CI and introduced a universal2 binary for macOS.
- Usability signals: poetry install.

## Closing remarks
- Roadmap: This setup allows it to provide functionalities like anonymous file sharing, temporary website hosting, and private chat, all routed through Tor to ensure user privacy and censorship circum.