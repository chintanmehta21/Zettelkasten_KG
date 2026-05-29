## Overview
- The repository provides bioinformatics workflows written in WDL for genomic characterization of public health pathogens.

### Core argument
- The repository provides bioinformatics workflows written in WDL for genomic characterization of public health pathogens.

### Architecture
- Workflows are categorized by pathogen type (e.g., , ) and are designed primarily for Terra.bio, but are also compatible with local or HPC execution using Cromwell or miniWDL.
- The codebase is predominantly WDL, with a small Python component, and leverages Docker images based on StaPH-B Docker Builds.

### Stack
- WDL, Python.

## Features and modules

### Overview
- Provides bioinformatics workflows for genomic characterization, submission preparation, and genomic epidemiology of public health pathogens, including viruses, bacteria, and fungi.
- Licensed under GNU AGPL v3.0.
- Maintained by Theiagen Genomics, committing to quarterly releases for new features and bug fixes, with urgent fixes released as needed.
- Docker images are based on StaPH-B Docker Builds.
- Extensive documentation is hosted on GitHub Pages.
- Support is available via GitHub issues or by emailing `support@theiagen.com`.
- Acknowledges influences from repositories like Andrew Lang's `genomic_analyses`, Broad's `viral-pipelines`, UPHL's `Cecret`, and Robert Petit's `bactopia`.
- Welcomes community contributions, providing code and documentation style guides.
- Recent activity includes release v4.1.0 and issues related to version updates (Freyja, Clair3), bug fixes (BaseSpace_Fetch failures, read_QC_trim hard failures), and feature requests (DENV characterization, AMRFinderPlus output enhancements).
- Users are directed to cite specific papers when publishing work using the workflows.

### Architecture / Modules
- Workflows are written predominantly in WDL (99.0% of the codebase) with a Python component (1.0%).
- All workflows are suffixed with `_PHB`.
- Workflows are categorized by pathogen type: `` & `` for viruses, `` for bacteria, and `` for fungi.
- Primarily designed for the Terra.bio platform.
- Can also be run locally or on HPC systems with Cromwell or miniWDL.

### Public API / Interfaces
- The email `@theiagen.com` is documented as a public interface for support.
- The endpoint `/center` is part of the public surface.
- The CLI flag `--pathogen` is available.
- The CLI flag `--Please` is available.
- Public surface: @theiagen.com, /center, --pathogen, --Please.

### Operational Guidance
- Workflows can be imported to Terra via the Dockstore PHB collection.
- Workflows can be run on Terra.bio, locally, or on HPC systems with Cromwell or miniWDL.
- Usability signals: Import to Terra via Dockstore PHB collection..

### Tests / Benchmarks / Examples
- The repository includes a `tests` directory.

## Benchmarks and examples
- The repository includes a `tests` directory for workflow validation.

## Closing remarks
- Roadmap: The codebase is predominantly WDL, with a small Python component, and leverages Docker images based on StaPH-B Docker Builds.