## Overview
- Sherlock is a Python-based command-line tool designed for Open Source Intelligence (OSINT), enabling users to find social media accounts by username across over 400 networks.

### Core argument
- Sherlock is a Python-based command-line tool designed for Open Source Intelligence (OSINT), enabling users to find social media accounts by username across over 400 networks.

### Architecture
- Its core functionality relies on a `data.json` file that defines the searchable sites.
- The tool is primarily implemented in Python, with supporting components in Dockerfile and Shell, facilitating broad installation and usage across various environments.

### Stack
- Python, Dockerfile, Shell, argparse.

## Features and modules

### Overview
- Sherlock is a Python-based command-line tool for Open Source Intelligence (OSINT) that finds social media accounts by username across over 400 networks.
- The project is licensed under MIT and was created by Siddharth Dushantha.
- The latest version is 0.16.0.

### Architecture / Modules
- Its core logic relies on a `data.json` file to define searchable sites.
- The tool is primarily written in Python (97.3%), with minor parts in Dockerfile (2.1%) and Shell (0.6%).
- The default behavior prioritizes the local `data.json` file.

### Public API / Interfaces
- The tool is invoked with `sherlock user1 [user2 ...]`, and results are saved to a text file named after the username (e.g., `user123.txt`).
- It supports multiple output formats including CSV (`--csv`) and XLSX (`--xlsx`).
- Key command-line options include specifying an output file/folder, limiting searches to specific sites (`--site`), using a proxy (`--proxy`), setting a request timeout (default 60s), and including NSFW sites (`--nsfw`).
- The `--update` flag was added to fetch the latest version of `data.json`.
- Public surface: sherlock user1 [user2 ...], --csv, --xlsx, --site, --proxy, --nsfw.

### Operational Guidance
- Installation is supported via `pipx`, `pip`, `uv`, Docker (`docker run -it --rm sherlock/sherlock`), and `dnf`.
- Community-maintained packages exist for Debian (>=13), Ubuntu (>=22.10), Homebrew, Kali, and BlackArch.
- Third-party packages for ParrotOS and Ubuntu 24.04 are noted as broken.
- Usability signals: pipx, pip, uv, docker run -it --rm sherlock/sherlock, dnf, Debian (>=13).

### Recent Developments
- Recent development activity includes fixing a crash when usernames end in a period (issue #2970).
- Addressed numerous false positives (e.g., on TikTok due to SlardarWAF, and on sites using AWS WAF) and false negatives.
- Fixed a command injection vulnerability.
- Improved Ctrl+C responsiveness and enhanced URL encoding for usernames.
- There are ongoing efforts to add a PyQt5 GUI.

## Closing remarks
- Roadmap: The tool is primarily implemented in Python, with supporting components in Dockerfile and Shell, facilitating broad installation and usage across various environments.