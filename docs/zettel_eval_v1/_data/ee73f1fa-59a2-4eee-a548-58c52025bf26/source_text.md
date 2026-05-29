## Overview
- PsychoPy is a Python library for behavioral science experiments.

### Core argument
- PsychoPy is a Python library for behavioral science experiments.

### Architecture
- It serves as the core backend, with separate repositories (`psychopy/psychopy-studio`, `psychopy/psychopy-app`) providing modern web-based and legacy wxPython graphical user interfaces, respectively.
- Experiments can be executed locally as Python scripts or deployed online using JavaScript, supporting both a graphical Builder UI and direct Python coding.

### Stack
- Python, JavaScript, Go Template, numpy.

## Features and modules

### Overview
- PsychoPy is an open-source Python package for creating and running behavioral science experiments in fields like psychology, neuroscience, and psychophysics.
- The project aims to be precise enough for psychophysics, easy enough for teaching, and flexible for other uses.
- Experiments can be run as local Python scripts or online using JavaScript.
- It offers two interfaces: a graphical UI called Builder and direct Python coding.

### Architecture / Modules
- This repository contains only the PsychoPy library.
- The application UIs are in separate repositories: `psychopy/psychopy-studio` for the modern web-based GUI and `psychopy/psychopy-app` for the legacy wxPython GUI.

### Public API / Interfaces
- The public surface includes components prefixed with `/psy...`.
- Public surface: /psy....

### Operational Guidance
- Contributions are managed via forks and pull requests.
- Bug fixes are based on the `release` branch.
- New features are developed on the `dev` branch.
- Commits should be tagged with prefixes: BF (bug fix), FF (feature fix), RF (refactoring), NF (new feature), ENH (enhancement), DOC (documentation), and TEST.
- Usability signals: Experiments can be run as local Python scripts or online using JavaScript..

### Documentation
- Documentation is available on the project homepage.
- A YouTube channel provides additional resources.
- A textbook offers in-depth information.
- A Discourse forum is available for community support.
- A dedicated docs repository (`psychopy/psychopy-docs`) exists for documentation.

### Recent Issues / Development Status
- Recent releases include 2026.1.3.
- Identified bugs in `MovieStim` and `visual.TextStim` components.
- A breaking change in the `SerialDevice` wrapper has been noted.
- Memory leaks and font rendering inconsistencies are reported.
- Stdout update failures in the runner and crashes when opening multiple windows are issues.
- Dependency problems with `pypi-search` on older versions and `pyobjc` on Linux.
- Compatibility problems with Python 3.12+.
- Feature requests include merging experiments and automating translation file updates.
- Usability signals: 7 GitHub Actions workflows are used for continuous integration..

## Closing remarks
- Roadmap: Experiments can be executed locally as Python scripts or deployed online using JavaScript, supporting both a graphical Builder UI and direct Python coding.