## Overview
- The rapid7/metasploit-framework is an open-source tool written primarily in Ruby (94.8%), with smaller portions in PowerShell (2.7%), C (1.3%), and Python (0.5%).

### Core argument
- The rapid7/metasploit-framework is an open-source tool written primarily in Ruby (94.8%), with smaller portions in PowerShell (2.7%), C (1.3%), and Python (0.5%).

### Architecture
- It functions as a penetration testing framework, featuring exploit modules (e.g., for CVE-2026-9082, CVE-2024-27822, CVE-2026-34197, CVE-2026-45087, Peyara Remote Mouse RCE), persistence modules (e.g., Windows Print Processor), and scanners (`gitlab_version`, `http_version`).
- The project uses GitHub Actions for workflows and a `build.r.

### Stack
- Ruby, PowerShell, C, Python.

## Features and modules

### Overview
- The rapid7/metasploit-framework is an open-source tool.
- It is released under a BSD-style license, detailed in the `COPYING` file.
- Documentation is available at docs.metasploit.com, generated from `metasploit-framework.wiki/` markdown files using a `build.rb` script.
- Community support channels include GitHub Discussions, a Metasploit Slack, and GitHub Issues (using `MSF-BUGv1` form).
- Updates are posted on X (@metasploit) and Mastodon (@infosec.exchange | @metasploit.com | @rapid7.com).
- The project adheres to a Code of Conduct adapted from the Contributor Covenant v1.3.0, with reporting contacts at msfdev@metasploit.com.

### Architecture / Modules
- The framework is primarily written in Ruby (94.8%), with additional components in PowerShell (2.7%), C (1.3%), and Python (0.5%).
- It includes exploit modules, such as those for CVE-2026-9082 (Drupal Core SQLi), CVE-2024-27822 (macOS priv-esc), CVE-2026-34197 (ActiveMQ Jolokia RCE), CVE-2026-45087 (Dalfox RCE), and Peyara Remote Mouse RCE.
- Persistence modules are available, including a new Windows Print Processor module.
- Ongoing work involves improving existing modules (e.g., SSH modules, persistence modules using `create_process`).
- Scanner modules include `gitlab_version` and `http_version`, with ongoing fixes.
- Module disclosure dates are being standardized to YYYY-MM-DD format.

### Public API / Interfaces
- The primary command-line interface is `msfconsole`.
- The `msfvenom` tool uses flags such as `--list formats` and `--list-options`.
- Social media presence includes @metasploit on X and @infosec.exchange, @metasploit.com, @rapid7.com on Mastodon.
- Public surface: msfconsole, --list formats, --list-options, @infosec.exchange, @metasploit.com, @rapid7.com.

### Operational guidance
- Recommended installation is via official nightly installers for Linux or macOS.
- The framework comes pre-installed with Kali Linux.
- Contributions can be code-free (e.g., bug reports, testing PRs, documentation) or code-based.
- New developers are guided to port verified proof-of-concept exploits from ExploitDB.
- Usability signals: official nightly installers for Linux or macOS, pre-installed with Kali Linux.

## Closing remarks
- Roadmap: The core public interface is the `msfconsole` command, along with `msfvenom` flags like `--list formats` and `--list-options`.